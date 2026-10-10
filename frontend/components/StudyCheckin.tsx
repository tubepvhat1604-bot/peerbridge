"use client";
import CheckinImage from "./CheckinImage";
import {formatDateTime} from "@/lib/time";

import JourneyCard from "./JourneyCard";
import Avatar from "./Avatar";
import type { PlanItem } from "@/lib/plan-types";

import { ChangeEvent, ClipboardEvent, FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, API_URL } from "@/lib/api";
import { CHECKIN_EMOJIS, type Checkin, type CheckinFeed, type PersonProgress } from "@/lib/checkin-types";
import styles from "./StudyCheckin.module.css";

const SENT_NOTICE = "Đã lưu buổi học. Đang gợi ý việc đã hoàn thành…";
const UNSETTLED = new Set<Checkin["status"]>(["needs_confirm", "failed", "not_study"]);
const MAX_EDGE = 1280, QUALITY = 0.82, POLL_MS = 2000, POLL_MAX_MS = 30000;
const STATUS_LABEL: Record<Checkin["status"], string> = {
  processing: "Đang phân tích…",
  needs_confirm: "Cần bạn chọn mục",
  done: "Đã ghi nhận",
  not_study: "Chưa giống ảnh học",
  failed: "Chưa phân tích được",
};

function errorText(error: unknown) { return error instanceof Error ? error.message : "Không kết nối được. Hãy thử lại."; }
function imageSrc(url: string | null) { return url ? (url.startsWith("http") ? url : `${API_URL}${url}`) : null; }
function newId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, c => (Number(c) ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (Number(c) / 4)))).toString(16));
}

/** Thu ảnh về cạnh dài 1280px, JPEG: gửi nhanh hơn, rẻ hơn khi AI đọc. */
async function compress(file: Blob): Promise<Blob> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  const ctx = canvas.getContext("2d");
  if (!ctx) return file;
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  return await new Promise<Blob>(resolve => canvas.toBlob(b => resolve(b || file), "image/jpeg", QUALITY));
}

