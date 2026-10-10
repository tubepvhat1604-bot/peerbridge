// Kiểu dữ liệu cho tóm tắt phiên học và các màn Admin (backend: app/session_review).

export type WhoAmI = { user_id: number; role: "ADMIN" | "STUDENT"; is_admin: boolean };

export type SessionReview = {
  session_id: number;
  mode: "ai" | "rules";
  summary: string;
  key_points: string[];
  open_questions: string[];
  next_steps: string[];
  message_count: number;
  updated_at: string;
  // Chỉ Admin nhận các trường chấm điểm.
  socratic_score?: number | null;
  answer_leaked?: boolean;
  leak_message_ids?: number[];
  judge_notes?: string;
  ai_error?: string;
};

export type SessionVerdict = {
  mode: "ai" | "rules";
  stored: boolean;
  socratic_score: number | null;
  answer_leaked: boolean;
  has_chat: boolean;
};

export type PersonRef = { id: number; name: string | null };

export type AdminSessionRow = {
  id: number;
  peer_match_id: number;
  topic: string;
  learner: PersonRef;
  helper: PersonRef;
  scheduled_start: string | null;
  created_at: string;
  message_count: number;
  held_count: number;
  guide_count: number;
  pending_review: number;
  last_activity: string | null;
  verdict: SessionVerdict;
};

export type AdminMessage = {
  id: number;
  sender_id: number;
  sender_role: "learner" | "helper";
  sender_name: string | null;
  content: string;
  created_at: string;
  moderation_event_id: number | null;
  agent_action: string | null;
  final_action: string | null;
  delivered: boolean;
  risk_score: number | null;
  reason: string | null;
  guidance: string | null;
  intent: string | null;
  prefiltered: boolean;
  needs_review: boolean;
  review_action: string | null;
  review_notes: string | null;
};

export type AdminSessionDetail = {
  session: {
    id: number; topic: string; learner_id: number; helper_id: number;
    learner_name: string | null; helper_name: string | null; scheduled_start: string | null; messages: AdminMessage[];
  };
  review: SessionReview | null;
  verdict: SessionVerdict;
};

export type AdminOverview = {
  students: number;
  pairs: number;
  sessions_total: number;
  sessions_with_chat: number;
  sessions_7d: number;
  messages_total: number;
  messages_held: number;
  guides_total: number;
  actions: Record<"ALLOW" | "GUIDE" | "WARN" | "BLOCK" | "ESCALATE", number>;
  pending_reviews: number;
  leak_free: { sessions: number; leaked: number; rate: number | null; judged_by_ai: number };
  socratic_avg: number | null;
  ai: {
    messages_prefiltered: number;
    messages_ai_classified: number;
    saved_rate: number | null;
    moderation_cost_today_usd: number;
    review_cost_today_usd: number;
    budget_left_usd: number | null;
  };
  network: Array<{
    peer_match_id: number; members: PersonRef[]; sessions: number; messages: number; held: number;
    leaked_sessions: number; socratic_avg: number | null; last_activity: string;
  }>;
};
