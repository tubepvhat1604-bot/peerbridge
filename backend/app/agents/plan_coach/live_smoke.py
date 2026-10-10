"""Bounded synthetic Planner/Coach smoke. Never writes a plan or sends notifications."""

import argparse
import asyncio
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from .artifacts import claim_run, new_run_path, write_json
from .coach import allowed_actions
from .contract import MetricSnapshot
from .fixtures import synthetic_context
from .graph import CoachSelector
from .llm import PROMPT_VERSION, CompatibleLLM, PlannerFailureError, PlanSettings, divide_tasks
from .nudge import PROMPT_VERSION as NUDGE_PROMPT_VERSION
from .scheduler import PlanValidationError, schedule, validate_plan
from .tracing import identifier, safe_usage, valid_endpoint


class BudgetExhaustedError(RuntimeError):
    pass


class BudgetLLM:
    def __init__(self, llm, max_requests):
        if type(max_requests) is not int or not 1 <= max_requests <= 10:
            raise ValueError("REQUEST_LIMIT_MUST_BE_1_TO_10")
        self.llm, self.max_requests = llm, max_requests
        self.mode, self.model = llm.mode, llm.model
        self.records, self.halted = [], False
        self.usage = self.cost = None

    async def complete_json(self, system, user):
        self.usage = self.cost = None
        if self.halted or len(self.records) >= self.max_requests:
            raise BudgetExhaustedError("REQUEST_BUDGET_EXHAUSTED_OR_PROVIDER_REFUSED")
        record = {
            "request": len(self.records) + 1,
            "prompt_version": NUDGE_PROMPT_VERSION if "{action, message}" in system else PROMPT_VERSION,
            "started_at": datetime.now(UTC).isoformat(),
        }
        self.records.append(record)  # Claimed before awaiting; concurrent calls share this budget.
        started = time.perf_counter()
        try:
            return await self.llm.complete_json(system, user)
        except asyncio.CancelledError:
            record["error_code"] = "TimeoutOrCancelled"
            self.halted = True
            raise
        except Exception as error:
            code = (
                error.args[0]
                if isinstance(error, ValueError)
                and error.args
                and re.fullmatch(r"PROVIDER_[A-Z_0-9]+", str(error.args[0]))
                else type(error).__name__
            )
            record["error_code"] = code
            if str(code).startswith("PROVIDER_HTTP_") or code in (
                "PROVIDER_REFUSED",
                "PROVIDER_NETWORK_ERROR",
                "PROVIDER_OUTPUT_LIMIT",
            ):
                self.halted = True
            raise
        finally:
            self.usage = safe_usage(self.llm.usage)
            record["usage"] = self.usage
            record["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)


def configuration_status(settings):
    key = settings.llm_api_key.get_secret_value().strip()
    key_present = bool(key) and not any(s in key.lower() for s in ("your-", "your_", "xxxxx", "placeholder"))
    fields = {
        "PLAN_LLM_PROVIDER": "live_selected" if settings.llm_provider == "openai_compatible" else "not_live_selected",
        "PLAN_LLM_BASE_URL": "present_valid" if valid_endpoint(settings.llm_base_url) else "missing_or_invalid",
        "PLAN_LLM_API_KEY": "present" if key_present else "missing_or_placeholder",
        "PLAN_LLM_MODEL": "present_valid" if identifier(settings.llm_model) else "missing_or_invalid",
    }
    ready = fields == {
        "PLAN_LLM_PROVIDER": "live_selected",
        "PLAN_LLM_BASE_URL": "present_valid",
        "PLAN_LLM_API_KEY": "present",
        "PLAN_LLM_MODEL": "present_valid",
    }
    return {"fields": fields, "ready": ready}


async def run_smoke(settings, max_requests=10, llm=None):
    if type(max_requests) is not int or not 1 <= max_requests <= 10:
        raise ValueError("REQUEST_LIMIT_MUST_BE_1_TO_10")
    started = time.perf_counter()
    report = {
        "ran_at": datetime.now(UTC).isoformat(),
        "synthetic": True,
        "mode": "live" if llm is None else llm.mode,
        "model": settings.llm_model if identifier(settings.llm_model) else None,
        "planner_prompt_version": PROMPT_VERSION,
        "coach_prompt_version": NUDGE_PROMPT_VERSION,
        "request_limit": max_requests,
        "request_count": 0,
        "timeout_seconds": settings.llm_timeout_seconds,
        "max_output_tokens": settings.llm_max_output_tokens,
        "configuration": configuration_status(settings),
        "plan_persisted": False,
        "real_notification_sends": 0,
        "pilot": False,
    }
    if llm is None and not report["configuration"]["ready"]:
        report.update(status="CONFIGURATION_BLOCKED", latency_ms=0, requests=[], usage=None)
        return report
    budget = BudgetLLM(llm or CompatibleLLM(settings), max_requests)
    report["model"] = budget.model
    ctx = synthetic_context("normal")  # Development persona only; no old holdout tuning.
    trace = None
    try:
        tasks, trace = await divide_tasks(ctx, budget, settings.llm_timeout_seconds)
        output = schedule(ctx, tasks)
        validate_plan(ctx, output)
        report["planner"] = {
            "accepted": True,
            "validator_passed": True,
            "trace": trace,
            "output": output.model_dump(mode="json"),
            "partial_personal_plans": sum(p.partial for p in output.plans),
        }
        plans = {p.user_id: p for p in output.plans}
        ids = [m.user_id for m in ctx.members]
        metrics = MetricSnapshot(
            pair_id=ctx.pair_id,
            as_of=ctx.planning_start,
            source="SYNTHETIC_SMOKE_ONLY",
            plan_versions={i: plans[i].plan_version for i in ids},
            pacing={ids[0]: 0.6, ids[1]: 0.8},
            due_count={i: 1 for i in ids},
            last_checkin={i: None for i in ids},
        )
        reason, actions, concept = allowed_actions(ctx, plans, metrics, ids[0], ctx.planning_start)
        selection = await CoachSelector(budget, settings.llm_timeout_seconds).select(actions, reason, concept)
        report["coach"] = selection
        report["coach"]["allowed_actions"] = actions
        report["status"] = (
            "PASSED"
            if selection["mode"] == "v2" and selection["action"] != "no_action"
            else "COACH_NO_ACTION"
            if selection["action"] == "no_action"
            else "COACH_FALLBACK"
        )
        # Use the same notification contract, exclusively fake in this smoke.
        from ...services.coach import FakeNotification

        notification = FakeNotification()
        report["delivery_status"] = (
            notification.send(ids[0], selection["text"], trace["trace_id"])
            if selection["action"] != "no_action"
            else "NOT_APPLICABLE"
        )
        report["fake_notification_calls"] = len(notification.calls)
    except PlanValidationError as error:
        trace = error.trace if isinstance(error, PlannerFailureError) else trace
        report["planner"] = {
            "accepted": False,
            "validator_passed": False,
            "trace": trace,
            "error_codes": [i.code for i in error.issues],
        }
        report["status"] = "PLANNER_REJECTED"
    except Exception as error:
        report.update(status="CONTROLLED_FAILURE", error_code=type(error).__name__)
    report.update(
        request_count=len(budget.records),
        requests=budget.records,
        latency_ms=round((time.perf_counter() - started) * 1000, 3),
    )
    reported = [r["usage"] for r in budget.records if r.get("usage")]
    report["usage"] = (
        {k: sum(u.get(k, 0) for u in reported) for k in {k for u in reported for k in u}} if reported else None
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Report presence/validity only; never contact the LLM")
    parser.add_argument("--max-requests", type=int, choices=range(1, 11), default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[4]
    output = args.output or new_run_path(workspace / "docs/evidence/ai-data-2", "live-smoke")
    try:
        claim_run(output)
        try:
            settings = PlanSettings()
        except ValueError:
            report = {"status": "CONFIGURATION_INVALID", "request_count": 0, "error_code": "PLAN_SETTINGS_INVALID"}
        else:
            report = (
                {"status": "CONFIGURATION_CHECK", "request_count": 0, "configuration": configuration_status(settings)}
                if args.check
                else asyncio.run(run_smoke(settings, args.max_requests))
            )
        write_json(output / "results.json", report)
        print(
            json.dumps(
                {k: report[k] for k in ("status", "request_count", "configuration") if k in report}, ensure_ascii=False
            )
        )
    except (OSError, ValueError):
        parser.exit(2, "Smoke failed: invalid configuration or output directory already exists; no secret printed.\n")


if __name__ == "__main__":
    main()
