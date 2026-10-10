"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ConnectedPeerSummary } from "@/lib/types";
import type { CoachDecision, PlanItem, PlanMember, PlanSetup, PlanView } from "@/lib/plan-types";
import styles from "./StudyPlan.module.css";
import {formatDateTime, formatDate, toDateTimeInput, localInputToISO} from "@/lib/time";
import DateTimeField from "./DateTimeField";
import PlanNotes from "./PlanNotes";

const DAYS = ["Thứ hai", "Thứ ba", "Thứ tư", "Thứ năm", "Thứ sáu", "Thứ bảy", "Chủ nhật"];
const STATUS = { SCHEDULED: "Đã xếp lịch", COMPLETED: "Đã hoàn thành", DEFERRED: "Để sau" };
const DELIVERY_STATUS: Record<string, string> = {
  NOT_APPLICABLE: "Không có can thiệp cần gửi",
  RESERVED: "Đề xuất đang được xử lý; chưa gửi",
  PENDING: "Đang chờ kênh gửi xác nhận; chưa xác nhận gửi thành công",
  SIMULATED: "Mô phỏng; chưa gửi thông báo thật",
  NOT_CONFIGURED: "Đề xuất đã lưu; chưa có kênh gửi",
  FAILED: "Gửi thất bại",
  SUPPRESSED_QUIET_HOURS: "Chưa gửi vì đang trong giờ nghỉ 22:00–07:00",
};
const REASONS: Record<string, string> = { PREREQUISITE_DEFERRED: "Cần học việc tiên quyết trước", NO_FITTING_SLOT_OR_BUDGET: "Chưa có khung giờ hoặc ngân sách đủ", METRICS_UNAVAILABLE: "Chưa có dữ liệu tiến độ để đề xuất hỗ trợ", NO_DUE_WORK_OR_INSUFFICIENT_DATA: "Chưa có việc đến hạn hoặc chưa đủ dữ liệu", QUIET_HOURS: "Đang trong giờ nghỉ 22:00–07:00", DAILY_LIMIT: "Hôm nay bạn đã có một đề xuất hỗ trợ", NO_TRIGGER: "Hiện chưa cần can thiệp", METRICS_INVALID_OR_STALE: "Dữ liệu tiến độ cần được cập nhật", PLAN_UNAVAILABLE: "Cần có kế hoạch trước" };
function errorText(error: unknown) { return error instanceof Error ? error.message : "Không kết nối được. Hãy thử lại."; }
function date(value: string | null, timezone: string) { return value ? formatDateTime(value,timezone) : "Để sau"; }

function Item({ item, timezone, resources, onSave, busy, errorMessage }: { item: PlanItem; timezone: string; resources: Record<string, string>; busy?: boolean; errorMessage?: string; onSave?: (id: string, start: string, minutes: number) => Promise<boolean> }) {
  const [editing, setEditing] = useState(false);
  const [start, setStart] = useState(toDateTimeInput(item.scheduled_start));
  const [minutes, setMinutes] = useState(item.est_minutes);
  const [error, setError] = useState("");
  async function save(e: FormEvent) {
    e.preventDefault(); setError("");
    try { if (await onSave?.(item.id, localInputToISO(start), minutes)) setEditing(false); }
    catch { setError("Chọn ngày và giờ hợp lệ."); }
  }
  return <article className={`${styles.item} ${item.status === "COMPLETED" ? styles.completed : ""}`}>
    <div className={styles.meta}><span>{STATUS[item.status]}</span><span>{item.est_minutes} phút</span></div>
    <h3>{item.action}</h3>
    {onSave && item.status !== "COMPLETED" && !editing && <button type="button" className="outline edit-schedule-button" disabled={busy} onClick={() => setEditing(true)}>✏️ Sửa lịch</button>}
    {editing && <form className="schedule-editor" onSubmit={save}><DateTimeField label="Ngày và giờ học" value={start} onChange={setStart}/><label>Thời lượng (phút)<input type="number" min={30} max={90} required value={minutes} onChange={e=>setMinutes(Number(e.target.value))}/></label><p>Bạn tự chọn thời gian phù hợp. Các việc cần học trước và lịch đã đặt vẫn được kiểm tra.</p>{(error || errorMessage) && <p className="form-error">{error || errorMessage}</p>}<div className="product-actions"><button className="primary" disabled={busy}>Lưu lịch mới</button><button type="button" className="secondary" disabled={busy} onClick={()=>setEditing(false)}>Hủy</button></div></form>}
    {item.scheduled_start && <p><time dateTime={item.scheduled_start}>{date(item.scheduled_start, timezone)}</time> → {date(item.scheduled_end, timezone)}</p>}
    <p>Đầu ra: {item.expected_output}</p>
    {item.if_then_text && <p className={styles.commitment}>{item.if_then_text}</p>}
    {item.defer_reason && <p>{REASONS[item.defer_reason] || item.defer_reason}</p>}
    {item.resource_ids.filter(id => resources[id]?.startsWith("https://")).map(id => <a key={id} href={resources[id]} target="_blank" rel="noreferrer">Nguồn học: {id}</a>)}
  </article>;
}

