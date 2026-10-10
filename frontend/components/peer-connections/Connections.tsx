"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { ConnectionRequestSummary } from "@/lib/types";
import { connectionStatusLabels, errorMessage, formatTime, LoadingState, Participants, PeerIdentity, StatusBadge } from "./shared";
import { useConnections } from "./useConnections";

export function Connections({ token, userId, notify, onMatching, onPlan, onSessions }: {
  token: string;
  userId: number;
  notify: (message: string) => void;
  onMatching: () => void;
  onPlan: () => void;
  onSessions: () => void;
}) {
  const { data, loading, error, refresh, updateRequest } = useConnections(token);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<{ id: number; message: string } | null>(null);
  const [notice, setNotice] = useState("");
  const actionInFlight = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  async function respond(item: ConnectionRequestSummary, action: "accept" | "reject") {
    if (actionInFlight.current || loading || error || item.recipient_id !== userId || item.status !== "PENDING") return;
    actionInFlight.current = true;
    setBusyId(item.id);
    setActionError(null);
    setNotice("");
    try {
      const response = await (action === "accept" ? api.acceptConnection(token, item.id) : api.rejectConnection(token, item.id));
      if (!mounted.current) return;
      updateRequest(response);
      const message = `${connectionStatusLabels[response.status]}: ${item.peer.display_name}.`;
      setNotice(message);
      notify(message);
      await refresh();
    } catch (failure) {
      if (!mounted.current) return;
      setActionError({ id: item.id, message: errorMessage(failure) });
      if (failure instanceof ApiError && failure.status === 409) await refresh();
    } finally {
      actionInFlight.current = false;
      if (mounted.current) setBusyId(null);
    }
  }

  function invitation(item: ConnectionRequestSummary) {
    const canRespond = item.recipient_id === userId && item.status === "PENDING";
    return <article className="connection-item" key={item.id}>
      <div className="connection-peer"><PeerIdentity peer={item.peer}/><StatusBadge status={item.status}/></div>
      <Participants requesterId={item.requester_id} recipientId={item.recipient_id} userId={userId} peer={item.peer}/>
      <p className="connection-time">Gửi lúc <time dateTime={item.created_at}>{formatTime(item.created_at)}</time></p>
      {item.responded_at && <p className="connection-time">Phản hồi lúc <time dateTime={item.responded_at}>{formatTime(item.responded_at)}</time></p>}
      {canRespond && <div className="request-actions"><button className="ghost" disabled={busyId !== null || loading || !!error} onClick={() => void respond(item, "reject")}>Từ chối</button><button className="primary" disabled={busyId !== null || loading || !!error} onClick={() => void respond(item, "accept")}>{busyId === item.id ? "Đang xử lý..." : "Chấp nhận"}</button></div>}
    </article>;
  }

  return <div className="page animate-in peer-workspace">
    <div className="page-title"><div><span className="eyebrow">Kết nối khi cả hai đồng ý</span><h1>Kết nối của bạn</h1><p>Theo dõi lời mời và những người học đã đồng ý kết nối với bạn.</p></div><div className="page-actions"><button className="outline" onClick={onMatching}>Tìm bạn học</button><button className="primary" disabled={loading || busyId !== null} onClick={() => void refresh()}>{loading ? "Đang tải kết nối..." : "Cập nhật kết nối"}</button></div></div>
    {loading && <LoadingState message="Đang tải kết nối..."/>}
    {error && <div className="peer-error" role="alert"><p>{error}</p><button className="outline" disabled={loading || busyId !== null} onClick={() => void refresh()}>Thử lại</button></div>}
    {actionError && <p className="form-error" role="alert">Lời mời #{actionError.id}: {actionError.message}</p>}
    {notice && <p className="form-success" role="status">{notice}</p>}
    {data && <div className="connections-sections">
      <section className="panel"><div className="section-title"><h2>Lời mời đến <span className="connection-count">{data.incoming.length}</span></h2></div><div className="connection-list">{data.incoming.length ? data.incoming.map(invitation) : <p className="peer-empty">Bạn chưa có lời mời đến.</p>}</div></section>
      <section className="panel"><div className="section-title"><h2>Lời mời đã gửi <span className="connection-count">{data.sent.length}</span></h2></div><div className="connection-list">{data.sent.length ? data.sent.map(invitation) : <p className="peer-empty">Bạn chưa có lời mời đã gửi.</p>}</div></section>
      <section className="panel"><div className="section-title"><h2>Đã kết nối <span className="connection-count">{data.connected.length}</span></h2></div><div className="connection-list">{data.connected.length ? data.connected.map((item) => <article className="connection-item" key={item.peer_match_id}>
        <div className="connection-peer"><PeerIdentity peer={item.peer}/><StatusBadge status="MATCHED"/></div>
        <Participants requesterId={item.requester_id} recipientId={item.recipient_id} userId={userId} peer={item.peer}/>
        <p className="connection-time">Đã có một người cùng bạn giữ nhịp 🌱</p><div className="product-actions"><button className="primary" onClick={onPlan}>Lập kế hoạch cùng nhau →</button><button className="secondary" onClick={onSessions}>Hẹn phiên học</button></div>
      </article>) : <p className="peer-empty">Bạn chưa có kết nối. Hãy tìm bạn học và gửi lời mời.</p>}</div></section>
    </div>}
  </div>;
}
