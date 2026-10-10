import type {
  ConnectedPeerSummary,
  ConnectionCreateRequest,
  ConnectionResponse,
  ConnectionsResponse,
  CoachDecision,
  GeneratePlan,
  GeneratePlanResult,
  LoginRequest,
  MatchSearchResponse,
  ProfileMeResponse,
  ProfileMeUpdate,
  PlanProposal,
  PlanSetup,
  PlanView,
  RegisterRequest,
  StudySession,
  StudySessionCreateRequest,
  StudySessionFromConnectionRequest,
  StudySessionListResponse,
  StudySessionResponse,
  TokenResponse,
} from "@/lib/types";
import type { Checkin, CheckinFeed } from "@/lib/checkin-types";
import type { AiStats, HomeOverview, NotificationList } from "@/lib/home-types";
import type { AdminOverview, AdminSessionDetail, AdminSessionRow, SessionReview, WhoAmI } from "@/lib/admin-types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type ApiOptions = RequestInit & { token?: string };

const unauthorizedListeners = new Set<(token: string) => void>();

export function subscribeToUnauthorized(listener: (token: string) => void): () => void {
  unauthorizedListeners.add(listener);
  return () => { unauthorizedListeners.delete(listener); };
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

function formatApiError(body: unknown, fallback: string) {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (item && typeof item === "object" && "msg" in item) return String((item as { msg: unknown }).msg);
          return String(item);
        })
        .join("; ");
    }
  }
  if (typeof body === "string" && body.trim()) return body;
  return fallback;
}

async function request<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const { token, headers, ...init } = options;
  // FormData (ảnh) tự đặt Content-Type multipart; chỉ JSON mới cần header này.
  const isForm = typeof FormData !== "undefined" && init.body instanceof FormData;
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...(isForm ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
  });
  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) as unknown : null;
  } catch {
    body = text;
  }
  if (!response.ok) {
    if (response.status === 401 && token) {
      unauthorizedListeners.forEach((listener) => listener(token));
    }
    throw new ApiError(response.status, formatApiError(body, `API ${response.status}`));
  }
  return body as T;
}

