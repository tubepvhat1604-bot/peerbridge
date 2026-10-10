// Hợp đồng API trang Tổng quan, thông báo và số liệu AI (backend/app/home, backend/app/checkin/stats.py).
export type AppPage = "dashboard" | "matching" | "connections" | "sessions" | "plan" | "checkin" | "profile" | "moderation" | "analytics" | "architecture";

export interface OnboardingStep { key: "profile" | "connect" | "plan" | "checkin"; title: string; done: boolean; page: AppPage; hint: string }
export interface PlanPreviewItem { id: string; label: string; concept_id: string; scheduled_start: string | null; est_minutes: number; due_now: boolean }
export interface ActivityItem { id: number; kind: string; title: string; body: string; page: AppPage; relative: string; unread: boolean }

export interface HomeOverview {
  display_name: string;
  profile_completion: number;
  profile_missing: string[];
  pending_invites: number;
  connections: number;
  pair: { pair_id: number; partner_id: number; partner_name: string } | null;
  plan: { today_total?: number; today_done?: number; has_plan: boolean; week_total: number; week_done: number; minutes_total: number; minutes_done: number; next: PlanPreviewItem[] };
  checkin: {
    checked_in_today: boolean;
    partner_checked_in_today: boolean;
    streak: number;
    total_done: number;
    partner_latest: { headline: string; relative: string } | null;
  };
  sessions: { id: number; topic: string; scheduled_start: string }[];
  steps: OnboardingStep[];
  progress: PairProgress | null;
  coach: CoachAdvice | null;
  activity: ActivityItem[];
  unread: number;
}

export interface NotificationItem { id: number; kind: string; title: string; body: string; page: AppPage; created_at: string; read_at: string | null }
export interface NotificationList { items: NotificationItem[]; unread: number }

export interface AiStats {
  days: number;
  total_checkins: number;
  by_status: Record<string, number>;
  ai_accept_rate: number | null;
  user_correction_rate: number | null;
  ask_again_rate: number | null;
  not_study_rate: number | null;
  avg_confidence: number | null;
  latency_p50_ms: number | null;
  latency_p90_ms: number | null;
  cost_usd: number;
  cost_today_usd: number;
  daily_budget_usd: number;
  model: string;
  per_day: { date: string; checkins: number; cost_usd: number }[];
}

export interface ProgressSide { pacing: number | null; completed_minutes: number; due_minutes: number }
export type PairProgress =
  | { available: false; reason: string }
  | { available: true; as_of: string; me: ProgressSide; partner: ProgressSide; pair_score: number; gap: number;
      needs_attention: boolean; i_am_lagging: boolean; my_risk: number | null; streak: number };
export interface CoachAdvice { action: string; text: string | null; source: string; status: string; created_at: string; proposal_id: number | null }
