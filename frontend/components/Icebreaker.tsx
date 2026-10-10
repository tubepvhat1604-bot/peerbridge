"use client";
import { useState } from "react";
export default function Icebreaker({ name, topic, onChoose }: { name: string; topic?: string; onChoose?: (text: string) => void }) {
  const [selected, setSelected] = useState("");
  const [variant, setVariant] = useState(false);
  const subject = topic || "mục tiêu tuần này";
  const questions = variant
    ? [{emoji:"🌱",text:"Bạn thích học yên lặng hay trao đổi sau mỗi việc nhỏ?"},{emoji:"⏰",text:"Mỗi tuần mình cùng học vào những ngày nào thì vừa sức?"},{emoji:"🤝",text:"Khi bạn mất động lực, mình có thể giúp thế nào?"}]
    : [{emoji:"👋",text:`Chào ${name}! Điều gì khiến bạn bắt đầu mục tiêu này?`},{emoji:"🎯",text:`Bạn muốn làm được điều gì sau buổi học đầu tiên?`},{emoji:"💬",text:`Phần nào trong ${subject} bạn muốn cùng mình luyện trước?`}];
  
  return <section className="icebreaker" style={{ background: "var(--surface-sunken)", padding: "16px", borderRadius: "16px", border: "1px dashed var(--accent)", marginBottom: "16px" }}>
    <div className="section-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
      <b style={{ color: "var(--accent-text)", display: "flex", alignItems: "center", gap: "8px" }}>🤖 BridgeBot Gợi Ý Phá Băng</b>
      <button className="text-link" type="button" onClick={() => setVariant(v => !v)} style={{ fontSize: "0.85rem", color: "var(--accent-text)" }}>Đổi gợi ý</button>
    </div>
    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
      {questions.map(q => (
        <button key={q.text} type="button" style={{ display: "flex", alignItems: "center", gap: "12px", background: "white", border: "1px solid var(--border)", padding: "10px 16px", borderRadius: "12px", textAlign: "left", fontSize: "0.95rem", color: "var(--text)", transition: "all 0.2s" }} onClick={() => { setSelected(q.text); onChoose?.(q.text); }}>
          <span style={{ fontSize: "1.2rem" }}>{q.emoji}</span> {q.text}
        </button>
      ))}
    </div>
    {selected && !onChoose && <div className="icebreaker-draft" style={{ marginTop: "12px", padding: "12px", background: "var(--surface)", borderRadius: "8px" }}><p>{selected}</p><button className="secondary" type="button" onClick={async () => { try { await navigator.clipboard.writeText(selected); setSelected("Đã sao chép lời chào. Bạn có thể gửi trong phiên học."); } catch { setSelected(selected); } }}>Sao chép lời chào</button></div>}
  </section>;
}
