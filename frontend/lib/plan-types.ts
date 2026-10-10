export interface PlanWindow { id: string; day_of_week: number; start_time: string; end_time: string }
export interface PlanMember {
  user_id: number; goal: string; concept_ids: string[]; known_concept_ids: string[]; can_help_concept_ids: string[];
  committed_minutes_per_week: number; availability: PlanWindow[]; timezone: string; location: string; deadline: string | null;
}
export interface PlanItem {
  id: string; user_id: number; pair_id: number; plan_version: number; concept_id: string; action: string; expected_output: string;
  est_minutes: number; scheduled_start: string | null; scheduled_end: string | null; if_then_text: string | null;
  status: "SCHEDULED" | "DEFERRED" | "COMPLETED"; defer_reason: string | null; resource_ids: string[];
}
export interface PersonalPlan {
  user_id: number; pair_id: number; plan_version: number; items: PlanItem[]; deferred_items: PlanItem[]; partial: boolean;
  warnings: { code: string; message: string }[];
}
export interface ReplanBudget {
  week_start: string; baseline_minutes: number; completed_minutes: number;
  remaining_minutes: number; proposed_limit_minutes: number;
}
export interface PlanProposal { id: number; status: string; expected_version: number; reason: string; cutoff: string; budget?: ReplanBudget[]; before: PersonalPlan; after: PersonalPlan }
export interface PlanView {
  id?: number; plan: PersonalPlan | null; timezone?: string; goal?: string; resources?: Record<string, string>;
  provider_mode?: string; catalog_source?: string; proposal: PlanProposal | null;
  partner: { user_id: number; goal: string; version: number; scheduled_count: number; completed_count: number; deferred_count: number; partial: boolean; items?: PlanItem[] } | null;
}
export interface PlanSetup {
  pair_id: number; catalog_source: string; provider_mode: string; resources: Record<string, string>;
  concepts: { id: string; track: "sql" | "python" | "english" | "ai"; prerequisites: string[]; action: string; expected_output: string; est_minutes: number }[];
  members: { user_id: number; display_name: string; goals: string[]; suggested_concept_ids?: string[]; availability: (PlanWindow & { timezone: string })[] }[];
}
export interface CoachDecision { action: string; reason: string; text?: string; sent: boolean; delivery_status?: string; proposal_id?: number | null; variant?: "ai" | "template"; message_source?: "ai" | "template" | "none"; selection?: { mode?: string; provider_mode?: string } }
export interface GeneratePlan { pair_id: number; members: PlanMember[]; horizon_days: number }
export interface GeneratePlanResult {
  plan_ids: Record<string, number>; version: number; trace_id: string; partial: boolean;
  provider_mode: string; catalog_source: string;
}
