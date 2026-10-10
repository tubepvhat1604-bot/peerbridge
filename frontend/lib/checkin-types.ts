// Hợp đồng API check-in của AI Vision (backend/app/checkin/schemas.py).
export type CheckinStatus = "processing" | "needs_confirm" | "done" | "not_study" | "failed";

export interface CheckinOption { plan_item_id: string; label: string; concept_name: string | null }
export interface CheckinReaction { user_id: number; display_name: string; emoji: string | null; comment: string | null; relative: string }

export interface Checkin {
  id: string;
  status: CheckinStatus;
  kind: "photo" | "text";
  owner_id: number;
  owner_name: string;
  image_url: string | null;
  note: string | null;
  created_at: string;
  relative: string;
  headline: string;
  description: string | null;
  concept_names: string[];
  partner_summary: string | null;
  bridge: string | null;
  plan_item_label: string | null;
  options: CheckinOption[];
  reactions: CheckinReaction[];
}

export interface PersonProgress {
  user_id: number;
  display_name: string;
  pacing: number | null;
  done_items: number;
  total_items: number;
  checked_in_today: boolean;
}

export interface CheckinFeed {
  provider_mode?: string;
  pair_id: number;
  me: PersonProgress;
  partner: PersonProgress;
  streak: number;
  partner_latest: Checkin | null;
  my_latest: Checkin | null;
  my_pending: Checkin[];
  history: Checkin[];
  can_nudge: boolean;
  nudge_hint: string | null;
}

export const CHECKIN_EMOJIS = ["🔥", "👏", "💪", "😮", "❤️"] as const;
