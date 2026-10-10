"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

type Event = {
  id: number; session_id: number; message_id: number; sender_id: number;
  agent_action: string; risk_score: number; reason: string; message_content: string | null;
  guidance: string | null; instructor_review: unknown;
  context: { retrieved_sources?: Array<{source: string; chunk_id: string; text?: string}> };
};

export default function InstructorModeration({token}: {token: string}) {
  const [items, setItems] = useState<Event[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const busy = useRef(false);
  const selected = items.find(item => item.id === selectedId);
  useEffect(() => {
    let active = true;
    setLoading(true);
    api.moderationQueue(token).then(data => {
      if (!active) return;
      const events = (data as {items: Event[]}).items;
      // Tin cần Admin xem (ESCALATE chưa xử lý) lên đầu, sau đó tới tin bị chặn/cảnh báo, cuối cùng là tin đã phát.
      const rank = (e: Event) => e.instructor_review ? 3 : e.agent_action === "ESCALATE" ? 0 : e.agent_action === "ALLOW" || e.agent_action === "GUIDE" ? 2 : 1;
      const sorted = [...events].sort((a, b) => rank(a) - rank(b) || b.id - a.id);
      setItems(sorted); setSelectedId(sorted[0]?.id ?? null);
    }).catch(err => {if (active) setError(String(err));})
      .finally(() => {if (active) setLoading(false);});
    return () => {active = false;};
  }, [token]);
  async function review(override?: "ALLOW" | "BLOCK") {
    if (!selected || busy.current) return;
    busy.current = true;
    setSaving(true); setError("");
    try {
      const updated = await api.reviewModeration(token, String(selected.id), {
        action: override ? "OVERRIDE" : "INTERVENE", override_action: override, notes,
      }) as Event;
      setItems(current => current.map(item => item.id === updated.id ? updated : item));
    } catch (err) {setError(String(err));}
    finally {busy.current = false; setSaving(false);}
  }
  return <div className="page animate-in">
    <header className="page-title"><div><span className="eyebrow">Admin · Kiểm duyệt</span><h1>Hàng đợi kiểm duyệt</h1>
    <p>Log kiểm duyệt của mọi phòng học. Tin chờ Admin được xếp lên đầu; quyết định của bạn được lưu lại để đối chiếu.</p></div></header>
    {loading && <p>Đang tải hàng đợi...</p>}
    {error && <p role="alert" className="form-error">{error}</p>}
    {!loading && !items.length && <p>Chưa có log kiểm duyệt nào.</p>}
    <div className="moderation-layout">
      <section className="panel queue-panel">{items.map(item => <button key={item.id}
        className={`queue-item ${selectedId === item.id ? "active" : ""}`}
        onClick={() => {setSelectedId(item.id); setNotes("");}}>
        <div><b>Phiên {item.session_id} · Tin {item.message_id}</b><p>{item.message_content}</p>
        <span>{item.instructor_review ? "ĐÃ XỬ LÝ" : item.agent_action}</span></div>
      </button>)}</section>
      {selected && <section className="panel review-panel">
        <h2>Tin {selected.message_id} · {selected.agent_action}</h2>
        <p>Rủi ro: {(selected.risk_score * 100).toFixed(0)}/100</p>
        <div className="context-message flagged"><b>Người gửi {selected.sender_id}</b><p>{selected.message_content}</p></div>
        <p>{selected.reason}</p>{selected.guidance && <p>{selected.guidance}</p>}
        {selected.context.retrieved_sources?.map(source => <details key={source.chunk_id}>
          <summary>{source.source} · {source.chunk_id}</summary><p>{source.text}</p>
        </details>)}
        <label className="review-note">Lý do quyết định (khi bấm "Nhắn vào phòng học", nội dung này hiện cho hai bạn)<textarea value={notes} onChange={e => setNotes(e.target.value)} maxLength={1000}/></label>
        <div className="decision-actions">
          <button disabled={saving || !!selected.instructor_review || !notes.trim()} onClick={() => review("ALLOW")}>Cho phép phát tin</button>
          <button disabled={saving || !!selected.instructor_review || !notes.trim()} onClick={() => review()}>Nhắn vào phòng học</button>
          <button disabled={saving || !!selected.instructor_review || !notes.trim()} onClick={() => review("BLOCK")}>Chặn nội dung</button>
        </div>
        {!!selected.instructor_review && <p className="resolved">Admin đã xử lý tin này.</p>}
      </section>}
    </div>
  </div>;
}
