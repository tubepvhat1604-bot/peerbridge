"use client";
import {useEffect,useState} from "react";
export default function DateTimeField({value,onChange,label}:{value:string;onChange:(value:string)=>void;label:string}) {
 const split=(v:string)=>{const [d,t]=v.split("T");return [d ? d.split("-").reverse().join("/") : "",t?.slice(0,5)||""];};
 const [day,setDay]=useState(()=>split(value)[0]);const [time,setTime]=useState(()=>split(value)[1]);
 useEffect(()=>{const [d,t]=split(value);setDay(d);setTime(t);},[value]);
 function validDay(d:string) { const [dd,mm,yyyy]=d.split("/");const iso=`${yyyy}-${mm}-${dd}`;const parsed=new Date(iso+"T00:00:00Z");return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0,10)===iso; }
 function update(d:string,t:string){
  if(!/^\d{2}\/\d{2}\/\d{4}$/.test(d)||!/^([01]\d|2[0-3]):[0-5]\d$/.test(t))return;
  const [dd,mm,yyyy]=d.split("/");const iso=`${yyyy}-${mm}-${dd}`;const parsed=new Date(iso+"T00:00:00Z");
  if(!Number.isNaN(parsed.getTime())&&parsed.toISOString().slice(0,10)===iso)onChange(`${iso}T${t}`);
 }
 return <fieldset className="date-time-field"><legend>{label} · giờ Việt Nam</legend><div className="form-row"><label>Ngày (dd/MM/yyyy)<input name="schedule_date" type="text" inputMode="numeric" required placeholder="dd/MM/yyyy" pattern="[0-9]{2}/[0-9]{2}/[0-9]{4}" value={day} onChange={e=>{e.currentTarget.setCustomValidity(/^\d{2}\/\d{2}\/\d{4}$/.test(e.target.value) && !validDay(e.target.value) ? "Ngày không tồn tại." : "");setDay(e.target.value);update(e.target.value,time);}}/></label><label>Giờ (HH:mm)<input name="schedule_time" type="text" inputMode="numeric" required placeholder="HH:mm" pattern="([01][0-9]|2[0-3]):[0-5][0-9]" value={time} onChange={e=>{setTime(e.target.value);update(day,e.target.value);}}/></label></div></fieldset>;
}
