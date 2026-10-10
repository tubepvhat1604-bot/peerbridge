"use client";
import {formatClock} from "@/lib/time";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/icons";
import { api, studyRoomSocket } from "@/lib/api";
import Icebreaker from "./Icebreaker";
import type { ModerationAction } from "@/lib/types";
import styles from "./StudyRoom.module.css";

export type StudyRoomProps = {
  token: string;
  sessionId: string | number;
  peerName?: string;
  topic?: string;
};

type ConnectionState = "idle" | "connecting" | "connected" | "closed" | "auth-error" | "forbidden" | "error";

type ChatMessageRecord = {
  id: number;
  session_id: number;
  sender_id: number;
  content: string;
  created_at: string | null;
};

type SessionStatusEvent = {
  type: "SESSION_STATUS";
  session_id: number;
  user_id: number;
  status: string;
  tutor?: TutorStatus;
};

type TutorStatus = { active: boolean; topic: string; turn_count: number; max_turns: number };

type ChatMessageEvent = {
  type: "CHAT_MESSAGE";
  session_id: number;
  message: ChatMessageRecord;
};

type ModerationResultPayload = {
  action: ModerationAction;
  risk_score: number;
  reason: string;
  guidance: string | null;
  needs_human_review: boolean;
};

type ModerationResultEvent = {
  type: "MODERATION_RESULT";
  session_id: number;
  message_id: number;
  moderation_event_id: number;
  result: ModerationResultPayload;
  sender_id?: number;
  tutor?: TutorStatus;
};

type GuidanceEvent = {
  type: "GUIDANCE";
  session_id: number;
  message_id: number;
  moderation_event_id: number;
  guidance: string;
};

type WarningEvent = {
  type: "WARNING";
  session_id: number;
  message_id: number;
  moderation_event_id: number;
  action: ModerationAction;
  warning: string;
};

type AdminNoteEvent = {
  type: "ADMIN_NOTE";
  session_id: number;
  message_id: number | null;
  note: string;
  created_at: string | null;
};

type StudyRoomErrorEvent = {
  type: "ERROR";
  code: string;
  message: string;
  details?: unknown;
};

type StudyRoomServerEvent =
  | SessionStatusEvent
  | ChatMessageEvent
  | ModerationResultEvent
  | GuidanceEvent
  | WarningEvent
  | AdminNoteEvent
  | StudyRoomErrorEvent;

type AgentEvents = {
  moderation?: ModerationResultEvent;
  guidance?: GuidanceEvent;
  warning?: WarningEvent;
};

const connectionTone: Record<ConnectionState, string> = {
  idle: styles.neutral,
  connecting: styles.pending,
  connected: styles.live,
  closed: styles.neutral,
  "auth-error": styles.danger,
  forbidden: styles.danger,
  error: styles.danger,
};

const connectionLabel: Record<ConnectionState, string> = {
  idle: "Idle",
  connecting: "Connecting",
  connected: "Connected",
  closed: "Closed",
  "auth-error": "Unauthorized",
  forbidden: "Forbidden",
  error: "Error",
};

