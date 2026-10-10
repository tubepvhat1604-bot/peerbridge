"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AppPage, HomeOverview } from "@/lib/home-types";
import Avatar from "./Avatar";
import JourneyCard from "./JourneyCard";
import { LoopCards } from "./Overview";

function partOfDay() {
  const h = new Date().getHours();
  return h < 11 ? "Chào buổi sáng" : h < 14 ? "Chào buổi trưa" : h < 18 ? "Chào buổi chiều" : "Chào buổi tối";
}

export default function ProductOverview({ token, go }: { token: string; go: (p: AppPage) => void }) {
  const [data, setData] = useState<HomeOverview | null>(null);
  const [myId, setMyId] = useState(0);
  const [goal, setGoal] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try { const [home, profile] = await Promise.all([api.home(token), api.profile(token)]); setData(home); setGoal(profile.profile.learning_goals[0] || ""); setMyId(profile.profile.user_id); setError(""); }
    catch (e) { setError(e instanceof Error ? e.message : "Chưa tải được tiến độ."); }
  }, [token]);
  useEffect(() => { void load(); const timer = setInterval(() => void load(), 30000); return () => clearInterval(timer); }, [load]);
  if (!data) return <div className="page"><section className="panel"><p>{error || "Đang mở góc học tập của bạn…"}</p>{error && <button className="primary" onClick={() => void load()}>Thử lại</button>}</section></div>;
  const name = data.display_name.includes("@") ? data.display_name.split("@")[0] : data.display_name.split(" ").slice(-2).join(" ");
  const next = data.steps.find(s => !s.done);
  const weekPercent = data.plan.week_total ? Math.round(data.plan.week_done / data.plan.week_total * 100) : 0;
  const todayTotal = data.plan.today_total ?? 0, todayDone = data.plan.today_done ?? 0;
  return <div className="page animate-in product-overview">
    <header className="product-heading"><div><span className="eyebrow">{partOfDay()}</span><h1>Mỗi bước nhỏ đều đáng ghi nhận, {name} ✨</h1><p>{data.pair ? `Có ${data.pair.partner_name} đồng hành, bạn không phải cố gắng một mình.` : "Một mục tiêu của bạn. Một người cùng giữ lời hứa."}</p></div><button className="primary" onClick={() => go(data.pair && data.plan.has_plan ? "checkin" : next?.page || "matching")}>{data.pair && data.plan.has_plan ? "📸 Check-in hôm nay" : next?.title || "Tìm bạn đồng hành"}</button></header>
    {error && <p className="form-error">{error}</p>}
    <div className="daily-grid">
      <section className="panel daily-card" style={{ background: "var(--surface-sunken)", border: "none" }}><div className="section-title"><h2>Tiến độ của {name}</h2><span className="soft-label">Hôm nay</span></div><div className="daily-score"><b>{todayDone}<small>/{todayTotal} việc</small></b><span>{data.checkin.checked_in_today ? "Đã lưu dấu một buổi học ✓" : todayTotal ? "Một việc nhỏ cũng là tiến bộ" : "Hôm nay chưa có việc được xếp"}</span></div><div className="product-progress"><i style={{ width: `${todayTotal ? todayDone / todayTotal * 100 : 0}%`, background: "var(--accent)" }}/></div><p>Tuần này: {data.plan.week_done}/{data.plan.week_total} việc · {data.plan.minutes_done} phút đã học</p><button className="secondary" onClick={() => go(data.plan.has_plan ? "plan" : data.pair ? "plan" : "matching")} style={{ marginTop: "16px" }}>{data.plan.has_plan ? "Xem lịch học của tôi" : "Tạo kế hoạch vừa sức"}</button></section>
      <section className="panel partner-card" style={{ background: "var(--surface-sunken)", border: "none" }}><div className="section-title"><h2>Bạn đồng hành</h2>{data.pending_invites > 0 && <button className="text-link" onClick={() => go("connections")}>{data.pending_invites} lời mời</button>}</div>{data.pair ? <><div className="partner-identity"><Avatar seed={data.pair.partner_id} size={64}/><div><h3>{data.pair.partner_name}</h3><span>{data.checkin.partner_checked_in_today ? "🌟 Đã học và check-in hôm nay" : "🌱 Đang trên hành trình của riêng mình"}</span></div></div><p style={{ marginTop: "12px", background: "var(--surface)", padding: "12px", borderRadius: "8px" }}>{data.checkin.partner_latest?.headline || "Hãy gửi một lời động viên hoặc hẹn một buổi học ngắn cùng nhau."}</p>{data.checkin.partner_latest && <small style={{ display: "block", marginTop: "8px", color: "var(--text-soft)" }}>{data.checkin.partner_latest.relative}</small>}<div className="product-actions" style={{ marginTop: "16px" }}><button className="secondary" onClick={() => go("checkin")}>Góc học tập</button><button className="outline" onClick={() => go("sessions")}>Nhắn tin</button></div></> : <><p>Mục tiêu sẽ dễ giữ hơn khi có một người biết bạn đang cố gắng.</p><button className="primary" onClick={() => go("matching")} style={{ marginTop: "16px" }}>Tìm người cùng nhịp →</button></>}</section>
    </div>
    <div style={{ marginTop: "24px" }}><LoopCards data={data} go={go} /></div>
    {data.pair && <><JourneyCard me={data.display_name} partner={data.pair.partner_name} meId={myId} partnerId={data.pair.partner_id} streak={data.checkin.streak} minutes={data.plan.minutes_done} tasks={data.plan.week_done}/></>}
    {next && <section className="next-step" style={{ marginTop: "24px" }}><span>🌉 BƯỚC TIẾP THEO</span><div><h3>{next.title}</h3><p>{next.hint}</p></div><button className="primary" onClick={() => go(next.page)}>Tiếp tục →</button></section>}
  </div>;
}
