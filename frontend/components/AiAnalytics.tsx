"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AiStats } from "@/lib/home-types";
import styles from "./AiAnalytics.module.css";

const STATUS_LABEL: Record<string, string> = {
  done: "Đã ghi nhận", needs_confirm: "Phải hỏi lại", not_study: "Không phải ảnh học", failed: "Lỗi, chọn tay", processing: "Đang xử lý",
};
const pct = (v: number | null) => (v === null ? "—" : `${v}%`);
const sec = (ms: number | null) => (ms === null ? "—" : `${(ms / 1000).toFixed(1)} giây`);

/** Số liệu thật của AI Vision: độ đúng, tỷ lệ phải hỏi lại, độ trễ, chi phí theo ngày. */
export default function AiAnalytics({ token }: { token: string }) {
  const [days, setDays] = useState(7);
  const [data, setData] = useState<AiStats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    setError("");
    api.aiStats(token, days).then(d => { if (alive) setData(d); }).catch(e => { if (alive) setError(e instanceof Error ? e.message : "Không tải được số liệu."); });
    return () => { alive = false; };
  }, [token, days]);

  const max = Math.max(1, ...(data?.per_day.map(d => d.checkins) ?? [1]));
  const budgetPct = data ? Math.min(100, Math.round((data.cost_today_usd / Math.max(data.daily_budget_usd, 0.0001)) * 100)) : 0;

  return <div className="page animate-in">
    <div className="page-title"><div><h1>Số liệu AI Vision</h1><p>Chất lượng, tốc độ và chi phí của AI chấm ảnh check-in, tính trên dữ liệu thật.</p></div>
      <div className="page-actions"><div className={styles.range} role="group" aria-label="Khoảng thời gian">
        {[7, 30].map(d => <button key={d} type="button" className={days === d ? styles.on : ""} onClick={() => setDays(d)}>{d} ngày</button>)}
      </div></div>
    </div>
    {error && <p className={styles.error} role="alert">{error}</p>}
    {!data && !error && <div className={styles.tiles}>{[0, 1, 2, 3].map(i => <div key={i} className={styles.skel} />)}</div>}
    {data && <>
      {data.total_checkins === 0 && <p className={styles.note}>Chưa có check-in nào trong {data.days} ngày qua. Số liệu sẽ hiện khi người dùng bắt đầu check-in.</p>}
      <div className={styles.tiles}>
        <div className={styles.tile}><small>AI gắn đúng mục, không phải sửa</small><b>{pct(data.ai_accept_rate)}</b><span>Mục tiêu ≥ 75%</span></div>
        <div className={styles.tile}><small>Phải hỏi lại người dùng</small><b>{pct(data.ask_again_rate)}</b><span>Mục tiêu ≤ 30%</span></div>
        <div className={styles.tile}><small>Thời gian AI xử lý (p90)</small><b>{sec(data.latency_p90_ms)}</b><span>Trung vị {sec(data.latency_p50_ms)} · mục tiêu &lt; 15 giây</span></div>
        <div className={styles.tile}><small>Chi phí hôm nay</small><b>${data.cost_today_usd.toFixed(3)}</b>
          <div className={styles.bar}><i style={{ width: `${budgetPct}%` }} /></div><span>Trần {data.daily_budget_usd.toFixed(2)} USD/ngày · model {data.model}</span></div>
      </div>
      <div className={styles.grid}>
        <section className="panel"><h2>Check-in mỗi ngày</h2>
          {data.per_day.length === 0 ? <p className={styles.note}>Chưa có dữ liệu.</p> :
            <div className={styles.chart}>{data.per_day.map(d => <div key={d.date} title={`${d.checkins} check-in · $${d.cost_usd.toFixed(3)}`}>
              <span style={{ height: `${Math.max(4, d.checkins * 100 / max)}%` }} /><b>{d.checkins}</b><small>{d.date.slice(8, 10)}/{d.date.slice(5, 7)}</small>
            </div>)}</div>}
        </section>
        <section className="panel"><h2>Kết quả AI</h2>
          <ul className={styles.statuses}>{Object.entries(data.by_status).filter(([k]) => k !== "processing").map(([k, v]) => <li key={k}>
            <span>{STATUS_LABEL[k] || k}</span><div><i style={{ width: `${data.total_checkins ? v * 100 / data.total_checkins : 0}%` }} /></div><b>{v}</b>
          </li>)}</ul>
          <p className={styles.note}>Tỷ lệ người dùng sửa lại lựa chọn của AI: {pct(data.user_correction_rate)} · Độ tự tin trung bình: {data.avg_confidence ?? "—"} · Tổng chi phí {data.days} ngày: ${data.cost_usd.toFixed(3)}</p>
        </section>
      </div>
    </>}
  </div>;
}
