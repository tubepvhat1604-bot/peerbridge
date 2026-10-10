"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AdminOverview } from "@/lib/admin-types";
import { formatDateTime } from "@/lib/time";
import styles from "./Admin.module.css";

const ACTION_LABEL: Record<keyof AdminOverview["actions"], string> = {
  ALLOW: "Cho qua", GUIDE: "Gợi mở", WARN: "Cảnh báo", BLOCK: "Chặn", ESCALATE: "Chờ Admin",
};

function percent(value: number | null | undefined) {
  return value === null || value === undefined ? "—" : `${Math.round(value * 100)}%`;
}

export default function AdminDashboard({ token, onSessions, onModeration }: {
  token: string; onSessions: () => void; onModeration: () => void;
}) {
  const [data, setData] = useState<AdminOverview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true);
    try { setData(await api.adminOverview(token)); setError(""); }
    catch (e) { setError(e instanceof Error ? e.message : "Chưa tải được số liệu."); }
    finally { setLoading(false); }
  }, [token]);
  useEffect(() => { void load(); }, [load]);

  const totalActions = data ? Object.values(data.actions).reduce((a, b) => a + b, 0) : 0;
  const leakRate = data?.leak_free.rate ?? null;
  return <div className="page animate-in">
    <header className="page-title">
      <div><span className="eyebrow">Admin · Giám sát peer support</span><h1>Tổng quan phiên học</h1>
        <p>Theo dõi chất lượng trao đổi, liêm chính học thuật và chi phí AI của phòng học.</p></div>
      <button className="outline" disabled={loading} onClick={() => void load()}>{loading ? "Đang tải…" : "Cập nhật"}</button>
    </header>
    {error && <p className="form-error" role="alert">{error}</p>}
    {data && <>
      <section className={styles.kpis} aria-label="Chỉ số chính">
        <div className={`${styles.kpi} ${leakRate !== null && leakRate < 0.9 ? styles.bad : styles.good}`}>
          <span>Phiên không lộ đáp án</span><b>{percent(leakRate)}</b>
          <small>{data.leak_free.sessions - data.leak_free.leaked}/{data.leak_free.sessions} phiên có trao đổi · {data.leak_free.judged_by_ai} phiên đã chấm bằng AI</small>
        </div>
        <div className={styles.kpi}><span>Tuân thủ Socratic</span><b>{percent(data.socratic_avg)}</b>
          <small>Trung bình điểm dẫn dắt bằng câu hỏi của các phiên</small></div>
        <div className={`${styles.kpi} ${data.pending_reviews ? styles.bad : ""}`}><span>Chờ Admin xử lý</span><b>{data.pending_reviews}</b>
          <small><button className="text-link" onClick={onModeration}>Mở hàng đợi kiểm duyệt →</button></small></div>
        <div className={styles.kpi}><span>Mạng lưới</span><b>{data.pairs}</b>
          <small>cặp học · {data.students} sinh viên · {data.sessions_total} phiên ({data.sessions_7d} trong 7 ngày)</small></div>
      </section>

      <div className={styles.grid2}>
        <section className="panel">
          <h2>Kiểm duyệt realtime</h2>
          <p className={styles.note}>{data.messages_total} tin nhắn · {data.messages_held} tin bị giữ lại · AI gợi mở {data.guides_total} lần</p>
          <div className={styles.bars}>
            {(Object.keys(ACTION_LABEL) as Array<keyof AdminOverview["actions"]>).map(action => {
              const count = data.actions[action];
              return <div className={styles.barRow} key={action}><span>{ACTION_LABEL[action]}</span>
                <div className={styles.barTrack}><div className={styles.barFill} style={{ width: `${totalActions ? (count / totalActions) * 100 : 0}%` }} /></div>
                <b>{count}</b></div>;
            })}
          </div>
        </section>
        <section className="panel">
          <h2>Chi phí AI phòng học</h2>
          <div className={styles.summary} style={{ marginTop: 12 }}>
            <p>Tin chat thường đi thẳng không gọi AI: <b>{data.ai.messages_prefiltered}</b> tin ({percent(data.ai.saved_rate)} số tin).</p>
            <p>Tin cần AI phân loại: <b>{data.ai.messages_ai_classified}</b>.</p>
            <p>Hôm nay: kiểm duyệt <b>{data.ai.moderation_cost_today_usd.toFixed(4)} USD</b>, tóm tắt/chấm phiên <b>{data.ai.review_cost_today_usd.toFixed(4)} USD</b>.</p>
            <p className={styles.note}>Còn lại trong trần AI chung của ngày: {data.ai.budget_left_usd === null ? "—" : `${data.ai.budget_left_usd.toFixed(2)} USD`}. Hết trần thì phòng học chỉ dùng bộ luật.</p>
          </div>
        </section>
      </div>

      <section className="panel">
        <div className={styles.actions} style={{ justifyContent: "space-between" }}>
          <h2>Mạng lưới các cặp học</h2>
          <button className="secondary" onClick={onSessions}>Xem từng phiên →</button>
        </div>
        {data.network.length === 0 ? <p className={styles.note} style={{ marginTop: 12 }}>Chưa có phiên học nào.</p> :
          <div className={styles.tableWrap}><table className={styles.table}>
            <thead><tr><th>Cặp</th><th>Phiên</th><th>Tin nhắn</th><th>Bị giữ</th><th>Socratic</th><th>Lộ đáp án</th><th>Hoạt động gần nhất</th></tr></thead>
            <tbody>{data.network.map(pair => <tr key={pair.peer_match_id}>
              <td>{pair.members.map(m => m.name || `#${m.id}`).join(" · ")}</td>
              <td>{pair.sessions}</td><td>{pair.messages}</td><td>{pair.held}</td>
              <td>{percent(pair.socratic_avg)}</td>
              <td>{pair.leaked_sessions ? <span className={`${styles.badge} ${styles.badgeBad}`}>{pair.leaked_sessions} phiên</span> : <span className={styles.badge}>Không</span>}</td>
              <td>{pair.last_activity ? formatDateTime(pair.last_activity) : "—"}</td>
            </tr>)}</tbody>
          </table></div>}
      </section>
    </>}
  </div>;
}
