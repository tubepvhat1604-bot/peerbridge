"use client";
const icons = ["🤖", "🐻", "🐱", "🦊", "🐼", "🐸", "🐧", "🦉"];
const colors = ["#e1edff", "#fff0c2", "#ffe1ed", "#e9e0ff", "#d9f4e6"];
export default function Avatar({ seed, size = 48 }: { seed: string | number; size?: number }) {
 const hash = Array.from(String(seed)).reduce((n,c) => (n * 31 + c.charCodeAt(0)) >>> 0, 0);
 return <span className="buddy-avatar" role="img" aria-label="Avatar mặc định" style={{ width:size, height:size, minWidth:size, display:"inline-flex", alignItems:"center", justifyContent:"center", borderRadius:"50%", background:colors[hash % colors.length], fontSize:size * .55, lineHeight:1 }}>{icons[hash % icons.length]}</span>;
}
