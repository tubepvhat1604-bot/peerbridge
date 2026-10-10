"use client";
import {formatDateTime} from "@/lib/time";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import Avatar from "./Avatar";
type Note = {id: number; user_id: number; display_name: string; text: string; created_at: string};
export default function PlanNotes({ token, pair, partner }: {token:string;pair:number;partner:string}) {
  const [notes,setNotes]=useState<Note[]>([]), [text,setText]=useState("");
  const [error,setError]=useState(""),[busy,setBusy]=useState(false);
  const load=useCallback(async()=>{try{setNotes((await api.planNotes(token,pair)).items);setError("");}catch(e){setError(e instanceof Error?e.message:"Chưa tải được lời nhắn.");}},[token,pair]);
  useEffect(()=>{void load();const id=setInterval(()=>void load(),15000);return()=>clearInterval(id);},[load]);
  async function send(e:FormEvent){e.preventDefault();if(busy||!text.trim())return;setBusy(true);try{await api.addPlanNote(token,pair,text.trim());setText("");await load();}catch(e){setError(e instanceof Error?e.message:"Chưa gửi được lời nhắn.");}finally{setBusy(false);}}
  return <section className="plan-notes"><h3>💬 Nhắn gửi về kế hoạch</h3><p>Trao đổi việc đang vướng hoặc gửi một lời động viên cho {partner}.</p><button type="button" className="text-link" onClick={()=>setText("Mình thấy kế hoạch này vừa sức đó. Nếu có phần nào vướng, mình cùng thử một ví dụ nhỏ nhé!")}>🤖 Gợi ý lời động viên · Theo mẫu</button><form onSubmit={send}><textarea rows={3} maxLength={280} value={text} onChange={e=>setText(e.target.value)} placeholder="Bạn muốn nhắn gì cho người đồng hành?" aria-label="Lời nhắn về kế hoạch"/><div className="product-actions"><small>{text.length}/280</small><button className="primary" disabled={busy||!text.trim()}>{busy?"Đang gửi…":"Gửi lời nhắn"}</button></div></form>{error&&<p className="form-error">{error}</p>}{notes.map(n=><article className="plan-note" key={n.id}><Avatar seed={n.user_id} size={35}/><div><b>{n.display_name}</b><p>{n.text}</p><small>{formatDateTime(n.created_at)}</small></div></article>)}</section>;
}
