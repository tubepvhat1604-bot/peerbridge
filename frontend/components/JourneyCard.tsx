"use client";
import { useState } from "react";
import Avatar from "./Avatar";
export default function JourneyCard({ me, partner, meId, partnerId, streak, minutes, tasks }: { me: string; partner: string; meId?: number; partnerId?: number; streak: number; minutes: number; tasks: number }) {
  const [shared, setShared] = useState(false);
  const target = streak < 3 ? 3 : streak < 7 ? 7 : streak < 14 ? 14 : (Math.floor(streak / 7) + 1) * 7;
  const title = streak >= 14 ? "Song kiếm hợp bích" : streak >= 7 ? "Đôi bạn giữ lửa" : streak >= 3 ? "Cùng nhau vào nhịp" : "Bắt đầu một tình bạn học tập";
  async function share() { const text = `${me} & ${partner} · ${streak} ngày cùng học · ${tasks} việc đã hoàn thành trên PeerBridge`; try { if (navigator.share) await navigator.share({ title: "Hành trình học cùng nhau", text }); else await navigator.clipboard.writeText(text); setShared(true); } catch { setShared(false); } }
  return <section className="journey-card"><div><span>PEERBRIDGE · HÀNH TRÌNH ĐỒNG HÀNH</span><h2>{title} 🏅</h2><div className="journey-buddies"><Avatar seed={meId ?? me} size={60}/><span>🤝</span><Avatar seed={partnerId ?? partner} size={60}/></div><p>{me} × {partner}</p></div><div><div className="journey-stats"><div><b>{streak}</b><small>Ngày cùng giữ nhịp</small></div><div><b>{Math.round(minutes / 60 * 10) / 10}h</b><small>Bạn học tuần này</small></div><div><b>{tasks}</b><small>Việc bạn đã xong</small></div></div><p>🌟 Cột mốc tiếp theo: {target} ngày cả hai cùng check-in</p><div className="product-progress"><i style={{width: `${Math.min(100, streak / target * 100)}%`}}/></div><button className="secondary" onClick={() => void share()}>{shared ? "Đã chia sẻ / sao chép ✓" : "✨ Chia sẻ hành trình"}</button></div></section>;
}