export const api = {
  home: (token: string) => request<HomeOverview>("/api/v1/home", { token }),
  notifications: (token: string) => request<NotificationList>("/api/v1/notifications?limit=20", { token }),
  readNotifications: (token: string, ids?: number[]) => request<{ unread: number }>("/api/v1/notifications/read", { token, method: "POST", body: JSON.stringify({ ids: ids ?? null }) }),
  aiStats: (token: string, days = 7) => request<AiStats>(`/api/v1/checkins/stats?days=${days}`, { token }),
  checkinFeed: (token: string) => request<CheckinFeed>("/api/v1/pairs/me/feed", { token }),
  checkin: (token: string, id: string) => request<Checkin>(`/api/v1/checkins/${encodeURIComponent(id)}`, { token }),
  createPhotoCheckin: (token: string, id: string, image: Blob, note: string) => {
    const form = new FormData();
    form.append("id", id);
    form.append("image", image, "checkin.jpg");
    if (note.trim()) form.append("note", note.trim());
    return request<Checkin>("/api/v1/checkins", { token, method: "POST", body: form });
  },
  createTextCheckin: (token: string, id: string, note: string, planItemId?: string) => request<Checkin>("/api/v1/checkins/text", { token, method: "POST", body: JSON.stringify({ id, note, plan_item_id: planItemId || null }) }),
  planNotes: (token: string, pair: number) => request<{items: {id: number; user_id: number; display_name: string; text: string; created_at: string}[]}>(`/api/v1/plans/${pair}/notes`, { token }),
  addPlanNote: (token: string, pair: number, text: string) => request(`/api/v1/plans/${pair}/notes`, { token, method: "POST", body: JSON.stringify({text}) }),
  confirmCheckin: (token: string, id: string, planItemId: string | null) => request<Checkin>(`/api/v1/checkins/${encodeURIComponent(id)}/confirm`, { token, method: "POST", body: JSON.stringify({ plan_item_id: planItemId }) }),
  reactCheckin: (token: string, id: string, body: { emoji?: string; comment?: string }) => request<Checkin>(`/api/v1/checkins/${encodeURIComponent(id)}/reactions`, { token, method: "POST", body: JSON.stringify(body) }),
  nudgePartner: (token: string, pairId: number) => request<{ message: string }>(`/api/v1/pairs/${pairId}/nudge`, { token, method: "POST" }),
  planCommitments: (token: string, pair: number) => request<{mine: boolean; partner: boolean; both: boolean}>(`/api/v1/plans/${pair}/commitments`, { token }),
  commitPlan: (token: string, pair: number) => request<{mine: boolean; partner: boolean; both: boolean}>(`/api/v1/plans/${pair}/commit`, { token, method: "POST" }),
  planSetup: (token: string, pair: number) => request<PlanSetup>(`/api/v1/plans/${pair}/setup`, { token }),
  plan: (token: string, pair: number) => request<PlanView>(`/api/v1/plans/${pair}`, { token }),
  generatePlan: (token: string, payload: GeneratePlan, key: string) => request<GeneratePlanResult>("/api/v1/plans/generate", { token, method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(payload) }),
  editPlanSchedule: (token: string, pair: number, item: string, version: number, scheduled_start: string, minutes: number) => request(`/api/v1/plans/${pair}/items/${item}/schedule`, {token, method: "PATCH", body: JSON.stringify({expected_version:version,scheduled_start,minutes})}),
  replan: (token: string, pair: number, version: number) => request<PlanProposal>(`/api/v1/plans/${pair}/replan`, { token, method: "POST", body: JSON.stringify({ expected_version: version, reduce_load: true }) }),
  decideReplan: (token: string, pair: number, proposal: number, version: number, accept: boolean) => request<{ applied: boolean; duplicate: boolean }>(`/api/v1/plans/${pair}/proposals/${proposal}/${accept ? "accept" : "reject"}`, { token, method: "POST", body: JSON.stringify({ expected_version: version }) }),
  evaluateCoach: (token: string, pair: number) => request<CoachDecision>(`/api/v1/coach/${pair}/evaluate`, { token, method: "POST" }),
  register: (payload: RegisterRequest) => request<TokenResponse>("/api/v1/auth/register", { method: "POST", body: JSON.stringify(payload) }),
  demoInfo: () => request<{ enabled: boolean; accounts: { slug: string; name: string }[] }>("/api/v1/demo"),
  demoLogin: (slug: string) => request<TokenResponse>(`/api/v1/demo/login/${slug}`, { method: "POST" }),
  login: (payload: LoginRequest) => request<TokenResponse>("/api/v1/auth/login", { method: "POST", body: JSON.stringify(payload) }),
  profile: (token: string) => request<ProfileMeResponse>("/api/v1/profiles/me", { token }),
  updateProfile: (token: string, payload: ProfileMeUpdate) => request<ProfileMeResponse>("/api/v1/profiles/me", { method: "PUT", token, body: JSON.stringify(payload) }),
  searchMatches: (token: string) => request<MatchSearchResponse>("/api/v1/matches/search", { method: "POST", token }),
  matchResult: (token: string, requestId: number) => request<MatchSearchResponse>(`/api/v1/matches/${requestId}`, { token }),
  listConnections: (token: string) => request<ConnectionsResponse>("/api/v1/connections", { token }),
  requestConnection: (token: string, payload: ConnectionCreateRequest) => request<ConnectionResponse>("/api/v1/connections", { method: "POST", token, body: JSON.stringify(payload) }),
  acceptConnection: (token: string, id: number) => request<ConnectionResponse>(`/api/v1/connections/${id}/accept`, { method: "POST", token }),
  rejectConnection: (token: string, id: number) => request<ConnectionResponse>(`/api/v1/connections/${id}/reject`, { method: "POST", token }),
  listSessions: (token: string) => request<StudySessionListResponse>("/api/v1/sessions", { token }),
  createSession: (token: string, payload: StudySessionCreateRequest) => request<StudySessionResponse>("/api/v1/sessions", { method: "POST", token, body: JSON.stringify(payload) }),
  createSessionFromConnection: async (token: string, connection: ConnectedPeerSummary, details: StudySessionFromConnectionRequest): Promise<StudySessionResponse> => {
    const { peer_match_id, requester_id, recipient_id } = connection;
    if (![peer_match_id, requester_id, recipient_id].every(isPositiveInteger) || requester_id === recipient_id) {
      throw new TypeError("A valid connected peer is required to create a study session.");
    }
    if (details.learner_id !== requester_id && details.learner_id !== recipient_id) {
      throw new TypeError("The learner must be a member of the connected peer match.");
    }
    // The backend still validates the authenticated user's membership and role.
    return api.createSession(token, {
      peer_match_id,
      learner_id: details.learner_id,
      helper_id: details.learner_id === requester_id ? recipient_id : requester_id,
      topic: details.topic,
      scheduled_start: details.scheduled_start,
      scheduled_end: details.scheduled_end,
    });
  },
  session: (token: string, id: string | number) => request<StudySessionResponse>(`/api/v1/sessions/${encodeURIComponent(String(id))}`, { token }),
  whoami: (token: string) => request<WhoAmI>("/api/v1/admin/me", { token }),
  sessionReview: (token: string, id: number) => request<{ review: SessionReview | null }>(`/api/v1/sessions/${id}/review`, { token }),
  createSessionReview: (token: string, id: number) => request<{ review: SessionReview | null }>(`/api/v1/sessions/${id}/review`, { method: "POST", token }),
  adminOverview: (token: string) => request<AdminOverview>("/api/v1/admin/overview", { token }),
  adminSessions: (token: string) => request<{ items: AdminSessionRow[]; count: number }>("/api/v1/admin/sessions", { token }),
  adminSession: (token: string, id: number) => request<AdminSessionDetail>(`/api/v1/admin/sessions/${id}`, { token }),
  adminReviewSession: (token: string, id: number) => request<{ review: SessionReview | null }>(`/api/v1/admin/sessions/${id}/review`, { method: "POST", token }),
  moderationQueue: (token: string) => request("/instructor/moderation", { token }),
  reviewModeration: (token: string, id: string, payload: unknown) => request(`/instructor/moderation/${id}/review`, { method: "POST", token, body: JSON.stringify(payload) }),
};

function isPositiveInteger(value: number): boolean {
  return Number.isInteger(value) && value > 0;
}

/** UI eligibility only: the WebSocket backend remains the authorization authority. */
export function canJoinStudySession(session: StudySession, userId: number): boolean {
  return session.id !== null && isPositiveInteger(session.id)
    && isPositiveInteger(userId)
    && (session.learner_id === userId || session.helper_id === userId);
}

export function studyRoomSocket(sessionId: string, token: string) {
  const base = API_URL.replace(/^http/, "ws");
  return new WebSocket(`${base}/ws/sessions/${sessionId}?token=${encodeURIComponent(token)}`);
}
