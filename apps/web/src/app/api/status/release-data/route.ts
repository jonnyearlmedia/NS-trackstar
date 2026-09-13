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

type CadencePayload = {
  items?: CadenceItem[];
  metadata?: Record<string, unknown>;
};

type LifecyclePayload = {
  stage_counts?: Record<string, number>;
  unknown_raw_statuses?: Array<{ dimension: string; value: string; project_count: number }>;
  metadata?: Record<string, unknown>;
};

type ChurnPayload = {
  latest_run?: { records_returned?: number; records_changed?: number } | null;
  field_changes?: Array<{ field: string; changed_records: number }>;
};

async function json<T>(path: string): Promise<{ ok: boolean; status: number; body: T | null }> {
  try {
    const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
    return { ok: response.ok, status: response.status, body: response.ok ? await response.json() as T : null };
  } catch {
    return { ok: false, status: 0, body: null };
  }
}

export async function GET() {
  const [health, cadence, lifecycle, civicClerk] = await Promise.all([
    fetch(`${API_BASE}/health`, { cache: "no-store" }).then((response) => ({ ok: response.ok, status: response.status })).catch(() => ({ ok: false, status: 0 })),
    json<CadencePayload>("/admin/sources/cadence?days=7"),
    json<LifecyclePayload>("/admin/lifecycle/audit?sample_limit=5"),
    json<ChurnPayload>("/admin/sources/vallejo.civicclerk/churn-fields"),
  ]);

  const cadenceItems = cadence.body?.items ?? [];
  const stageCounts = lifecycle.body?.stage_counts ?? {};
  const civic = cadenceItems.find((item) => item.source_key === "vallejo.civicclerk") ?? null;
  const policyProblems = cadenceItems.filter((item) => !["within_policy", "unclassified"].includes(item.cadence_policy_state));
  const unhealthy = cadenceItems.filter((item) => item.health_state !== "healthy");
  const missed = cadenceItems.filter((item) => item.missed_expected_check);
  const unstable = cadenceItems.filter((item) => item.stability_state === "unstable");

  const ok = health.ok && cadence.ok && lifecycle.ok && cadenceItems.length > 0 && missed.length === 0 && unstable.length === 0;

  return NextResponse.json({
    ok,
    backend_health: health,
    cadence: {
      status: cadence.status,
      source_count: cadenceItems.length,
      unhealthy_source_keys: unhealthy.map((item) => item.source_key),
      missed_source_keys: missed.map((item) => item.source_key),
      unstable_source_keys: unstable.map((item) => item.source_key),
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
    checked_at: new Date().toISOString(),
  }, { status: ok ? 200 : 502 });
}
