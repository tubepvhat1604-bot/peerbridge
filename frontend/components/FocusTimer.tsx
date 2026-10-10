"use client";
import { useEffect, useState } from "react";
export default function FocusTimer({ minutes, goal, onFinish }: { minutes: number; goal: string; onFinish: () => void }) {
  const [remaining, setRemaining] = useState(minutes*60);
  const [running, setRunning] = useState(false);
  useEffect(() => { if (!running) return; const interval = setInterval(() => setRemaining(t => Math.max(0,t-1)),1000); return () => clearInterval(interval); },[running]);
  useEffect(() => { if (remaining === 0) setRunning(false); },[remaining]);
  return <div className="focus-timer"><div><span className="soft-label">🎯 MỤC TIÊU PHIÊN</span><h3>{goal}</h3><p>Cuối buổi, ghi lại một điều bạn làm được hoặc một điều còn vướng.</p></div><div><strong>{String(Math.floor(remaining/60)).padStart(2,"0")}:{String(remaining%60).padStart(2,"0")}</strong><div className="product-actions"><button className="primary" onClick={() => setRunning(r=>!r)} disabled={remaining === 0}>{running ? "Tạm dừng" : "Bắt đầu tập trung"}</button><button className="outline" onClick={onFinish}>Kết thúc & check-in</button></div></div></div>;
}
