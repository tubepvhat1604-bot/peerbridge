"use client";

import Avatar from "../Avatar";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { ConnectionResponse, ConnectionStatus, MatchSearchCandidate, MatchSearchResponse } from "@/lib/types";
import { connectionStatusLabels, errorMessage, initials, LoadingState, StatusBadge } from "./shared";
import { useConnections } from "./useConnections";

const componentLabels: Record<string, string> = {
  skill_complementarity: "Kiến thức bổ trợ",
  topic_compatibility: "Chủ đề học tập",
  availability_overlap: "Thời gian phù hợp",
  preference_compatibility: "Mục tiêu học tập",
};

export function Matching({ token, notify, onConnections }: {
  token: string;
  notify: (message: string) => void;
  onConnections: () => void;
}) {
  const [result, setResult] = useState<MatchSearchResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sendingId, setSendingId] = useState<number | null>(null);
  const [invitations, setInvitations] = useState<Record<number, ConnectionResponse>>({});
  const [invitationErrors, setInvitationErrors] = useState<Record<number, string>>({});
  const mounted = useRef(true);
  const searchInFlight = useRef(false);
  const sendInFlight = useRef(false);
  const connections = useConnections(token);

  useEffect(() => {
    if (connections.data) setInvitations({});
  }, [connections.data]);

  const search = useCallback(async () => {
    if (searchInFlight.current) return;
    searchInFlight.current = true;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const response = await api.searchMatches(token);
      if (mounted.current) setResult(response);
    } catch (failure) {
      if (mounted.current) setError(errorMessage(failure));
    } finally {
      searchInFlight.current = false;
      if (mounted.current) setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    mounted.current = true;
    void search();
    return () => { mounted.current = false; };
  }, [search]);

  function statusFor(candidateId: number): ConnectionStatus | null {
    if (connections.data?.connected.some((item) => item.peer.user_id === candidateId)) return "MATCHED";
    const pending = [...(connections.data?.incoming ?? []), ...(connections.data?.sent ?? [])]
      .find((item) => item.peer.user_id === candidateId && item.status === "PENDING");
    return pending?.status ?? invitations[candidateId]?.status ?? null;
  }

  async function invite(candidate: MatchSearchCandidate) {
    const status = statusFor(candidate.candidate_id);
    if (sendInFlight.current || loading || connections.loading || connections.error || !connections.data
      || status === "PENDING" || status === "MATCHED") return;
    sendInFlight.current = true;
    setSendingId(candidate.candidate_id);
    setInvitationErrors((current) => ({ ...current, [candidate.candidate_id]: "" }));
    try {
      const response = await api.requestConnection(token, { recipient_id: candidate.candidate_id });
      if (!mounted.current) return;
      setInvitations((current) => ({ ...current, [candidate.candidate_id]: response }));
      notify(`Đã gửi lời mời tới ${candidate.display_name}.`);
      await connections.refresh();
    } catch (failure) {
      if (!mounted.current) return;
      setInvitationErrors((current) => ({ ...current, [candidate.candidate_id]: errorMessage(failure) }));
      if (failure instanceof ApiError && failure.status === 409) await connections.refresh();
    } finally {
      sendInFlight.current = false;
      if (mounted.current) setSendingId(null);
    }
  }

  return <div className="page animate-in peer-workspace">
    <div className="page-title">
      <div><span className="eyebrow">Một người bạn · Một lời hứa chung</span><h1>Tìm người học cùng nhịp</h1><p>Tìm người hiểu mục tiêu của bạn, có giờ học cùng và sẵn sàng động viên nhau.</p></div>
      <div className="page-actions"><button className="outline" onClick={onConnections}>Xem kết nối</button><button className="primary" disabled={loading || sendingId !== null} onClick={() => { void search(); void connections.refresh(); }}>{loading ? "Đang tìm người phù hợp..." : "Cập nhật kết quả"}</button></div>
    </div>
    {loading && <LoadingState message="Đang tìm người phù hợp..."/>}
    {error && <div className="peer-error" role="alert"><p>{error}</p><button className="outline" disabled={loading} onClick={() => void search()}>Thử lại</button></div>}
    {connections.loading && <LoadingState message="Đang cập nhật trạng thái lời mời..."/>}
    {connections.error && <div className="peer-error" role="alert"><p>Không tải được trạng thái kết nối: {connections.error}</p><button className="outline" disabled={connections.loading || sendingId !== null} onClick={() => void connections.refresh()}>Thử lại trạng thái kết nối</button></div>}
    {!loading && !error && result && <>
      <div className="match-summary" role="status"><span><b>{result.candidates.length}</b> người học phù hợp</span><small>{result.matching_mode === "live" ? "AI phân tích mục tiêu và nhu cầu" : "Gợi ý cá nhân hóa · nhu cầu, mục tiêu và lịch rảnh"}</small></div>
      {result.candidates.length === 0 ? <div className="panel peer-empty"><h2>Chưa tìm thấy người học phù hợp</h2><p>Hãy cập nhật nhu cầu hỗ trợ, khả năng hỗ trợ và lịch rảnh trong hồ sơ, rồi tìm lại.</p></div> :
        <div className="candidate-grid">{result.candidates.map((candidate) => {
          const status = statusFor(candidate.candidate_id);
          const unavailable = status === "PENDING" || status === "MATCHED";
          return <article className="candidate-card" key={candidate.candidate_id}>
            <div className="candidate-goal" style={{ background: "var(--surface-sunken)", padding: "12px", borderRadius: "12px", marginBottom: "16px", fontWeight: "600", color: "var(--accent-text)", border: "1px solid var(--border)" }}>🎯 {candidate.learning_goals?.[0] || "Đang tìm một người cùng giữ cam kết học tập"}</div>
            <div className="candidate-top"><Avatar seed={candidate.candidate_id} size={76}/><div className="compatibility-score"><b>{candidate.total_score >= 75 ? "Rất hợp" : candidate.total_score >= 60 ? "Hợp nhịp" : "Cùng thử nhé"}</b><span>{Math.round(candidate.total_score)}/100 điểm phù hợp</span></div></div>
            <h2>{candidate.display_name}</h2><p className="major">{[candidate.major, candidate.school].filter(Boolean).join(" · ") || "Chưa cập nhật ngành/trường"}</p>
            {candidate.bio && <p className="candidate-bio">{candidate.bio}</p>}
            <div className="topic-pair" style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", gap: "12px", background: "var(--surface-sunken)", padding: "16px", borderRadius: "16px", alignItems: "center", textAlign: "center" }}><div><small style={{ display: "block", color: "var(--text-soft)", fontSize: "0.75rem", marginBottom: "4px" }}>CẦN HỖ TRỢ</small><b style={{ color: "var(--text-strong)" }}>{candidate.needs?.join(", ") || "Cùng giữ nhịp"}</b></div><span style={{ color: "var(--border-strong)" }}>⇄</span><div><small style={{ display: "block", color: "var(--text-soft)", fontSize: "0.75rem", marginBottom: "4px" }}>CÓ THỂ HỖ TRỢ</small><b style={{ color: "var(--text-strong)" }}>{candidate.strengths?.join(", ") || "Động viên nhau"}</b></div></div>
            <p className="schedule">🗓️ {candidate.availability?.length ? candidate.availability.slice(0,3).map(w => `${["T2","T3","T4","T5","T6","T7","CN"][w.day_of_week]} ${w.start_time.slice(0,5)}–${w.end_time.slice(0,5)}`).join(" · ") : "Trao đổi thêm về giờ học phù hợp"}</p>
            <div className="match-reasons"><b>🌉 Vì sao hai bạn có thể hợp?</b>{candidate.reasons?.map(r => <p key={r}>✓ {r}</p>)}</div>
            <details className="component-scores"><summary>Xem mức độ phù hợp</summary><dl>{Object.entries(candidate.component_scores).map(([name, score]) => <div key={name}><dt>{componentLabels[name] ?? name}</dt><dd>{score.toLocaleString("vi-VN", { maximumFractionDigits: 4 })}</dd></div>)}</dl></details>
            {status && <StatusBadge status={status}/>}
            {invitationErrors[candidate.candidate_id] && <p className="form-error" role="alert">{invitationErrors[candidate.candidate_id]}</p>}
            <div className="candidate-invite"><button className={unavailable ? "secondary" : "primary"} disabled={unavailable || sendingId !== null || connections.loading || !!connections.error || !connections.data} onClick={() => void invite(candidate)}>{sendingId === candidate.candidate_id ? "Đang gửi lời mời..." : unavailable ? connectionStatusLabels[status] : "Cùng học nhé →"}</button></div>
          </article>;
        })}</div>}
    </>}
  </div>;
}