function Progress({ person, me }: { person: PersonProgress; me: boolean }) {
  const pct = person.total_items ? Math.round((person.done_items / person.total_items) * 100) : 0;
  return <div className={styles.progressRow}>
    <b>{person.display_name}{me ? " (bạn)" : ""}{person.checked_in_today && <span className={styles.dot} title="Đã check-in hôm nay" />}</b>
    <div className={styles.bar} role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${pct}%` }} /></div>
    <small>{person.done_items}/{person.total_items} việc tuần này{person.pacing !== null ? ` · tiến độ ${Math.round(person.pacing * 100)}%` : ""}</small>
  </div>;
}

function Card({ token, checkin, mine, busy, onConfirm, onReact }: {
  token: string; checkin: Checkin; mine: boolean; busy: boolean;
  onConfirm: (c: Checkin, planItemId: string | null) => void;
  onReact: (c: Checkin, body: { emoji?: string; comment?: string }) => void;
}) {
  const [comment, setComment] = useState("");
  const src = imageSrc(checkin.image_url);
  return <article className={`${styles.card} ${styles[checkin.status] || ""}`} style={{ background: "white", borderRadius: "24px", padding: "16px", boxShadow: "0 4px 12px rgba(0,0,0,0.05)", marginBottom: "24px", border: "1px solid var(--border-soft)" }}>
    <div className="locket-owner" style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "16px" }}>
      <Avatar seed={checkin.owner_id} size={48}/>
      <div style={{ flex: 1 }}>
        <b style={{ fontSize: "1.05rem", color: "var(--text-strong)", display: "block" }}>{mine ? "Góc học tập của tôi" : checkin.owner_name}</b>
        <small style={{ color: "var(--text-soft)", display: "flex", alignItems: "center", gap: "4px" }}>
          {checkin.kind === "photo" ? "📸" : "✓"} {formatDateTime(checkin.created_at)}
        </small>
      </div>
    </div>
    <div style={{ borderRadius: "16px", overflow: "hidden", marginBottom: "16px", background: "var(--surface)", display: "flex", justifyContent: "center", alignItems: "center", minHeight: "200px" }}>
      {src ? <CheckinImage src={src} token={token} alt={`Ảnh check-in của ${checkin.owner_name}`}/> : <div className={styles.textOnly} style={{ padding: "32px", textAlign: "center", fontSize: "1.1rem", color: "#fff" }}>{checkin.note || checkin.description || "Check-in bằng ghi chú"}</div>}
    </div>
    <div className={styles.cardBody}>
      <h3 style={{ fontSize: "1.1rem", marginBottom: "4px", color: "var(--text-strong)" }}>{checkin.headline}</h3>
      {checkin.description && checkin.description !== checkin.headline && <p style={{ color: "var(--text)", marginBottom: "12px" }}>{checkin.description}</p>}
      {checkin.concept_names.length > 0 && <div className={styles.tags} style={{ display: "flex", gap: "8px", flexWrap: "wrap", marginBottom: "12px" }}>{checkin.concept_names.map(n => <span key={n} style={{ background: "var(--surface-sunken)", padding: "4px 12px", borderRadius: "100px", fontSize: "0.85rem", color: "var(--text-strong)", border: "1px solid var(--border)" }}>{n}</span>)}</div>}
      
      {mine && checkin.status === "processing" && <p className={styles.muted} aria-live="polite">AI đang xem ảnh, chờ vài giây…</p>}
      {mine && UNSETTLED.has(checkin.status) && <div className={styles.options} role="group" aria-label="Chọn mục bạn vừa học" style={{ marginTop: "16px", display: "flex", flexDirection: "column", gap: "8px" }}>
        {checkin.options.length > 0 && <p className={styles.muted} style={{ fontSize: "0.9rem" }}>Chọn mục trong kế hoạch bạn vừa học:</p>}
        {checkin.options.map(o => <button key={o.plan_item_id} type="button" className="secondary" disabled={busy} onClick={() => onConfirm(checkin, o.plan_item_id)} style={{ textAlign: "left", justifyContent: "flex-start" }}>
          {o.label}{o.concept_name ? ` · ${o.concept_name}` : ""}
        </button>)}
        <button type="button" className={checkin.options.length ? "ghost" : "secondary"} disabled={busy} onClick={() => onConfirm(checkin, null)} style={{ textAlign: "left", justifyContent: "flex-start" }}>
          {checkin.options.length ? "Mình học thứ khác" : checkin.status === "not_study" ? "Ảnh này đúng là mình đang học" : "Ghi nhận buổi học này"}
        </button>
      </div>}
      
      {checkin.reactions.length > 0 && <ul className={styles.reactions} style={{ listStyle: "none", padding: 0, marginTop: "16px", display: "flex", flexDirection: "column", gap: "8px" }}>{checkin.reactions.map((r, i) => <li key={i} style={{ background: "var(--surface-sunken)", padding: "8px 12px", borderRadius: "12px", fontSize: "0.95rem" }}><b style={{ color: "var(--text-strong)" }}>{r.display_name}</b> {r.emoji} {r.comment}</li>)}</ul>}
      
      {!mine && checkin.status === "done" && <div className={styles.react} style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "16px", flexWrap: "wrap" }}>
        {CHECKIN_EMOJIS.map(e => <button key={e} type="button" aria-label={`Thả ${e}`} disabled={busy} onClick={() => onReact(checkin, { emoji: e })} style={{ background: "var(--surface-sunken)", border: "1px solid var(--border)", borderRadius: "100px", padding: "6px 12px", fontSize: "1.2rem", cursor: "pointer", transition: "all 0.2s" }}>{e}</button>)}
        <form style={{ flex: 1, minWidth: "200px", display: "flex", gap: "8px" }} onSubmit={(ev: FormEvent) => { ev.preventDefault(); if (comment.trim()) { onReact(checkin, { comment: comment.trim() }); setComment(""); } }}>
          <input value={comment} maxLength={200} onChange={e => setComment(e.target.value)} placeholder="Nhắn gì đó..." aria-label="Bình luận" style={{ flex: 1, padding: "8px 16px", borderRadius: "100px", border: "1px solid var(--border)", outline: "none" }} />
          <button type="submit" className="primary" disabled={busy || !comment.trim()} style={{ borderRadius: "100px", padding: "8px 16px" }}>Gửi</button>
        </form>
      </div>}
    </div>
  </article>;
}

export default function StudyCheckin({ token, onConnections, onPlan }: { token: string; onConnections: () => void; onPlan: () => void }) {
  const [minutes, setMinutes] = useState(0);
  const [items, setItems] = useState<PlanItem[]>([]);
  const [selectedItem, setSelectedItem] = useState("");
  const [feed, setFeed] = useState<CheckinFeed | null>(null);
  const [noPair, setNoPair] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [file, setFile] = useState<Blob | null>(null);
  const [preview, setPreview] = useState("");
  const [note, setNote] = useState("");
  const pending = useRef<string | null>(null);  // id giữ nguyên khi gửi lại, tránh tạo trùng
  const polling = useRef<Set<string>>(new Set());
  const alive = useRef(true);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.checkinFeed(token);
      if (!alive.current) return;
      setFeed(data); setNoPair(false); setError("");
      void api.plan(token, data.pair_id).then(view => {
        if (!alive.current) return;
        const pendingItems = view.plan?.items.filter(i => i.status !== "COMPLETED" && (!i.scheduled_start || new Date(i.scheduled_start).getTime() <= Date.now())) || [];
        setItems(pendingItems);
        setSelectedItem(old => pendingItems.some(i => i.id === old) ? old : pendingItems[0]?.id || "");
      }).catch(() => {});
      void api.home(token).then(home => { if (alive.current) setMinutes(home.plan.minutes_done); }).catch(() => {});
      for (const c of [data.my_latest, ...data.my_pending]) if (c?.status === "processing") void poll(c.id);
    } catch (e) {
      if (!alive.current) return;
      if (e instanceof ApiError && e.status === 403) setNoPair(true);
      else setError(errorText(e));
    } finally {
      if (alive.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const poll = useCallback(async (id: string) => {
    if (polling.current.has(id)) return;
    polling.current.add(id);
    const started = Date.now();
    try {
      while (alive.current && Date.now() - started < POLL_MAX_MS) {
        await new Promise(r => setTimeout(r, POLL_MS));
        const c = await api.checkin(token, id);
        if (c.status !== "processing") break;
      }
    } catch { /* lần tải feed sau sẽ hiện lỗi nếu có */ } finally {
      polling.current.delete(id);
      if (alive.current) { setNotice(n => (n === SENT_NOTICE ? "" : n)); await load(); }
    }
  }, [token, load]);

  useEffect(() => {
    alive.current = true;
    void load();
    return () => { alive.current = false; };
  }, [load]);

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  function pick(blob: Blob | null) {
    if (!blob || !blob.type.startsWith("image/")) { setError("Hãy chọn một file ảnh."); return; }
    setError(""); setFile(blob); pending.current = null;
    setPreview(old => { if (old) URL.revokeObjectURL(old); return URL.createObjectURL(blob); });
  }
  function onPaste(e: ClipboardEvent) {
    const item = [...e.clipboardData.items].find(i => i.type.startsWith("image/"));
    if (item) { e.preventDefault(); pick(item.getAsFile()); }
  }
  function clearForm() {
    setFile(null); setNote(""); pending.current = null;
    setPreview(old => { if (old) URL.revokeObjectURL(old); return ""; });
    if (fileInput.current) fileInput.current.value = "";
  }

  async function submit(textOnly: boolean) {
    if (busy) return;
    if (textOnly ? false : !file) {
      setError(textOnly ? "Ghi chú cần ít nhất 3 ký tự." : "Hãy chụp hoặc chọn một ảnh.");
      return;
    }
    setBusy(true); setError(""); setNotice("");
    pending.current = pending.current || newId();
    try {
      const c = textOnly
        ? await api.createTextCheckin(token, pending.current, (note.trim() || "Đã hoàn thành buổi học hôm nay"), selectedItem)
        : await api.createPhotoCheckin(token, pending.current, await compress(file as Blob), note);
      clearForm();
      setNotice(c.status === "done" ? "🎉 Đã ghi nhận việc hoàn thành! Bạn đồng hành đã thấy tiến độ mới." : SENT_NOTICE);
      await load();
      if (c.status === "processing") void poll(c.id);
    } catch (e) {
      setError(errorText(e));  // giữ pending.current để bấm gửi lại không tạo check-in trùng
    } finally {
      setBusy(false);
    }
  }

  async function act(fn: () => Promise<unknown>, ok?: string) {
    setBusy(true); setError(""); setNotice("");
    try { await fn(); if (ok) setNotice(ok); await load(); } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  const confirm = (c: Checkin, planItemId: string | null) => act(() => api.confirmCheckin(token, c.id, planItemId), "Đã ghi nhận check-in.");
  const react = (c: Checkin, body: { emoji?: string; comment?: string }) => act(() => api.reactCheckin(token, c.id, body));
  const nudge = () => feed && act(async () => setNotice((await api.nudgePartner(token, feed.pair_id)).message));

  if (loading) return <div className="page animate-in"><p className={styles.muted}>Đang tải check-in…</p></div>;

  return <div className="page animate-in" onPaste={onPaste}>
    <div className="page-title"><div>
      <span className="eyebrow">📸 Study Locket · Những dấu nhỏ của sự cố gắng</span>
      <h1>Lưu một buổi học, giữ một lời hứa</h1>
      <p>Một tấm ảnh, một việc nhỏ đã xong. Cho bạn đồng hành biết hôm nay bạn vẫn đang cố gắng.</p>
    </div></div>

    {noPair && <section className="panel">
      <h2>Bạn chưa có bạn học</h2>
      <p className={styles.muted}>Hãy kết nối với một bạn, rồi lập kế hoạch học. Sau đó quay lại đây để check-in.</p>
      <button type="button" className="primary" onClick={onConnections}>Đến trang Kết nối</button>
    </section>}

    {error && <p className={styles.error} role="alert">{error}</p>}
    {notice && <p className={styles.notice} role="status">{notice}</p>}

    {feed && <><JourneyCard me={feed.me.display_name} partner={feed.partner.display_name} meId={feed.me.user_id} partnerId={feed.partner.user_id} streak={feed.streak} minutes={minutes} tasks={feed.me.done_items}/><div className={styles.layout}>
      <div className={styles.main}>
        <section className="panel">
          <div className={styles.head}>
            <h2>{feed.me.display_name} &amp; {feed.partner.display_name}</h2>
            {feed.streak > 0 && <span className={styles.streak}>🔥 {feed.streak} ngày liên tiếp cùng học</span>}
          </div>
          <Progress person={feed.me} me />
          <Progress person={feed.partner} me={false} />
          {feed.me.total_items === 0 && <p className={styles.muted}>Bạn chưa có kế hoạch tuần này. <button type="button" className={styles.inlineLink} onClick={onPlan}>Lập kế hoạch</button> để AI biết bạn đang học gì.</p>}
          <div className={styles.actions}>
            <button type="button" className="outline" disabled={busy || !feed.can_nudge} title={feed.nudge_hint || ""} onClick={nudge}>Nhắc {feed.partner.display_name}</button>
            {!feed.can_nudge && feed.nudge_hint && <small className={styles.muted}>{feed.nudge_hint}</small>}
          </div>
        </section>

        <section className="panel">
          <h2>📸 Góc học tập của tôi</h2><p className="provider-note">{feed.provider_mode === "openai" ? "🤖 AI phân tích ảnh và gợi ý việc đã học." : "🤖 Đang dùng kết quả mô phỏng cho bản demo."} Bạn có thể chọn lại việc đã hoàn thành.</p>
          <form className={styles.form} onSubmit={(e: FormEvent) => { e.preventDefault(); void submit(false); }}>
            {items.length > 0 && <label className={styles.note}>Hôm nay mình làm xong việc nào?<select className="checkin-task-select" value={selectedItem} onChange={e => setSelectedItem(e.target.value)}>{items.map(i => <option key={i.id} value={i.id}>{i.action}</option>)}<option value="">Một việc học khác ngoài kế hoạch</option></select></label>}
            <label className={styles.drop}>
              {preview ? <img src={preview} alt="Ảnh sẽ gửi" /> : <span>Chụp hoặc chọn ảnh<br /><small>Trên máy tính: dán ảnh chụp màn hình (Ctrl+V)</small></span>}
              <input ref={fileInput} type="file" accept="image/*" capture="environment" onChange={(e: ChangeEvent<HTMLInputElement>) => pick(e.target.files?.[0] || null)} />
            </label>
            <label className={styles.note}>Ghi chú (không bắt buộc)
              <textarea rows={2} maxLength={300} value={note} onChange={e => setNote(e.target.value)} placeholder="Ví dụ: vướng chỗ chọn kích thước chunk" />
            </label>
            <div className={styles.actions}>
              <button type="submit" className="primary" disabled={busy || !file}>{busy ? "Đang gửi…" : "Gửi check-in"}</button>
              <button type="button" className="ghost" disabled={busy} onClick={() => void submit(true)}>✓ Tick đã học · Tự khai báo</button>
            </div>
          </form>
        </section>

        {(feed.my_latest || feed.my_pending.length > 0) && <section className={styles.list} aria-label="Check-in của bạn">
          <h2>Của bạn</h2>
          {[feed.my_latest, ...feed.my_pending].filter((c): c is Checkin => Boolean(c)).map(c =>
            <Card token={token} key={c.id} checkin={c} mine busy={busy} onConfirm={confirm} onReact={react} />)}
        </section>}
      </div>

      <aside className={styles.side}>
        <section className={styles.list} aria-label="Check-in mới nhất của bạn cặp">
          <div className="partner-identity"><Avatar seed={feed.partner.user_id}/><h2>{feed.partner.display_name} vừa học</h2></div>
          {feed.partner_latest
            ? <Card token={token} checkin={feed.partner_latest} mine={false} busy={busy} onConfirm={confirm} onReact={react} />
            : <p className={styles.muted}>{feed.partner.display_name} chưa có check-in nào.</p>}
        </section>
        {feed.history.length > 0 && <section className="panel">
          <h2>Nhật ký của hai bạn</h2>
          <ol className={styles.history}>{feed.history.map(c => {
            const src = imageSrc(c.image_url);
            return <li key={c.id} title={c.headline}>
              {src ? <CheckinImage src={src} token={token} alt={c.headline} thumbnail/> : <span>{c.note || c.description}</span>}
              <small>{c.owner_name} · {formatDateTime(c.created_at)}</small>
            </li>;
          })}</ol>
        </section>}
      </aside>
    </div></>}
  </div>;
}
