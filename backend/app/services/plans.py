"""Plan orchestration. LLM divides tasks; code owns dates, state and authorization."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from ..agents.plan_coach.contract import (
    Availability,
    BusyInterval,
    CompletionEvent,
    Concept,
    ItemStatus,
    PlannerInput,
    PlannerOutput,
    Task,
)
from ..agents.plan_coach.fixtures import demo_catalog
from ..agents.plan_coach.llm import PlannerFailureError, PlanSettings, divide_tasks, provider
from ..agents.plan_coach.scheduler import PlanValidationError, schedule, validate_plan, week_key
from ..db import database
from ..onboarding.catalog import load_catalog
from ..repositories.plans import PlanError, PlanRepository, digest, encode
from ..repositories.profiles import ProfileRepository


def suggested_concepts(needs, plan_concept_ids) -> list[str]:
    """Concept trong danh mục Plan khớp tên hoặc alias với chủ đề người học cần (vd "RAG Pipeline" -> ai.rag_pipeline)."""
    names = {}
    for c in load_catalog():
        for name in (c.name, *c.aliases):
            names.setdefault(name.casefold().strip(), c.id)
    ids = (names.get(str(n.get("topic", "")).casefold().strip()) for n in needs)
    return list(dict.fromkeys(cid for cid in ids if cid in plan_concept_ids))


class PlanService:
    def __init__(self, settings=None, llm_factory=None, clock=None):
        self.settings = settings or PlanSettings()
        self.llm_factory = llm_factory or provider
        self.clock = clock or (lambda: datetime.now(UTC))

    def catalog(self):
        if not self.settings.catalog_path:
            return demo_catalog(), {}, "demo"
        try:
            raw = json.loads(Path(self.settings.catalog_path).read_text(encoding="utf-8"))
            concepts = [Concept.model_validate(c) for c in raw["concepts"]]
        except (OSError, ValueError, KeyError, TypeError):
            raise PlanError("BAD_CATALOG", "Danh mục concept của team chưa sẵn sàng hoặc không hợp lệ", 503) from None
        resources = raw.get("resources", {})
        if not isinstance(resources, dict) or not all(
            isinstance(k, str) and isinstance(v, str) and v.startswith("https://") for k, v in resources.items()
        ):
            raise PlanError("BAD_CATALOG", "Danh mục nguồn học của team không hợp lệ", 503)
        return concepts, resources, "team"

    def busy_intervals(self, db, members):
        result = {}
        for m in members:
            rows = db.execute(
                "SELECT scheduled_start,scheduled_end FROM study_sessions WHERE (learner_id=? OR helper_id=?) AND scheduled_start IS NOT NULL AND scheduled_end IS NOT NULL",
                (m.user_id, m.user_id),
            ).fetchall()
            try:
                result[m.user_id] = [BusyInterval(start=r[0], end=r[1]) for r in rows]
            except ValueError:
                raise PlanError(
                    "SESSION_TIME_INVALID", "Lịch phiên học có thời gian thiếu múi giờ; cần sửa lịch phiên học", 422
                ) from None
        return result

    def setup(self, pair_id, user):
        with database() as db:
            pair = PlanRepository(db).pair(pair_id, user)
            members = []
            for uid in (pair["user_a_id"], pair["user_b_id"]):
                bundle = ProfileRepository(db).get_profile_bundle(uid)
                if not bundle:
                    raise PlanError("PROFILE_MISSING", "Thành viên chưa có hồ sơ", 422)
                members.append(
                    {
                        "user_id": uid,
                        "display_name": bundle["profile"]["display_name"],
                        "goals": bundle["profile"]["learning_goals"],
                        "needs": bundle["needs_help_with"],
                        "strengths": bundle["can_help_with"],
                        "availability": bundle["availability"],
                    }
                )
        concepts, resources, source = self.catalog()
        plan_ids = {c.id for c in concepts}
        for m in members:
            m["suggested_concept_ids"] = suggested_concepts(m["needs"], plan_ids)
        return {
            "pair_id": pair_id,
            "members": members,
            "concepts": [c.model_dump(mode="json") for c in concepts],
            "resources": resources,
            "catalog_source": source,
            "provider_mode": self.settings.llm_provider,
            "dependencies": [
                "AI Data 1: chọn concept/đã biết, cam kết và deadline cần xác nhận",
                "AI Vision: sự kiện check-in xác nhận",
                "AI Data 1: metric",
                "SE/PO: adapter gửi và cron",
            ],
        }

    def read(self, pair_id, user):
        with database() as db:
            repo = PlanRepository(db)
            pair = repo.pair(pair_id, user)
            row = repo.active(pair_id, user["id"])
            partner_uid = pair["user_b_id"] if pair["user_a_id"] == user["id"] else pair["user_a_id"]
            partner = repo.active(pair_id, partner_uid)
            partner_summary = None
            if partner:
                p = repo.hydrated(partner)
                context, _ = repo.context(partner)
                member = next(m for m in context.members if m.user_id == partner_uid)
                partner_summary = {
                    "user_id": partner_uid,
                    "goal": member.goal,
                    "version": p.plan_version,
                    "scheduled_count": len(p.items),
                    "completed_count": sum(i.status == ItemStatus.COMPLETED for i in p.items),
                    "deferred_count": len(p.deferred_items),
                    "partial": p.partial,
                    "items": [i.model_dump(mode="json") for i in p.items],
                }
            draft = db.execute(
                "SELECT * FROM pb_plans WHERE pair_id=? AND user_id=? AND status='DRAFT' ORDER BY version DESC LIMIT 1",
                (pair_id, user["id"]),
            ).fetchone()
            if not row:
                return {"plan": None, "partner": partner_summary, "proposal": None}
            ctx, _ = repo.context(row)
            member = next(m for m in ctx.members if m.user_id == user["id"])
            trace = db.execute(
                "SELECT body FROM pb_traces WHERE pair_id=? AND kind='planner' ORDER BY created_at DESC,id DESC LIMIT 1",
                (pair_id,),
            ).fetchone()
            return {
                "id": row["id"],
                "plan": repo.hydrated(row).model_dump(mode="json"),
                "timezone": member.timezone,
                "goal": member.goal,
                "partner": partner_summary,
                "catalog_source": ctx.catalog_source,
                "resources": ctx.resources,
                "provider_mode": json.loads(trace["body"])["provider_mode"] if trace else "unknown",
                "proposal": self._proposal(repo, dict(draft)) if draft else None,
            }

    def edit_schedule(self, pair_id, user, item_id, payload):
        now = self.clock()
        start = payload.scheduled_start
        if start.tzinfo is None:
            raise PlanError("TIMEZONE", "Giờ học phải có múi giờ.", 422)
        start = start.astimezone(UTC)
        end = start + timedelta(minutes=payload.minutes)
        if start < now or start > now + timedelta(days=365):
            raise PlanError("TIME_RANGE", "Chọn giờ học trong tương lai, tối đa một năm.", 422)
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            repo = PlanRepository(db)
            repo.pair(pair_id, user)
            row = repo.active(pair_id, user["id"])
            if not row:
                raise PlanError("NO_PLAN", "Bạn chưa có kế hoạch.", 404)
            if row["version"] != payload.expected_version:
                raise PlanError("STALE_PLAN", "Lịch vừa thay đổi. Tải lại trước khi sửa.", 409)
            own = repo.hydrated(row)
            item = next((i for i in own.items + own.deferred_items if i.id == item_id), None)
            if not item:
                raise PlanError("NOT_OWN_ITEM", "Chỉ được sửa việc trong lịch của mình.", 403)
            if item.status == ItemStatus.COMPLETED:
                raise PlanError("DONE_ITEM", "Việc đã hoàn thành được giữ trong nhật ký.", 409)
            for other in own.items:
                if other.id != item_id and other.scheduled_start and other.scheduled_end and start < other.scheduled_end and end > other.scheduled_start:
                    raise PlanError("OVERLAP", "Giờ này trùng một việc khác của bạn.", 422)
            ctx, caps = repo.context(row)
            member = next(m for m in ctx.members if m.user_id == user["id"])
            for busy in self.busy_intervals(db, [member]).get(user["id"], []):
                if start < busy.end and end > busy.start:
                    raise PlanError("SESSION_OVERLAP", "Giờ này trùng một phiên học đã đặt.", 422)
            concepts = {c.id: c for c in ctx.concepts}
            for other in own.items + own.deferred_items:
                if other.id == item.id:
                    continue
                if other.concept_id in concepts[item.concept_id].prerequisites and other.status != ItemStatus.COMPLETED and (not other.scheduled_end or other.scheduled_end > start):
                    raise PlanError("PREREQUISITE", "Xếp việc này sau việc cần học trước.", 422)
                if item.concept_id in concepts[other.concept_id].prerequisites and other.status != ItemStatus.COMPLETED and other.scheduled_start and end > other.scheduled_start:
                    raise PlanError("DEPENDENT", "Xếp việc này trước việc học tiếp theo.", 422)
            item.scheduled_start, item.scheduled_end = start, end
            item.est_minutes, item.status = payload.minutes, ItemStatus.SCHEDULED
            item.defer_reason, item.slot_id = None, None
            item.if_then_text = "Đến giờ đã chọn, mình dành thời gian cho: " + item.action
            if item in own.deferred_items:
                own.deferred_items.remove(item)
                own.items.append(item)
            own.items.sort(key=lambda i: i.scheduled_start or now)
            own.partial = bool(own.deferred_items)
            own.plan_version = repo.next_version(pair_id, user["id"])
            for i in own.items + own.deferred_items:
                i.plan_version = own.plan_version
            db.execute("UPDATE pb_plans SET status='SUPERSEDED' WHERE id=?", (row["id"],))
            db.execute("UPDATE pb_plans SET status='REJECTED' WHERE pair_id=? AND user_id=? AND status='DRAFT'", (pair_id, user["id"]))
            new_id = repo.insert(own, ctx, now, base=row["id"], reason="Bạn tự điều chỉnh lịch", caps=caps)
            repo.trace(pair_id, "schedule_edited", {"user_id": user["id"], "item_id": item_id, "version": own.plan_version}, now)
        return {"plan_id": new_id, "plan_version": own.plan_version}

    def traces(self, pair_id, user):
        with database() as db:
            PlanRepository(db).pair(pair_id, user)
            rows = db.execute(
                "SELECT id,kind,body,created_at FROM pb_traces WHERE pair_id=? ORDER BY created_at DESC,id DESC LIMIT 30",
                (pair_id,),
            ).fetchall()
            return {
                "traces": [
                    {"id": r["id"], "kind": r["kind"], "body": json.loads(r["body"]), "created_at": r["created_at"]}
                    for r in rows
                ]
            }

    async def generate(self, request, user, request_key):
        if not 1 <= len(request_key) <= 120:
            raise PlanError("REQUEST_KEY", "Cần Idempotency-Key dài 1–120 ký tự", 422)
        now, fingerprint, token = self.clock(), digest(request), uuid4().hex
        setup = self.setup(request.pair_id, user)
        if {m.user_id for m in request.members} != {m["user_id"] for m in setup["members"]}:
            raise PlanError("MEMBER_MISMATCH", "Hai thành viên phải khớp peer_matches", 403)
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            repo = PlanRepository(db)
            old = db.execute(
                "SELECT * FROM pb_plan_requests WHERE pair_id=? AND actor_id=? AND request_key=?",
                (request.pair_id, user["id"], request_key),
            ).fetchone()
            if old:
                if old["request_hash"] != fingerprint:
                    raise PlanError("KEY_REUSED", "Idempotency-Key đã dùng cho nội dung khác")
                if old["status"] == "DONE":
                    return json.loads(old["result"])
                if old["status"] == "PENDING" and now - datetime.fromisoformat(old["created_at"]) < timedelta(
                    minutes=5
                ):
                    raise PlanError("IN_PROGRESS", "Yêu cầu đang được xử lý; thử đọc plan sau ít phút")
                db.execute(
                    "UPDATE pb_plan_requests SET status='PENDING',owner_token=?,created_at=? WHERE id=?",
                    (token, now.isoformat(), old["id"]),
                )
            else:
                db.execute(
                    "INSERT INTO pb_plan_requests(pair_id,actor_id,request_key,request_hash,owner_token,status,created_at) VALUES (?,?,?,?,?,'PENDING',?)",
                    (request.pair_id, user["id"], request_key, fingerprint, token, now.isoformat()),
                )
            if any(repo.active(request.pair_id, m.user_id) for m in request.members):
                raise PlanError("PLAN_EXISTS", "Cặp đã có plan; dùng phương án điều chỉnh")
            for m in request.members:
                if db.execute(
                    "SELECT 1 FROM pb_plans WHERE user_id=? AND pair_id<>? AND status='ACTIVE'",
                    (m.user_id, request.pair_id),
                ).fetchone():
                    raise PlanError(
                        "ACTIVE_PLAN_ELSEWHERE", "MVP chỉ giữ một plan hoạt động/người để bảo đảm ngân sách tuần"
                    )
            version = max(repo.next_version(request.pair_id, m.user_id) for m in request.members)
        # Reuse profile availability if already present; no second profile system.
        members = []
        for m in request.members:
            bundle = next(x for x in setup["members"] if x["user_id"] == m.user_id)
            try:
                if bundle["availability"]:
                    zones = {w["timezone"] for w in bundle["availability"]}
                    if len(zones) != 1:
                        raise PlanError("MIXED_TIMEZONES", "Cần thống nhất múi giờ trong hồ sơ", 422)
                    m = m.model_copy(
                        update={
                            "availability": [
                                Availability.model_validate(
                                    {
                                        "id": str(w["id"]),
                                        "day_of_week": w["day_of_week"],
                                        "start_time": w["start_time"],
                                        "end_time": w["end_time"],
                                    }
                                )
                                for w in bundle["availability"]
                            ],
                            "timezone": zones.pop(),
                        }
                    )
                m = type(m).model_validate(m.model_dump(mode="json"))
            except PlanError:
                self._fail_request(request.pair_id, user["id"], request_key, token)
                raise
            except ValueError:
                self._fail_request(request.pair_id, user["id"], request_key, token)
                raise PlanError(
                    "PROFILE_PLAN_CONSTRAINTS",
                    "Múi giờ hoặc khung giờ trong hồ sơ không hợp lệ cho Plan; cần cập nhật hồ sơ",
                    422,
                ) from None
            members.append(m)
        ctx = PlannerInput(
            pair_id=request.pair_id,
            members=members,
            concepts=setup["concepts"],
            resources=setup["resources"],
            planning_start=now,
            horizon_days=request.horizon_days,
            plan_version=version,
            catalog_source=setup["catalog_source"],
        )
        trace = None
        try:
            try:
                llm = self.llm_factory(ctx, self.settings)
            except ValueError:
                raise PlanError("PROVIDER_CONFIGURATION", "Provider chưa được cấu hình đầy đủ", 503) from None
            tasks, trace = await divide_tasks(ctx, llm, self.settings.llm_timeout_seconds)
            with database() as db:
                db.execute("BEGIN IMMEDIATE")
                repo = PlanRepository(db)
                # Refresh the anchor after generation. A one-minute lead avoids saving work already in the past.
                ctx = ctx.model_copy(
                    update={
                        "planning_start": self.clock() + timedelta(minutes=1),
                        "busy_intervals": self.busy_intervals(db, ctx.members),
                    }
                )
                output = schedule(ctx, tasks)
                validate_plan(ctx, output)
                owner = db.execute(
                    "SELECT owner_token,status FROM pb_plan_requests WHERE pair_id=? AND actor_id=? AND request_key=?",
                    (ctx.pair_id, user["id"], request_key),
                ).fetchone()
                if not owner or owner["owner_token"] != token or owner["status"] != "PENDING":
                    raise PlanError("REQUEST_CHANGED", "Yêu cầu đã được tiếp quản; đọc lại plan")
                if any(repo.active(ctx.pair_id, m.user_id) for m in ctx.members):
                    raise PlanError("PLAN_EXISTS", "Plan đã được tạo đồng thời; đọc lại plan")
                for m in ctx.members:
                    if db.execute(
                        "SELECT 1 FROM pb_plans WHERE user_id=? AND pair_id<>? AND status='ACTIVE'",
                        (m.user_id, ctx.pair_id),
                    ).fetchone():
                        raise PlanError("ACTIVE_PLAN_ELSEWHERE", "Thành viên đã có plan ở cặp khác; tải lại")
                ids = {p.user_id: repo.insert(p, ctx, now) for p in output.plans}
                trace_id = repo.trace(ctx.pair_id, "planner", trace, now)
                result = {
                    "plan_ids": ids,
                    "version": version,
                    "trace_id": trace_id,
                    "partial": any(p.partial for p in output.plans),
                    "provider_mode": trace["provider_mode"],
                    "catalog_source": ctx.catalog_source,
                }
                db.execute(
                    "UPDATE pb_plan_requests SET status='DONE',result=? WHERE pair_id=? AND actor_id=? AND request_key=? AND owner_token=?",
                    (encode(result), ctx.pair_id, user["id"], request_key, token),
                )
            from ..agents.plan_coach.tracing import export_db_trace

            await asyncio.to_thread(
                export_db_trace,
                self.settings,
                "planner",
                trace,
                trace_id,
                {"plan_ids": list(ids.values()), "plan_version": version},
            )
            return result
        except Exception as error:
            self._fail_request(ctx.pair_id, user["id"], request_key, token)
            if isinstance(error, PlannerFailureError):
                with database() as db:
                    error.trace_id = PlanRepository(db).trace(ctx.pair_id, "planner_error", error.trace, now)
                from ..agents.plan_coach.tracing import export_db_trace

                await asyncio.to_thread(export_db_trace, self.settings, "planner_error", error.trace, error.trace_id)
            elif isinstance(error, PlanValidationError):
                error_body = {**(trace or {}), "validation_errors": [i.model_dump(mode="json") for i in error.issues]}
                with database() as db:
                    error_trace_id = PlanRepository(db).trace(
                        ctx.pair_id,
                        "planner_error",
                        error_body,
                        now,
                    )
                from ..agents.plan_coach.tracing import export_db_trace

                await asyncio.to_thread(export_db_trace, self.settings, "planner_error", error_body, error_trace_id)
            raise

    def _fail_request(self, pair_id, uid, key, token):
        with database() as db:
            db.execute(
                "UPDATE pb_plan_requests SET status='FAILED' WHERE pair_id=? AND actor_id=? AND request_key=? AND owner_token=? AND status='PENDING'",
                (pair_id, uid, key, token),
            )

    def complete(self, event: CompletionEvent):
        now = self.clock()
        if event.confirmed_at > now:
            raise PlanError("FUTURE_CHECKIN", "Thời điểm xác nhận không được ở tương lai", 422)
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            repo = PlanRepository(db)
            old = db.execute(
                "SELECT event_hash FROM pb_completion_events WHERE event_id=?", (event.event_id,)
            ).fetchone()
            if old:
                if old["event_hash"] != digest(event):
                    raise PlanError("EVENT_CONFLICT", "event_id đã dùng cho nội dung khác")
                return {"applied": False, "duplicate": True}
            row = db.execute(
                "SELECT * FROM pb_plans WHERE pair_id=? AND user_id=? AND version=? AND status IN ('ACTIVE','SUPERSEDED')",
                (event.pair_id, event.user_id, event.plan_version),
            ).fetchone()
            active = repo.active(event.pair_id, event.user_id)
            if not row or not active:
                raise PlanError("CHECKIN_PLAN", "Phiên bản plan không hợp lệ", 422)
            historic = repo.hydrated(dict(row))
            current = repo.hydrated(active)
            item = next((i for i in historic.items if i.id == event.plan_item_id), None)
            if not item or not any(i.id == item.id for i in current.items + current.deferred_items):
                raise PlanError("CHECKIN_ITEM", "Check-in không tham chiếu việc đã xếp của thành viên", 422)
            if item.scheduled_start and event.confirmed_at < item.scheduled_start:
                raise PlanError("EARLY_CHECKIN", "Check-in trước thời điểm thực hiện việc", 422)
            # A moved scheduled item keeps its identity, including a late event on an old version.
            db.execute(
                "INSERT INTO pb_completion_events(event_id,item_id,event_hash,confirmed_at) VALUES (?,?,?,?)",
                (event.event_id, item.id, digest(event), event.confirmed_at.isoformat()),
            )
            applied = (
                db.execute(
                    "UPDATE pb_plan_items SET completed_at=?,completed_payload=? WHERE id=? AND completed_at IS NULL",
                    (event.confirmed_at.isoformat(), encode(item), item.id),
                ).rowcount
                == 1
            )
            return {"applied": applied, "duplicate": not applied}

    def _proposal(self, repo, row):
        base = repo.plan(row["base_plan_id"], row["pair_id"], row["user_id"])
        ctx, caps = repo.context(row)
        member = next(m for m in ctx.members if m.user_id == row["user_id"])
        # Use the draft's progress snapshot, not live completion events arriving
        # after preview. Acceptance separately rejects any changed progress.
        draft = repo.hydrated(row)
        stored = type(draft).model_validate_json(row["payload"])
        budgets = []
        for (uid, week), cap in sorted(caps.items()):
            if uid != row["user_id"]:
                continue
            baseline = member.committed_minutes_per_week * 4 // 5
            completed = sum(
                i.est_minutes
                for i in stored.items
                if i.status == ItemStatus.COMPLETED and week_key(i.scheduled_start, member) == week
            )
            budgets.append(
                {
                    "week_start": week,
                    "baseline_minutes": baseline,
                    "completed_minutes": completed,
                    "remaining_minutes": max(0, baseline - completed),
                    "proposed_limit_minutes": cap,
                }
            )
        return {
            "id": row["id"],
            "status": row["status"],
            "expected_version": base["version"],
            "reason": row["reason"],
            "cutoff": row["cutoff"],
            "budget": budgets,
            "before": repo.hydrated(base).model_dump(mode="json"),
            "after": draft.model_dump(mode="json"),
        }

    def replan(self, pair_id, user, request):
        now = self.clock()
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            repo = PlanRepository(db)
            repo.pair(pair_id, user)
            active = repo.active(pair_id, user["id"])
            if not active or active["version"] != request.expected_version:
                raise PlanError("STALE_PLAN", "Plan đã thay đổi; tải lại trước khi điều chỉnh")
            original, _ = repo.context(active)
            end = original.planning_start + timedelta(days=original.horizon_days)
            member = next(m for m in original.members if m.user_id == user["id"])
            end = min(end, member.deadline or end)
            # Expired horizon yields a controlled response, without inventing a new deadline.
            if now >= end:
                raise PlanError(
                    "HORIZON_EXPIRED", "Khoảng lập kế hoạch/deadline đã hết; cần chốt mục tiêu và mốc mới", 422
                )
            anchor = now + timedelta(minutes=1)
            if anchor >= end:
                raise PlanError("HORIZON_TOO_SHORT", "Không còn đủ thời gian để xem và xác nhận lịch mới", 422)
            p = repo.hydrated(active)
            prior = p.items + p.deferred_items
            done = [i for i in prior if i.status == ItemStatus.COMPLETED]
            version = repo.next_version(pair_id, user["id"])
            # Keep the original end by shortening deadlines; fresh cutoff never compounds reduction.
            members = [
                m.model_copy(update={"deadline": end}) if m.user_id == user["id"] else m for m in original.members
            ]
            ctx = original.model_copy(
                update={
                    "planning_start": anchor,
                    "horizon_days": min(28, max(1, int((end - now).total_seconds() // 86400) + 1)),
                    "plan_version": version,
                    "members": members,
                }
            )
            ctx.busy_intervals = self.busy_intervals(db, [m for m in ctx.members if m.user_id == user["id"]])
            caps = {}
            for m in ctx.members:
                for d in range(ctx.horizon_days + 1):
                    wk = week_key(now + timedelta(days=d), m)
                    completed_spent = sum(
                        i.est_minutes for i in done if i.user_id == m.user_id and week_key(i.scheduled_start, m) == wk
                    )
                    remaining = max(0, m.committed_minutes_per_week * 4 // 5 - completed_spent)
                    caps[m.user_id, wk] = remaining * 4 // 5 if request.reduce_load else remaining
            tasks = [
                Task.model_validate({k: i.model_dump()[k] for k in Task.model_fields})
                for i in prior
                if i.status != ItemStatus.COMPLETED
            ]
            output = schedule(ctx, tasks, completed=done, previous=prior, budget_caps=caps, user_ids={user["id"]})
            own = next(p for p in output.plans if p.user_id == user["id"])
            # Older pending proposals remain history and cannot be accepted.
            db.execute(
                "UPDATE pb_plans SET status='REJECTED' WHERE pair_id=? AND user_id=? AND status='DRAFT'",
                (pair_id, user["id"]),
            )
            pid = repo.insert(
                own,
                ctx,
                now,
                status="DRAFT",
                base=active["id"],
                progress=repo.progress_hash(active),
                reason=request.reason,
                caps=caps,
            )
            repo.trace(
                pair_id,
                "replan",
                {
                    "user_id": user["id"],
                    "proposal_id": pid,
                    "base_version": active["version"],
                    "cutoff": now.isoformat(),
                    "reduction": 0.2 if request.reduce_load else 0,
                },
                now,
            )
            return self._proposal(repo, repo.plan(pid, pair_id, user["id"]))

    def decide_proposal(self, pair_id, proposal_id, user, expected_version, accept):
        now = self.clock()
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            repo = PlanRepository(db)
            repo.pair(pair_id, user)
            proposal = repo.plan(proposal_id, pair_id, user["id"])
            if proposal["base_plan_id"] is None:
                raise PlanError("NOT_PROPOSAL", "Đây không phải phương án điều chỉnh")
            base = repo.plan(proposal["base_plan_id"], pair_id, user["id"])
            if base["version"] != expected_version:
                raise PlanError("STALE_PLAN", "Phiên bản trước/sau không khớp")
            if proposal["status"] == "ACTIVE" and accept:
                return {"applied": False, "duplicate": True, "plan_id": proposal_id}
            if proposal["status"] == "REJECTED" and not accept:
                return {"applied": False, "duplicate": True, "plan_id": proposal_id}
            active = repo.active(pair_id, user["id"])
            if proposal["status"] != "DRAFT" or not active or active["id"] != base["id"]:
                raise PlanError("STALE_PROPOSAL", "Phương án không còn áp dụng được; tạo phương án mới")
            if accept:
                if repo.progress_hash(active) != proposal["progress_hash"]:
                    raise PlanError("PROGRESS_CHANGED", "Có check-in mới; tạo lại phương án để giữ tiến độ")
                ctx, caps = repo.context(proposal)
                ctx.busy_intervals = self.busy_intervals(db, [m for m in ctx.members if m.user_id == user["id"]])
                # Revalidate only the consenting person's proposal; companion deadlines/progress are independent.
                own = repo.hydrated(proposal)
                if any(i.status == ItemStatus.SCHEDULED and i.scheduled_start < now for i in own.items):
                    raise PlanError("PROPOSAL_EXPIRED", "Giờ trong phương án đã qua; tạo lại phương án")
                validate_plan(ctx, PlannerOutput(pair_id=pair_id, plans=[own]), budget_caps=caps, user_ids={user["id"]})
                db.execute("UPDATE pb_plans SET status='SUPERSEDED' WHERE id=?", (active["id"],))
                db.execute(
                    "UPDATE pb_plans SET status='ACTIVE',accepted_at=? WHERE id=?", (now.isoformat(), proposal_id)
                )
                repo.trace(
                    pair_id,
                    "replan_accepted",
                    {"proposal_id": proposal_id, "user_id": user["id"], "base_version": expected_version},
                    now,
                )
            else:
                db.execute("UPDATE pb_plans SET status='REJECTED' WHERE id=?", (proposal_id,))
            return {"applied": accept, "duplicate": False, "plan_id": proposal_id}


def get_plan_service():
    return PlanService()
