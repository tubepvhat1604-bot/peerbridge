"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { SessionReview } from "@/lib/admin-types";
import { formatDateTime } from "@/lib/time";
import styles from "./Admin.module.css";

export function SummaryBody({ review }: { review: SessionReview }) {
  return <div className={styles.summary}>
    <p>{review.summary}</p>
    {review.key_points.length > 0 && <><h3>Đã cùng thảo luận</h3><ul>{review.key_points.map(p => <li key={p}>{p}</li>)}</ul></>}
    {review.open_questions.length > 0 && <><h3>Còn vướng</h3><ul>{review.open_questions.map(p => <li key={p}>{p}</li>)}</ul></>}
    {review.next_steps.length > 0 && <><h3>Tự luyện tiếp</h3><ul>{review.next_steps.map(p => <li key={p}>{p}</li>)}</ul></>}
    <p className={styles.note}>{review.mode === "ai" ? "Tóm tắt bởi AI" : "Tóm tắt nhanh (không dùng AI)"} · {review.message_count} tin · cập nhật {formatDateTime(review.updated_at)}</p>
  </div>;
}

/** Nút "Kết thúc & tóm tắt" trong phòng học: một lần gọi AI cho cả phiên, không có tin mới thì trả bản cũ. */
export default function SessionSummary({ token, sessionId }: { token: string; sessionId: number }) {
  const [review, setReview] = useState<SessionReview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setReview(null);
    api.sessionReview(token, sessionId).then(data => { if (active) setReview(data.review); }).catch(() => { /* chưa có tóm tắt */ });
    return () => { active = false; };
  }, [token, sessionId]);
  async function summarize() {
    setBusy(true); setError("");
    try { setReview((await api.createSessionReview(token, sessionId)).review); }
    catch (e) { setError(e instanceof Error ? e.message : "Chưa tóm tắt được phiên."); }
    finally { setBusy(false); }
  }
  return <section className="panel" style={{ marginTop: 20 }} aria-label="Tóm tắt phiên">
    <div className={styles.actions} style={{ justifyContent: "space-between" }}>
      <h2>📝 Tóm tắt phiên học</h2>
      <button className="secondary" disabled={busy} onClick={() => void summarize()}>
        {busy ? "Đang tóm tắt…" : review ? "Cập nhật tóm tắt" : "Kết thúc & tóm tắt"}</button>
    </div>
    {error && <p className="form-error" role="alert">{error}</p>}
    <div style={{ marginTop: 12 }}>
      {review ? <SummaryBody review={review} /> : <p className={styles.note}>Học xong, bấm để xem hai bạn đã trao đổi gì, còn vướng gì và nên tự luyện gì tiếp. Tóm tắt không chép đáp án.</p>}
    </div>
  </section>;
}
