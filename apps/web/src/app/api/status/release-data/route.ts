import { NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://15-204-82-184.sslip.io";

export const dynamic = "force-dynamic";

type CadenceItem = {
  source_key: string;
  poll_interval_minutes: number;
  cadence_policy_state: string;
  freshness_class: string;
  health_state: string | null;
  stability_state: string;
  success_rate: number | null;
  missed_expected_check: boolean;
  runs_with_changes: number;
  successful_runs: number;
  latest_run?: { outcome?: string | null; records_changed?: number };
};

type CadencePayload = { items?: CadenceItem[]; metadata?: Record<string, unknown> };
type LifecyclePayload = {
  stage_counts?: Record<string, number>;
  unknown_raw_statuses?: Array<{ dimension: string; value: string; project_count: number }>;
};
type ChurnPayload = {
  latest_run?: { records_returned?: number; records_changed?: number } | null;
  field_changes?: Array<{ field: string; changed_records: number }>;
};
type QualityPayload = {
  metadata?: {
    duplicate_name_group_count?: number;
    high_confidence_unresolved_count?: number;
    conflicting_assertion_count?: number;
    manual_sample_count?: number;
  };
  duplicate_name_groups?: unknown[];
  high_confidence_unresolved_candidates?: unknown[];
  conflicting_current_assertions?: unknown[];
  manual_qa_sample?: unknown[];
};

const RELEASE_CRITICAL_FRESHNESS_CLASSES = new Set([
  "meeting_feed",
  "active_project_tracker",
  "state_project_watch",
  "regulatory_watch",
]);

async function json<T>(path: string): Promise<{ ok: boolean; status: number; body: T | null }> {
  try {
    const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
    return { ok: response.ok, status: response.status, body: response.ok ? await response.json() as T : null };
  } catch {
    return { ok: false, status: 0, body: null };
  }
}

export async function GET() {
  const [health, cadence, lifecycle, civicClerk, quality] = await Promise.all([
    fetch(`${API_BASE}/health`, { cache: "no-store" }).then((response) => ({ ok: response.ok, status: response.status })).catch(() => ({ ok: false, status: 0 })),
    json<CadencePayload>("/admin/sources/cadence?days=7"),
    json<LifecyclePayload>("/admin/lifecycle/audit?sample_limit=5"),
    json<ChurnPayload>("/admin/sources/vallejo.civicclerk/churn-fields"),
    json<QualityPayload>("/admin/quality/audit"),
  ]);

  const cadenceItems = cadence.body?.items ?? [];
  const stageCounts = lifecycle.body?.stage_counts ?? {};
  const civic = cadenceItems.find((item) => item.source_key === "vallejo.civicclerk") ?? null;
  const policyProblems = cadenceItems.filter((item) => !["within_policy", "unclassified"].includes(item.cadence_policy_state));
  const unhealthy = cadenceItems.filter((item) => item.health_state !== "healthy");
  const missed = cadenceItems.filter((item) => item.missed_expected_check);
  const unstable = cadenceItems.filter((item) => item.stability_state === "unstable");
  const blockingUnstable = unstable.filter((item) => RELEASE_CRITICAL_FRESHNESS_CLASSES.has(item.freshness_class));
  const referenceWarnings = unstable.filter((item) => !RELEASE_CRITICAL_FRESHNESS_CLASSES.has(item.freshness_class));

  const ok = health.ok
    && cadence.ok
    && lifecycle.ok
    && cadenceItems.length === 23
    && unhealthy.length === 0
    && missed.length === 0
    && blockingUnstable.length === 0
    && policyProblems.length === 0;

  return NextResponse.json({
    ok,
    backend_health: health,
    cadence: {
      status: cadence.status,
      source_count: cadenceItems.length,
      unhealthy_source_keys: unhealthy.map((item) => item.source_key),
      missed_source_keys: missed.map((item) => item.source_key),
      blocking_unstable_source_keys: blockingUnstable.map((item) => item.source_key),
      reference_warning_source_keys: referenceWarnings.map((item) => item.source_key),
      policy_problem_source_keys: policyProblems.map((item) => item.source_key),
      items: cadenceItems.map((item) => ({
        source_key: item.source_key,
        poll_interval_minutes: item.poll_interval_minutes,
        freshness_class: item.freshness_class,
        cadence_policy_state: item.cadence_policy_state,
        health_state: item.health_state,
        stability_state: item.stability_state,
        success_rate: item.success_rate,
        successful_runs: item.successful_runs,
        runs_with_changes: item.runs_with_changes,
        latest_outcome: item.latest_run?.outcome ?? null,
        latest_records_changed: item.latest_run?.records_changed ?? 0,
      })),
    },
    lifecycle: {
      status: lifecycle.status,
      stage_counts: stageCounts,
      project_count: Object.values(stageCounts).reduce((sum, count) => sum + Number(count || 0), 0),
      top_unknown_statuses: (lifecycle.body?.unknown_raw_statuses ?? []).slice(0, 20),
    },
    civicclerk: {
      cadence: civic,
      churn_status: civicClerk.status,
      latest_run: civicClerk.body?.latest_run ?? null,
      field_changes: (civicClerk.body?.field_changes ?? []).slice(0, 20),
    },
    quality: {
      status: quality.status,
      metadata: quality.body?.metadata ?? null,
      duplicate_name_groups: (quality.body?.duplicate_name_groups ?? []).slice(0, 20),
      high_confidence_unresolved_candidates: (quality.body?.high_confidence_unresolved_candidates ?? []).slice(0, 20),
      conflicting_current_assertions: (quality.body?.conflicting_current_assertions ?? []).slice(0, 20),
      manual_qa_sample: (quality.body?.manual_qa_sample ?? []).slice(0, 20),
    },
    checked_at: new Date().toISOString(),
  }, { status: ok ? 200 : 502 });
}
