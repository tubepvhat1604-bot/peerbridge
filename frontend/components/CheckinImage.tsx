"use client";
import {useEffect,useState} from "react";
export default function CheckinImage({src,token,alt,thumbnail=false}:{src:string;token:string;alt:string;thumbnail?:boolean}) {
 const [url,setUrl]=useState("");const [error,setError]=useState(false);const [retry,setRetry]=useState(0);
 useEffect(()=>{
  const controller=new AbortController();let objectUrl="";setUrl("");setError(false);
  const source=new URL(src);source.search="";
  void fetch(source.toString(),{headers:{Authorization:`Bearer ${token}`},signal:controller.signal}).then(async r=>{if(!r.ok)throw Error("image");return r.blob();}).then(blob=>{if(controller.signal.aborted)return;objectUrl=URL.createObjectURL(blob);setUrl(objectUrl);}).catch(()=>{if(!controller.signal.aborted)setError(true);});
  return ()=>{controller.abort();if(objectUrl)URL.revokeObjectURL(objectUrl);};
 },[src,token,retry]);
 if(error)return <div className="checkin-image-state">Chưa tải được ảnh.<button type="button" className="text-link" onClick={()=>setRetry(r=>r+1)}>Tải lại ảnh</button></div>;
 return url ? <img src={url} alt={alt} className="uploaded-checkin-image" style={{width:"100%",height:thumbnail?120:"auto",maxHeight:thumbnail?120:480,objectFit:thumbnail?"cover":"contain",display:"block"}}/> : <div className="checkin-image-state" role="status">Đang tải ảnh…</div>;
}