export default function StudyRoom({ token, sessionId, peerName = "Bạn đồng hành", topic }: StudyRoomProps) {
  const normalizedSessionId = String(sessionId ?? "").trim();
  const currentUserId = useMemo(() => decodeUserId(token), [token]);
  const socketRef = useRef<WebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const [connectionState, setConnectionState] = useState<ConnectionState>("idle");
  const [connectionMessage, setConnectionMessage] = useState("Waiting for a session.");
  const [messages, setMessages] = useState<ChatMessageRecord[]>([]);
  const [agentEvents, setAgentEvents] = useState<Record<number, AgentEvents>>({});
  const [presenceEvents, setPresenceEvents] = useState<SessionStatusEvent[]>([]);
  const [onlineUsers, setOnlineUsers] = useState<number[]>([]);
  const [roomErrors, setRoomErrors] = useState<StudyRoomErrorEvent[]>([]);
  const [adminNotes, setAdminNotes] = useState<AdminNoteEvent[]>([]);
  const [sendError, setSendError] = useState("");
  const [draft, setDraft] = useState("");
  const [tutor, setTutor] = useState<TutorStatus | null>(null);
  const [historyReady,setHistoryReady] = useState(false);
  const [introDone,setIntroDone] = useState(true);
  const introKey = `peerbridge_intro:${currentUserId}:${peerName}`;
  useEffect(()=>{setIntroDone(localStorage.getItem(introKey)==="done");},[introKey]);
  useEffect(()=>{if(messages.length){localStorage.setItem(introKey,"done");setIntroDone(true);}},[messages.length,introKey]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ block: "end" });
  }, [messages, agentEvents, roomErrors, presenceEvents]);

  useEffect(() => {
    setMessages([]); setHistoryReady(false);
    setAgentEvents({});
    setPresenceEvents([]);
    setOnlineUsers([]);
    setRoomErrors([]);
    setAdminNotes([]);
    setSendError("");
    setDraft("");
    setTutor(null);

    if (!token || !normalizedSessionId) {
      setConnectionState("idle");
      setConnectionMessage("Missing token or session ID.");
      return;
    }

    let isActive = true;
    void api.session(token, normalizedSessionId).then(session => {
      if (!isActive) return;
      if (session.icebreaker_eligible === false) setIntroDone(true);
      setHistoryReady(true);
      const history = session.chat_messages.filter(m => m.id !== null).map(m => ({ ...m, id: m.id! }));
      setMessages(current => [...history, ...current.filter(m => !history.some(h => h.id === m.id))]);
    }).catch(() => { /* REST failures do not interrupt the active socket. */ });
    let socket: WebSocket;

    try {
      socket = studyRoomSocket(normalizedSessionId, token);
    } catch {
      setConnectionState("error");
      setConnectionMessage("Could not create the Study Room WebSocket.");
      return;
    }

    socketRef.current = socket;
    setConnectionState("connecting");
    setConnectionMessage("Opening WebSocket connection to the backend.");

    const applyServerEvent = (event: StudyRoomServerEvent) => {
      if (!isStudyRoomEventForSession(event, normalizedSessionId)) {
        setRoomErrors((current) => [
          ...current,
          {
            type: "ERROR",
            code: "SESSION_MISMATCH",
            message: `Received event for session ${"session_id" in event ? event.session_id : "unknown"}.`,
          },
        ]);
        return;
      }

      switch (event.type) {
        case "SESSION_STATUS":
          setPresenceEvents((current) => [...current, event].slice(-8));
          setOnlineUsers((current) => updateOnlineUsers(current, event));
          if (event.user_id === currentUserId && event.tutor) setTutor(event.tutor);
          break;
        case "CHAT_MESSAGE":
          setMessages((current) => upsertMessage(current, event.message));
          break;
        case "MODERATION_RESULT":
          setAgentEvents((current) => ({
            ...current,
            [event.message_id]: { ...current[event.message_id], moderation: event },
          }));
          if (event.sender_id === currentUserId && event.tutor) setTutor(event.tutor);
          break;
        case "GUIDANCE":
          setAgentEvents((current) => ({
            ...current,
            [event.message_id]: { ...current[event.message_id], guidance: event },
          }));
          break;
        case "WARNING":
          setAgentEvents((current) => ({
            ...current,
            [event.message_id]: { ...current[event.message_id], warning: event },
          }));
          break;
        case "ADMIN_NOTE":
          setAdminNotes((current) => [...current, event]);
          break;
        case "ERROR":
          setRoomErrors((current) => [...current, event]);
          break;
      }
    };

    socket.onopen = () => {
      if (!isActive) return;
      setConnectionState("connected");
      setConnectionMessage("Connected. Waiting for Study Room events.");
    };

    socket.onmessage = (messageEvent) => {
      if (!isActive) return;
      const parsed = parseStudyRoomEvent(messageEvent.data);
      if (!parsed.ok) {
        setRoomErrors((current) => [
          ...current,
          { type: "ERROR", code: "INVALID_SERVER_EVENT", message: parsed.error },
        ]);
        return;
      }
      applyServerEvent(parsed.event);
    };

    socket.onerror = () => {
      if (!isActive) return;
      setConnectionState((current) => (current === "connected" ? current : "error"));
      setConnectionMessage("WebSocket error. Check backend availability and session access.");
    };

    socket.onclose = (closeEvent) => {
      if (!isActive) return;
      if (socketRef.current === socket) socketRef.current = null;
      const next = describeClose(closeEvent);
      setConnectionState(next.state);
      setConnectionMessage(next.message);
    };

    return () => {
      isActive = false;
      if (socketRef.current === socket) socketRef.current = null;
      socket.onopen = null;
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;
      if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
        socket.close(1000, "StudyRoom component unmounted");
      }
    };
  }, [normalizedSessionId, token, currentUserId]);

  function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSendError("");

    const content = draft.trim();
    if (!content) return;

    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      setSendError("WebSocket is not connected.");
      return;
    }

    try {
      socket.send(JSON.stringify({ type: "CHAT_MESSAGE", content }));
      setDraft("");
    } catch {
      setSendError("Could not send the message over WebSocket.");
    }
  }

  const canSend = connectionState === "connected" && draft.trim().length > 0;

  return (
    <section className={styles.shell} aria-label="Study Room">
      <header className={styles.header}>
        <div>
          <span className={styles.eyebrow}>Cùng tập trung · Cùng tiến bộ</span>
          <h2>Trao đổi với {peerName}</h2>
          <p>Một lời chào, một câu hỏi, một chút động viên.</p>
        </div>
        <span className={`${styles.connectionPill} ${connectionTone[connectionState]}`}>
          <i />
          {connectionState === "connected" ? "Đã kết nối" : connectionState === "connecting" ? "Đang kết nối" : "Chưa kết nối"}
        </span>
      </header>

      <div className={`${styles.connectionNotice} ${connectionTone[connectionState]}`}>
        <Icon name={connectionState === "connected" ? "check" : "shield"} />
        <span>{connectionState === "connected" ? "Hai bạn có thể nhắn tin và chia sẻ điều đang vướng." : connectionState === "connecting" ? "Đang mở cuộc trò chuyện…" : "Kết nối tạm ngắt. Quay về lịch rồi vào lại phòng để thử lại."}</span>
      </div>

      <div className={styles.layout}>
        <section className={styles.roomPanel}>
          <div className={styles.messageList} role="log" aria-live="polite">
            {messages.length === 0 && roomErrors.length === 0 ? (
              <div className={styles.emptyState}>
                <Icon name="message" />
                <b>Bắt đầu bằng một lời chào nhé 👋</b>
                <span>Bạn có thể chọn một câu phá băng bên cạnh, rồi sửa trước khi gửi.</span>
              </div>
            ) : null}

            {messages.map((message) => {
              const isMine = currentUserId !== null && message.sender_id === currentUserId;
              return (
                <div className={styles.messageGroup} key={message.id}>
                  <article className={`${styles.message} ${isMine ? styles.mine : ""}`}>
                    <div className={styles.messageMeta}>
                      <b>{isMine ? "Bạn" : peerName}</b>
                      <span>{formatTime(message.created_at)}</span>
                    </div>
                    <p>{message.content}</p>
                  </article>
                  <AgentResponse event={agentEvents[message.id]} />
                </div>
              );
            })}

            {Object.entries(agentEvents).filter(([id, event]) =>
              !messages.some(message => message.id === Number(id)) &&
              (Boolean(event.warning) || Boolean(event.guidance)))
              .map(([id, event]) => <div className={styles.messageGroup} key={`held-${id}`}>
                <p>Tin nhắn đang được xử lý riêng.</p>
                <AgentResponse event={event} />
              </div>)}

            {adminNotes.map((note, index) => (
              <div className={styles.errorEvent} key={`admin-note-${index}`} role="status">
                <b>📣 Admin nhắn hai bạn</b>
                <span>{note.note}</span>
              </div>
            ))}

            {roomErrors.map((error, index) => (
              <div className={styles.errorEvent} key={`${error.code}-${index}`}>
                <b>{error.code}</b>
                <span>{error.message}</span>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          <form className={styles.composer} onSubmit={sendMessage}>
            <input
              aria-label="Message"
              disabled={connectionState !== "connected"}
              maxLength={2000}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={connectionState === "connected" ? "Nhắn bạn đồng hành hoặc chia sẻ điều đang vướng…" : "Chờ kết nối để gửi tin"}
              value={draft}
            />
            <button className={styles.sendButton} disabled={!canSend} type="submit" aria-label="Send message">
              <Icon name="send" />
            </button>
          </form>
          {sendError ? <p className={styles.sendError}>{sendError}</p> : null}
        </section>

        <aside className={styles.sideRail}>
          {historyReady && !introDone && messages.length === 0 && connectionState === "connected" && <Icebreaker name={peerName} topic={topic} onChoose={setDraft}/>}
          <section className={styles.statusCard}><div><h3>🌱 Nhịp học của hai bạn</h3><p>Học song song: nói mục tiêu đầu buổi, chia sẻ một điều làm được cuối buổi.</p><p>Đổi kèm: giải thích → hỏi lại → tự làm một ví dụ → đổi vai.</p><small>BridgeBot gợi mở khi cần. Bạn vẫn là người tự làm bài.</small></div></section>
          <section className={styles.statusCard}><div><h3>🤖 Trợ giảng AI</h3><p>{tutor?.active ? "Đang hỗ trợ" : "Sẵn sàng hỗ trợ khi bạn gặp khó khăn."}</p>{tutor?.active && tutor.topic ? <p>Chủ đề: {tutor.topic}</p> : null}{tutor?.active ? <p>Tiến trình gợi ý: {tutor.turn_count}/{tutor.max_turns}</p> : null}</div></section>
        </aside>
      </div>
    </section>
  );
}

const actionTone: Record<ModerationAction, string> = {
  ALLOW: styles.allow,
  GUIDE: styles.guide,
  WARN: styles.warn,
  BLOCK: styles.block,
  ESCALATE: styles.escalate,
};

function AgentResponse({ event }: { event?: AgentEvents }) {
  if (!event?.guidance && !event?.warning && (!event?.moderation || event.moderation.result.action === "ALLOW")) return null;

  const result = event.moderation?.result;

  return (
    <div className={styles.agentResponse}>
      <span className={styles.agentIcon}>
        <Icon name={event.warning ? "shield" : "spark"} />
      </span>
      <div>
        <div className={styles.agentHeader}>
          <b>🤖 BridgeBot gợi ý</b>
          {result ? <span className={`${styles.actionBadge} ${actionTone[result.action]}`}>{result.action === "GUIDE" ? "Gợi mở" : "Giữ cuộc trò chuyện an toàn"}</span> : null}
        </div>
        {event.guidance ? <p className={styles.guidance}>{event.guidance.guidance}</p> : null}
        {event.warning ? <p className={styles.warning}>{event.warning.warning}</p> : null}
      </div>
    </div>
  );
}

function parseStudyRoomEvent(raw: unknown): { ok: true; event: StudyRoomServerEvent } | { ok: false; error: string } {
  if (typeof raw !== "string") return { ok: false, error: "WebSocket message was not text JSON." };

  let payload: unknown;
  try {
    payload = JSON.parse(raw);
  } catch {
    return { ok: false, error: "WebSocket message was not valid JSON." };
  }

  if (!isRecord(payload) || typeof payload.type !== "string") {
    return { ok: false, error: "WebSocket event is missing a string type." };
  }

  switch (payload.type) {
    case "SESSION_STATUS":
      return normalizeSessionStatus(payload);
    case "CHAT_MESSAGE":
      return normalizeChatMessage(payload);
    case "MODERATION_RESULT":
      return normalizeModerationResult(payload);
    case "GUIDANCE":
      return normalizeGuidance(payload);
    case "WARNING":
      return normalizeWarning(payload);
    case "ADMIN_NOTE":
      return normalizeAdminNote(payload);
    case "ERROR":
      return normalizeError(payload);
    default:
      return { ok: false, error: `Unsupported Study Room event type: ${payload.type}` };
  }
}

function normalizeSessionStatus(payload: Record<string, unknown>) {
  if (!isNumber(payload.session_id) || !isNumber(payload.user_id) || typeof payload.status !== "string") {
    return invalidEvent("SESSION_STATUS");
  }
  return {
    ok: true,
    event: {
      type: "SESSION_STATUS",
      session_id: payload.session_id,
      user_id: payload.user_id,
      status: payload.status,
      tutor: isTutorStatus(payload.tutor) ? payload.tutor : undefined,
    },
  } as const;
}

function normalizeChatMessage(payload: Record<string, unknown>) {
  const message = payload.message;
  if (!isNumber(payload.session_id) || !isRecord(message)) return invalidEvent("CHAT_MESSAGE");
  if (
    !isNumber(message.id) ||
    !isNumber(message.session_id) ||
    !isNumber(message.sender_id) ||
    typeof message.content !== "string" ||
    !(typeof message.created_at === "string" || message.created_at === null)
  ) {
    return invalidEvent("CHAT_MESSAGE");
  }
  return {
    ok: true,
    event: {
      type: "CHAT_MESSAGE",
      session_id: payload.session_id,
      message: {
        id: message.id,
        session_id: message.session_id,
        sender_id: message.sender_id,
        content: message.content,
        created_at: message.created_at,
      },
    },
  } as const;
}

function normalizeModerationResult(payload: Record<string, unknown>) {
  const result = payload.result;
  if (
    !isNumber(payload.session_id) ||
    !isNumber(payload.message_id) ||
    !isNumber(payload.moderation_event_id) ||
    !isRecord(result) ||
    !isModerationAction(result.action) ||
    !isNumber(result.risk_score) ||
    typeof result.reason !== "string" ||
    !(typeof result.guidance === "string" || result.guidance === null) ||
    typeof result.needs_human_review !== "boolean"
  ) {
    return invalidEvent("MODERATION_RESULT");
  }
  return {
    ok: true,
    event: {
      type: "MODERATION_RESULT",
      session_id: payload.session_id,
      message_id: payload.message_id,
      moderation_event_id: payload.moderation_event_id,
      sender_id: isNumber(payload.sender_id) ? payload.sender_id : undefined,
      tutor: isTutorStatus(payload.tutor) ? payload.tutor : undefined,
      result: {
        action: result.action,
        risk_score: result.risk_score,
        reason: result.reason,
        guidance: result.guidance,
        needs_human_review: result.needs_human_review,
      },
    },
  } as const;
}

function normalizeGuidance(payload: Record<string, unknown>) {
  if (
    !isNumber(payload.session_id) ||
    !isNumber(payload.message_id) ||
    !isNumber(payload.moderation_event_id) ||
    typeof payload.guidance !== "string"
  ) {
    return invalidEvent("GUIDANCE");
  }
  return {
    ok: true,
    event: {
      type: "GUIDANCE",
      session_id: payload.session_id,
      message_id: payload.message_id,
      moderation_event_id: payload.moderation_event_id,
      guidance: payload.guidance,
    },
  } as const;
}

function normalizeWarning(payload: Record<string, unknown>) {
  if (
    !isNumber(payload.session_id) ||
    !isNumber(payload.message_id) ||
    !isNumber(payload.moderation_event_id) ||
    !isModerationAction(payload.action) ||
    typeof payload.warning !== "string"
  ) {
    return invalidEvent("WARNING");
  }
  return {
    ok: true,
    event: {
      type: "WARNING",
      session_id: payload.session_id,
      message_id: payload.message_id,
      moderation_event_id: payload.moderation_event_id,
      action: payload.action,
      warning: payload.warning,
    },
  } as const;
}

function normalizeError(payload: Record<string, unknown>) {
  if (typeof payload.code !== "string" || typeof payload.message !== "string") return invalidEvent("ERROR");
  return {
    ok: true,
    event: {
      type: "ERROR",
      code: payload.code,
      message: payload.message,
      details: payload.details,
    },
  } as const;
}

function normalizeAdminNote(payload: Record<string, unknown>): { ok: true; event: AdminNoteEvent } | { ok: false; error: string } {
  if (!isNumber(payload.session_id) || typeof payload.note !== "string" || !payload.note.trim()) return invalidEvent("ADMIN_NOTE");
  return {
    ok: true,
    event: {
      type: "ADMIN_NOTE",
      session_id: payload.session_id,
      message_id: isNumber(payload.message_id) ? payload.message_id : null,
      note: payload.note,
      created_at: typeof payload.created_at === "string" ? payload.created_at : null,
    },
  };
}

function invalidEvent(type: string): { ok: false; error: string } {
  return { ok: false, error: `Malformed ${type} event from Study Room WebSocket.` };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isTutorStatus(value: unknown): value is TutorStatus {
  return isRecord(value) && typeof value.active === "boolean" && typeof value.topic === "string" &&
    isNumber(value.turn_count) && isNumber(value.max_turns);
}

function isModerationAction(value: unknown): value is ModerationAction {
  return value === "ALLOW" || value === "GUIDE" || value === "WARN" || value === "BLOCK" || value === "ESCALATE";
}

function isStudyRoomEventForSession(event: StudyRoomServerEvent, sessionId: string) {
  if (event.type === "ERROR") return true;
  return String(event.session_id) === sessionId;
}

function upsertMessage(messages: ChatMessageRecord[], message: ChatMessageRecord) {
  const index = messages.findIndex((item) => item.id === message.id);
  if (index === -1) return [...messages, message].sort((left, right) => left.id - right.id);
  return messages.map((item) => (item.id === message.id ? message : item));
}

function updateOnlineUsers(users: number[], event: SessionStatusEvent) {
  if (event.status === "JOINED") return users.includes(event.user_id) ? users : [...users, event.user_id].sort((a, b) => a - b);
  if (event.status === "LEFT") return users.filter((userId) => userId !== event.user_id);
  return users;
}

function describeClose(event: CloseEvent): { state: ConnectionState; message: string } {
  if (event.code === 4401) return { state: "auth-error", message: "Authentication failed. The token was rejected." };
  if (event.code === 4403) return { state: "forbidden", message: "This user cannot access the requested study session." };
  if (event.wasClean) return { state: "closed", message: "WebSocket connection closed." };
  return { state: "error", message: `WebSocket closed unexpectedly${event.code ? ` with code ${event.code}` : ""}.` };
}

function formatTime(value: string | null) {
  if (!value) return "now";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return formatClock(value);
}

function decodeUserId(token: string) {
  const payload = token.split(".")[1];
  if (!payload) return null;
  try {
    const base64 = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
    const data = JSON.parse(atob(padded)) as unknown;
    if (!isRecord(data) || typeof data.sub !== "string") return null;
    const userId = Number.parseInt(data.sub, 10);
    return Number.isFinite(userId) ? userId : null;
  } catch {
    return null;
  }
}
