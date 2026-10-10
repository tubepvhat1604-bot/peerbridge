"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import StudyRoom from "@/components/StudyRoom";
import { api, ApiError, canJoinStudySession } from "@/lib/api";
import type { ConnectedPeerSummary, StudySession, StudySessionResponse } from "@/lib/types";
import { LoadingState } from "./peer-connections/shared";
import styles from "./StudySessions.module.css";

type StudySessionsProps = {
  token: string;
  userId: number;
  sessionId: number | null;
  onSessionChange: (id: number | null) => void;
  onConnections: () => void;
};

function describeError(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) return "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.";
  return error instanceof Error ? error.message : "Không thể kết nối tới máy chủ. Vui lòng thử lại.";
}

function formatDate(value: string | null): string {
  if (!value) return "Chưa đặt lịch";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("vi-VN");
}

export default function StudySessions({ token, userId, sessionId, onSessionChange, onConnections }: StudySessionsProps) {
  const [connections, setConnections] = useState<ConnectedPeerSummary[]>([]);
  const [sessions, setSessions] = useState<StudySession[]>([]);
  const [loading, setLoading] = useState(true);
  const [connectionError, setConnectionError] = useState("");
  const [listError, setListError] = useState("");
  const [selectedMatch, setSelectedMatch] = useState("");
  const [participantRole, setParticipantRole] = useState<"learner" | "helper">("learner");
  const [topic, setTopic] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const [notice, setNotice] = useState("");
  const [openedSession, setOpenedSession] = useState<StudySessionResponse | null>(null);
  const [opening, setOpening] = useState(false);
  const [roomError, setRoomError] = useState("");
  const [roomAttempt, setRoomAttempt] = useState(0);
  const mounted = useRef(false);
  const refreshVersion = useRef(0);
  const createInFlight = useRef(false);

  const refresh = useCallback(async () => {
    const version = ++refreshVersion.current;
    setLoading(true);
    setConnectionError("");
    setListError("");
    const [peers, list] = await Promise.allSettled([api.listConnections(token), api.listSessions(token)]);
    if (!mounted.current || version !== refreshVersion.current) return;
    if (peers.status === "fulfilled") {
      const eligible = peers.value.connected.filter((item) => item.requester_id === userId || item.recipient_id === userId);
      setConnections(eligible);
      setSelectedMatch((current) => eligible.some((item) => String(item.peer_match_id) === current) ? current : "");
    } else {
      setConnections([]);
      setConnectionError(describeError(peers.reason));
    }
    if (list.status === "fulfilled") {
      setSessions(list.value.items.filter((item) => canJoinStudySession(item, userId)));
    } else {
      setSessions([]);
      setListError(describeError(list.reason));
    }
    setLoading(false);
  }, [token, userId]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => { mounted.current = false; refreshVersion.current++; };
  }, [refresh]);

  useEffect(() => {
    let active = true;
    setOpenedSession(null);
    setRoomError("");
    setOpening(sessionId !== null);
    if (sessionId === null) return;
    void api.session(token, sessionId).then((session) => {
      if (!active) return;
      if (session.id !== sessionId || !canJoinStudySession(session, userId)) {
        setRoomError("Tài khoản này không phải người học hoặc người hỗ trợ của phiên.");
        return;
      }
      setOpenedSession(session);
    }).catch((error: unknown) => {
      if (active) setRoomError(describeError(error));
    }).finally(() => {
      if (active) setOpening(false);
    });
    return () => { active = false; };
  }, [token, userId, sessionId, roomAttempt]);

  async function createSession(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (createInFlight.current || loading || connectionError) return;
    setCreateError("");
    setNotice("");
    const peer = connections.find((item) => String(item.peer_match_id) === selectedMatch);
    if (!peer) { setCreateError("Hãy chọn một bạn học đã kết nối."); return; }
    if (!topic.trim()) { setCreateError("Hãy nhập chủ đề phiên học."); return; }
    const startDate = start ? new Date(start) : null;
    const endDate = end ? new Date(end) : null;
    if ((startDate && Number.isNaN(startDate.getTime())) || (endDate && Number.isNaN(endDate.getTime()))) {
      setCreateError("Thời gian học không hợp lệ."); return;
    }
    if (startDate && endDate && endDate <= startDate) {
      setCreateError("Thời gian kết thúc phải sau thời gian bắt đầu."); return;
    }
    createInFlight.current = true;
    setCreating(true);
    // Invalidate older list loads so they cannot overwrite the newly created session.
    refreshVersion.current++;
    try {
      const result = await api.createSessionFromConnection(token, peer, {
        learner_id: participantRole === "learner" ? userId : peer.peer.user_id,
        topic: topic.trim(),
        scheduled_start: startDate?.toISOString() ?? null,
        scheduled_end: endDate?.toISOString() ?? null,
      });
      if (!mounted.current) return;
      setNotice(`Đã tạo phiên học #${result.id}.`);
      setTopic("");
      if (canJoinStudySession(result, userId)) {
        setSessions((current) => [result, ...current.filter((item) => item.id !== result.id)]);
        onSessionChange(result.id);
      } else {
        setCreateError("Phiên đã được tạo nhưng chưa thể mở phòng. Hãy cập nhật danh sách phiên.");
      }
    } catch (error) {
      if (mounted.current) setCreateError(describeError(error));
    } finally {
      createInFlight.current = false;
      if (mounted.current) setCreating(false);
    }
  }

  const selectedPeer = connections.find((item) => String(item.peer_match_id) === selectedMatch);
  const peerName = (session: StudySession) => connections.find((item) => item.peer_match_id === session.peer_match_id)?.peer.display_name
    ?? `Người dùng #${session.learner_id === userId ? session.helper_id : session.learner_id}`;
  const room = openedSession?.id === sessionId ? openedSession : null;

  return <div className={`page animate-in peer-workspace ${styles.workspace}`}>
    <div className="page-title"><div><span className="eyebrow">Học cùng bạn đã kết nối</span><h1>Phiên học của bạn</h1><p>Chọn bạn học, tạo phiên và vào phòng để trao đổi trực tiếp.</p></div><div className="page-actions"><button className="outline" onClick={onConnections}>Xem kết nối</button><button className="primary" disabled={loading || creating} onClick={() => void refresh()}>{loading ? "Đang tải..." : "Cập nhật danh sách"}</button></div></div>
    {loading && <LoadingState message="Đang tải kết nối và phiên học..."/>}
    {notice && <p className="form-success" role="status">{notice}</p>}
    <div className={styles.grid}>
      <section className="panel" aria-labelledby="create-session-title">
        <h2 id="create-session-title">Tạo phiên học</h2>
        {connectionError && <p className="form-error" role="alert">Không tải được kết nối: {connectionError}</p>}
        {!loading && !connectionError && connections.length === 0 && <div className="peer-empty"><p>Bạn chưa có kết nối hợp lệ để tạo phiên.</p><button className="outline" onClick={onConnections}>Tìm và chấp nhận kết nối</button></div>}
        {createError && <p className="form-error" role="alert">{createError}</p>}
        <form className={styles.form} onSubmit={createSession}>
          <fieldset disabled={loading || creating || !!connectionError || connections.length === 0}>
            <label>Bạn học<select required value={selectedMatch} onChange={(event) => setSelectedMatch(event.target.value)}><option value="">Chọn bạn học đã kết nối</option>{connections.map((item) => <option key={item.peer_match_id} value={item.peer_match_id}>{item.peer.display_name} · #{item.peer.user_id}</option>)}</select></label>
            {selectedPeer && <p className={styles.meta}>{[selectedPeer.peer.school, selectedPeer.peer.major].filter(Boolean).join(" · ")}</p>}
            <label>Vai trò của bạn<select value={participantRole} onChange={(event) => setParticipantRole(event.target.value as "learner" | "helper")}><option value="learner">Người học — cần hỗ trợ</option><option value="helper">Người hỗ trợ</option></select></label>
            <label>Chủ đề<input value={topic} onChange={(event) => setTopic(event.target.value)} maxLength={120} required placeholder="Bạn muốn cùng học nội dung gì?"/></label>
            <div className={styles.dates}><label>Bắt đầu (tùy chọn)<input type="datetime-local" value={start} onChange={(event) => setStart(event.target.value)}/></label><label>Kết thúc (tùy chọn)<input type="datetime-local" value={end} min={start || undefined} onChange={(event) => setEnd(event.target.value)}/></label></div>
            <p className={styles.meta}>Thời gian được nhập theo múi giờ trên thiết bị của bạn.</p>
            <button className="primary" type="submit" disabled={!selectedPeer || !topic.trim()}>{creating ? "Đang tạo phiên..." : "Tạo phiên học"}</button>
          </fieldset>
        </form>
      </section>
      <section className="panel" aria-labelledby="sessions-title">
        <div className="section-title"><h2 id="sessions-title">Phiên bạn có thể tham gia</h2><span className="connection-count">{sessions.length}</span></div>
        {listError && <p className="form-error" role="alert">Không tải được phiên học: {listError}</p>}
        {!loading && !listError && sessions.length === 0 && <p className="peer-empty">Chưa có phiên học nào bạn được phép tham gia. Hãy tạo phiên với một bạn học đã kết nối.</p>}
        <div className={styles.list}>{sessions.map((session) => <article className={`connection-item ${session.id === sessionId ? styles.selected : ""}`} key={session.id}>
          <h3>{session.topic}</h3><p className={styles.meta}>Phiên #{session.id} · Học cùng {peerName(session)}</p>
          <p className={styles.meta}>Bạn là {session.learner_id === userId ? "người học" : "người hỗ trợ"}</p>
          <p className={styles.meta}>Bắt đầu: {formatDate(session.scheduled_start)}{session.scheduled_end && <> · Kết thúc: {formatDate(session.scheduled_end)}</>}</p>
          <button className="secondary" disabled={creating || (session.id === sessionId && (opening || !!room))} onClick={() => {
            if (session.id === sessionId) setRoomAttempt((current) => current + 1);
            else onSessionChange(session.id);
          }}>{session.id === sessionId && room ? "Đang ở phòng" : "Vào phòng học"}</button>
        </article>)}</div>
      </section>
    </div>
    {sessionId !== null && <section className={styles.room} aria-label="Phòng học đã chọn">
      <div className={styles.roomHeader}><div><h2>{room?.topic ?? `Phiên học #${sessionId}`}</h2><p className={styles.meta}>Phiên #{sessionId}{room && <> · Học cùng {peerName(room)}</>}</p></div><div className={styles.actions}><button className="outline" disabled={opening} onClick={() => setRoomAttempt((current) => current + 1)}>Kết nối lại</button><button className="outline" onClick={() => onSessionChange(null)}>Rời phòng</button></div></div>
      {opening && <LoadingState message="Đang kiểm tra quyền vào phòng..."/>}
      {roomError && <p className="form-error" role="alert">Không thể vào phòng: {roomError}</p>}
      {room && !opening && <StudyRoom key={`${sessionId}:${roomAttempt}`} token={token} sessionId={sessionId}/>}
    </section>}
  </div>;
}