export default function StudyPlan({ token, userId, onConnections }: { token: string; userId: number; onConnections: () => void }) {
  const [connections, setConnections] = useState<ConnectedPeerSummary[]>([]);
  const [pair, setPair] = useState(0);
  const [setup, setSetup] = useState<PlanSetup | null>(null);
  const [view, setView] = useState<PlanView | null>(null);
  const [members, setMembers] = useState<PlanMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [commits, setCommits] = useState({mine: false, partner: false, both: false});
  const [coach, setCoach] = useState<CoachDecision | null>(null);
  const [retry, setRetry] = useState(0);
  const sequence = useRef(0);
  const lock = useRef(false);
  const idempotency = useRef<{ payload: string; key: string } | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true); setError("");
    void api.listConnections(token).then(result => {
      if (!active) return;
      const eligible = result.connected.filter(p => p.requester_id === userId || p.recipient_id === userId);
      setConnections(eligible);
      setPair(current => eligible.some(p => p.peer_match_id === current) ? current : eligible[0]?.peer_match_id ?? 0);
    }).catch(e => { if (active) setError(errorText(e)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [token, userId, retry]);

  const refresh = useCallback(async () => {
    const seq = ++sequence.current;
    if (!pair) return;
    setLoading(true); setError("");
    try {
      const [s, v] = await Promise.all([api.planSetup(token, pair), api.plan(token, pair)]);
      if (seq !== sequence.current) return;
      setSetup(s); setView(v);
      setCommits(await api.planCommitments(token, pair));
      setMembers(current => current.length && current.every(m => s.members.some(p => p.user_id === m.user_id)) ? current : s.members.map(m => ({
        user_id: m.user_id, goal: m.goals.join("; "), concept_ids: m.suggested_concept_ids?.length ? m.suggested_concept_ids : [s.concepts.filter(c => c.track === (/anh|english|ielts/i.test(m.goals.join(" ")) ? "english" : /python/i.test(m.goals.join(" ")) ? "python" : "sql")).slice(-1)[0]?.id || s.concepts[0].id], known_concept_ids: [], can_help_concept_ids: [],
        committed_minutes_per_week: 240, availability: m.availability.map(w => ({ id: String(w.id), day_of_week: w.day_of_week, start_time: w.start_time.slice(0,5), end_time: w.end_time.slice(0,5) })),
        timezone: m.availability[0]?.timezone || "Asia/Ho_Chi_Minh", location: "Góc học tập của tôi", deadline: null,
      })));
    } catch (e) { if (seq === sequence.current) setError(errorText(e)); }
    finally { if (seq === sequence.current) setLoading(false); }
  }, [pair, token]);

  useEffect(() => { setView(null); setSetup(null); setMembers([]); setCoach(null); setNotice(""); idempotency.current = null; void refresh(); return () => { sequence.current++; }; }, [refresh]);

  function changeMember(uid: number, patch: Partial<PlanMember>) { setMembers(current => current.map(m => m.user_id === uid ? { ...m, ...patch } : m)); }

  async function run(operation: () => Promise<unknown>, message: string) {
    if (lock.current) return false;
    lock.current = true; setBusy(true); setError(""); setNotice("");
    try { await operation(); setNotice(message); await refresh(); return true; }
    catch (e) { setError(errorText(e)); return false; }
    finally { lock.current = false; setBusy(false); }
  }

  function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (members.some(m => !m.goal.trim() || !m.concept_ids.length)) { setError("Chọn mục tiêu và nội dung học cho cả hai người."); return; }
    const payload = { pair_id: pair, members, horizon_days: 7 };
    const encoded = JSON.stringify(payload);
    if (!idempotency.current || idempotency.current.payload !== encoded) idempotency.current = { payload: encoded, key: crypto.randomUUID() };
    void run(() => api.generatePlan(token, payload, idempotency.current!.key), "Đã lưu kế hoạch. Xem cảnh báo và các việc để sau nếu có.");
  }

  const timezone = view?.timezone || "Asia/Ho_Chi_Minh";
  const resources = view?.resources || {};
  const proposal = view?.proposal;

  return <section className={styles.workspace}>
    <div className="page-title"><div><span className="eyebrow">Chung nhịp · Mục tiêu riêng</span><h1>Kế hoạch tự học</h1><p>Xếp việc phù hợp thời gian của mỗi người, cùng giữ cam kết.</p></div><button className="secondary" disabled={loading || busy} onClick={() => pair ? void refresh() : setRetry(r => r + 1)}>Làm mới</button></div>
    {error && <div className={styles.error} role="alert">{error} <button className="text-link" disabled={busy} onClick={() => pair ? void refresh() : setRetry(r => r + 1)}>Thử lại</button></div>}
    {notice && <p role="status">{notice}</p>}
    {loading && <p role="status">Đang tải kế hoạch…</p>}
    {!loading && !error && !connections.length && <div className="panel"><h2>Chưa có bạn đồng hành</h2><p>Kết nối một bạn học để lập hai kế hoạch riêng.</p><button className="primary" onClick={onConnections}>Xem kết nối</button></div>}
    {connections.length > 0 && <label className={styles.pair}>Bạn đồng hành<select disabled={busy} value={pair} onChange={e => setPair(Number(e.target.value))}>{connections.map(p => <option key={p.peer_match_id} value={p.peer_match_id}>{p.peer.display_name}</option>)}</select></label>}
    {setup && !view?.plan && <form className={`panel ${styles.form}`} onSubmit={generate}>
      <h2>Chốt cam kết cho tuần tới</h2><p>Chọn mục tiêu và giờ rảnh. BridgeBot chia thành việc nhỏ, chừa thời gian để bạn không quá tải.</p>
      <p className="provider-note">🤖 Gợi ý kế hoạch · {setup.provider_mode === "openai_compatible" ? "AI" : "Bản demo theo mẫu"} · Bạn có thể điều chỉnh trước khi cam kết.</p>
      <fieldset disabled={busy || loading}><div className={styles.columns}>
        {members.map(m => <section key={m.user_id} className={styles.member}>
          <h3>{setup.members.find(p => p.user_id === m.user_id)?.display_name}{m.user_id === userId ? " · Bạn" : ""}</h3>
          <label>Mục tiêu<input required value={m.goal} onChange={e => changeMember(m.user_id, { goal: e.target.value })} /></label>
          <label>Nội dung muốn làm được<select required value={m.concept_ids[0] || ""} onChange={e => changeMember(m.user_id, { concept_ids: [e.target.value] })}><option value="">Chọn concept</option>{setup.concepts.map(c => <option key={c.id} value={c.id}>{c.action}</option>)}</select></label>
          <label>Phút cam kết mỗi tuần<input type="number" min={0} max={10080} required value={m.committed_minutes_per_week} onChange={e => changeMember(m.user_id, { committed_minutes_per_week: Number(e.target.value) })} /></label>
          <label>Nơi học<input required value={m.location} onChange={e => changeMember(m.user_id, { location: e.target.value })} /></label>
          <details><summary>Tôi đã biết gì và có thể giúp gì?</summary>{(["known_concept_ids", "can_help_concept_ids"] as const).map(field => <label key={field}>{field === "known_concept_ids" ? "Đã biết" : "Có thể hỗ trợ"}<select multiple value={m[field]} onChange={e => changeMember(m.user_id, { [field]: Array.from(e.target.selectedOptions, o => o.value) })}>{setup.concepts.map(c => <option key={c.id} value={c.id}>{c.id}</option>)}</select></label>)}</details>
          <h4>Khung giờ rảnh</h4>
          {m.availability.length === 0 && <p>Chưa có khung giờ. Thêm khung phù hợp trước khi xếp lịch.</p>}
          {m.availability.map((w, index) => <div className={styles.window} key={w.id}>
            <label>Ngày<select value={w.day_of_week} disabled={!!setup.members.find(p => p.user_id === m.user_id)?.availability.length} onChange={e => changeMember(m.user_id, { availability: m.availability.map((x,i) => i === index ? { ...x, day_of_week: Number(e.target.value) } : x) })}>{DAYS.map((d,i) => <option value={i} key={d}>{d}</option>)}</select></label>
            {(["start_time", "end_time"] as const).map(field => <label key={field}>{field === "start_time" ? "Từ" : "Đến"}<input type="text" inputMode="numeric" placeholder="HH:mm" pattern="([01][0-9]|2[0-3]):[0-5][0-9]" required value={w[field]} disabled={!!setup.members.find(p => p.user_id === m.user_id)?.availability.length} onChange={e => changeMember(m.user_id, { availability: m.availability.map((x,i) => i === index ? { ...x, [field]: e.target.value } : x) })} /></label>)}
            {!setup.members.find(p => p.user_id === m.user_id)?.availability.length && <button type="button" aria-label={`Xóa khung ${index+1}`} onClick={() => changeMember(m.user_id, { availability: m.availability.filter((_,i) => i !== index) })}>×</button>}
          </div>)}
          {setup.members.find(p => p.user_id === m.user_id)?.availability.length ? <p>Khung giờ lấy từ hồ sơ đã lưu.</p> : <button type="button" className="secondary" onClick={() => changeMember(m.user_id, { availability: [...m.availability, { id: crypto.randomUUID(), day_of_week: Math.min(m.availability.length,6), start_time: "19:00", end_time: "20:30" }] })}>Thêm khung giờ</button>}
        </section>)}
      </div><p>Cùng xem lại cam kết của hai người trước khi tạo kế hoạch.</p><button className="primary" disabled={busy || loading} type="submit">{busy ? "Đang tạo…" : "✨ Gợi ý kế hoạch cho hai bạn"}</button></fieldset>
    </form>}
    {view?.plan && <>
      <section className="commit-banner"><div><h2>{commits.both ? "🤝 Hai bạn đã cùng cam kết" : "🤝 Chốt lời hứa học cùng nhau"}</h2><p>{commits.mine ? "Bạn đã cam kết ✓" : "Bạn xem lại lịch rồi bấm cam kết nhé."} · {commits.partner ? "Bạn đồng hành đã cam kết ✓" : "Đang chờ bạn đồng hành xác nhận"}</p></div><button className="primary" disabled={busy || commits.mine} onClick={() => void run(async () => { setCommits(await api.commitPlan(token, pair)); }, "Đã lưu cam kết của bạn.")}>{commits.mine ? "Đã cam kết ✓" : "Tôi cam kết giữ nhịp"}</button></section>
      <div className={styles.columns}><section className={`panel ${styles.mySchedule}`}><span className="eyebrow">🗓️ Lịch học của bạn</span><h2>{view.goal}</h2><p className="provider-note">🤖 {view.provider_mode === "openai_compatible" || view.provider_mode === "live" ? "AI gợi ý" : "Gợi ý theo mẫu demo"} · Cùng xem lại trước khi cam kết.</p>
        {view.plan.warnings.map(w => <p className={styles.warning} key={w.code}>{w.message}</p>)}
        {view.plan.items.length === 0 && <p>Chưa có việc được xếp lịch. Xem mục để sau và điều chỉnh thời gian.</p>}
        <div className={styles.list}>{view.plan.items.map(i => <Item key={`${i.id}:${view.plan!.plan_version}`} item={i} timezone={timezone} resources={resources} busy={busy} errorMessage={error} onSave={(id,start,minutes)=>run(()=>api.editPlanSchedule(token,pair,id,view.plan!.plan_version,start,minutes),"Đã lưu lịch mới. Xem lại và cam kết với phiên bản này.")} />)}</div>
        <h2>Để dành khi có thêm thời gian ({view.plan.deferred_items.length})</h2>{view.plan.deferred_items.length === 0 && <p>Các việc đều đã có chỗ trong lịch.</p>}<div className={styles.list}>{view.plan.deferred_items.map(i => <Item key={`${i.id}:${view.plan!.plan_version}`} item={i} timezone={timezone} resources={resources} busy={busy} errorMessage={error} onSave={(id,start,minutes)=>run(()=>api.editPlanSchedule(token,pair,id,view.plan!.plan_version,start,minutes),"Đã lưu lịch mới. Xem lại và cam kết với phiên bản này.")} />)}</div>
        <p>Check-in được cập nhật sau khi được xác nhận. Việc hoàn thành không đồng nghĩa đã thành thạo concept.</p>
        <button className="secondary" disabled={busy || loading} onClick={() => void run(() => api.replan(token, pair, view.plan!.plan_version), "Đã tạo phương án. Xem trước/sau rồi xác nhận.")}>Xem phương án giảm tải 20%</button>
      </section><aside className={`panel ${styles.companion}`}><h2>Bạn đồng hành</h2>{view.partner ? <><p>{view.partner.goal}</p><p>{view.partner.completed_count}/{view.partner.scheduled_count} việc đã hoàn thành; {view.partner.deferred_count} việc để sau.</p>{view.partner.partial && <p>Bạn mình còn vài việc để dành cho tuần sau.</p>}</> : <p>Chưa có plan của bạn đồng hành.</p>}<div className={styles.list}>{view.partner?.items?.map(i => <Item key={i.id} item={i} timezone={timezone} resources={resources}/>)}</div><PlanNotes token={token} pair={pair} partner={connections.find(p => p.peer_match_id === pair)?.peer.display_name || "bạn học"}/><h2>🤖 Lời khuyên cho hai bạn</h2><button className="secondary" disabled={busy || loading} onClick={() => void run(async () => { setCoach(await api.evaluateCoach(token, pair)); }, "Đã kiểm tra điều kiện hỗ trợ.")}>Gợi ý cách giữ nhịp</button>{coach && <div role="status"><small className="provider-note">{coach.message_source === "ai" && coach.selection?.provider_mode !== "fake" ? "🤖 AI gợi ý" : "🤖 Gợi ý theo mẫu"}</small><p>{coach.text || REASONS[coach.reason] || coach.reason}</p></div>}</aside></div>
      {proposal && <section className={`panel ${styles.proposal}`}><span className="eyebrow">Phương án chưa áp dụng</span><h2>Điều chỉnh v{proposal.before.plan_version} → v{proposal.after.plan_version}</h2><p>{proposal.reason}</p><p>Ngân sách giảm tải được tính từ {date(proposal.cutoff, timezone)}.</p>
        {proposal.budget?.map(b => <p key={b.week_start}>Tuần từ {formatDate(b.week_start)}: ngân sách {b.baseline_minutes} phút, đã hoàn thành {b.completed_minutes} phút; còn {b.remaining_minutes} phút → phương án tối đa {b.proposed_limit_minutes} phút.</p>)}
        <div className={styles.compare}><table><caption>Trước và sau theo từng việc</caption><thead><tr><th>Việc</th><th>Trước</th><th>Sau</th></tr></thead><tbody>{[...proposal.after.items, ...proposal.after.deferred_items].map(i => { const old = [...proposal.before.items, ...proposal.before.deferred_items].find(p => p.id === i.id); return <tr key={i.id}><th>{i.action}</th><td>{old ? `${STATUS[old.status]} · ${date(old.scheduled_start, timezone)}` : "Mới"}</td><td>{STATUS[i.status]} · {date(i.scheduled_start, timezone)}</td></tr>; })}</tbody></table></div>{proposal.after.partial && <p className={styles.warning}>Phương án chỉ đáp ứng một phần mục tiêu; các việc còn lại chuyển sang để sau.</p>}<div className={styles.actions}><button className="primary" disabled={busy || loading} onClick={() => void run(() => api.decideReplan(token, pair, proposal.id, proposal.expected_version, true), "Đã áp dụng phương án.")}>Chấp nhận phương án</button><button className="secondary" disabled={busy || loading} onClick={() => void run(() => api.decideReplan(token, pair, proposal.id, proposal.expected_version, false), "Giữ kế hoạch đang dùng.")}>Giữ kế hoạch hiện tại</button></div></section>}
    </>}
  </section>;
}
