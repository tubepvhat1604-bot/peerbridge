import {formatDateTime} from "@/lib/time";
import Avatar from "../Avatar";
import type { ConnectionPeerProfile, ConnectionStatus } from "@/lib/types";

export const connectionStatusLabels: Record<ConnectionStatus, string> = {
  PENDING: "Đang chờ phản hồi",
  MATCHED: "Đã kết nối",
  REJECTED: "Đã từ chối",
  EXPIRED: "Đã hết hạn",
};

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Không thể xử lý yêu cầu. Vui lòng thử lại.";
}

export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  return words.length > 1
    ? `${words[0][0]}${words[words.length - 1][0]}`.toUpperCase()
    : (words[0] ?? "?").slice(0, 2).toUpperCase();
}

export function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : formatDateTime(value);
}

export function StatusBadge({ status }: { status: ConnectionStatus }) {
  return <span className={`connection-status status-${status.toLowerCase()}`}>{connectionStatusLabels[status]}</span>;
}

export function LoadingState({ message }: { message: string }) {
  return <p className="status-line peer-loading" role="status" aria-live="polite">
    <span className="peer-spinner" aria-hidden="true"/>
    <span>{message}</span>
  </p>;
}

export function PeerIdentity({ peer }: { peer: ConnectionPeerProfile }) {
  return <>
    <Avatar seed={peer.user_id}/>
    <div className="peer-identity">
      <h3>{peer.display_name}</h3>
      <p>{[peer.major, peer.school].filter(Boolean).join(" · ") || "Chưa cập nhật ngành/trường"}</p>
    </div>
  </>;
}

export function Participants({ requesterId, recipientId, userId, peer }: {
  requesterId: number;
  recipientId: number;
  userId: number;
  peer: ConnectionPeerProfile;
}) {
  const name = (id: number) => id === userId ? "Bạn" : peer.display_name;
  return <p className="connection-participants">Người gửi: {name(requesterId)} · Người nhận: {name(recipientId)}</p>;
}
