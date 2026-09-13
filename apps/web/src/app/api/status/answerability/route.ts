import { NextResponse } from "next/server";
import fixtures from "../../../../../../../fixtures/answerability/napa-solano.json";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://15-204-82-184.sslip.io";

export const dynamic = "force-dynamic";

type FixtureProject = {
  key: string;
  name: string;
  jurisdiction: string;
  identity_fields: string[];
  scale_fields: string[];
  location_fields: string[];
  next_step_fields: string[];
  status_dimensions: string[];
  required_relationship_types: string[];
  required_evidence_families: string[];
};

type SearchResult = { id: string; name: string; geometry: unknown | null };

type Explainer = {
  what_is_this: string;
  whats_happening: string | null;
  whats_next: string | null;
  why_care: Array<{ field: string }>;
  evidence_backed: boolean;
};

type ProjectDetail = {
  name: string;
  geometry: unknown | null;
  last_activity_at: string | null;
  statuses: Record<string, string>;
  assertions: Array<{ field: string }>;
  sources: Array<{ source_key?: string }>;
  explainer?: Explainer | null;
  evidence_sections?: Array<{ items: Array<{ field: string }> }> | null;
};

// The generic card this whole contract exists to prevent.
const GENERIC = ["a development project in napa", "napa-solano", "napa–solano"];

async function findProject(name: string): Promise<SearchResult | null> {
  const response = await fetch(
    `${API_BASE}/search/projects?${new URLSearchParams({ q: name, limit: "5" })}`,
    { cache: "no-store" },
  );
  if (!response.ok) return null;
  const results = (await response.json()) as SearchResult[];
  const wanted = name.toLocaleLowerCase();
  return (
    results.find((result) => {
      const found = result.name.toLocaleLowerCase();
      return found.includes(wanted) || wanted.includes(found);
    }) ?? null
  );
}

function assess(project: FixtureProject, detail: ProjectDetail) {
  const held = new Set(detail.assertions.map((assertion) => assertion.field));
  const explainer = detail.explainer ?? null;
  const summary = explainer?.what_is_this?.toLocaleLowerCase() ?? "";
  const surfacedScale = new Set((explainer?.why_care ?? []).map((fact) => fact.field));

  return {
    what_is_this: Boolean(explainer?.evidence_backed) && !GENERIC.some((phrase) => summary.includes(phrase)),
    current_status: Object.keys(detail.statuses ?? {}).some((dimension) =>
      project.status_dimensions.includes(dimension),
    ),
    latest_change: Boolean(explainer?.whats_happening),
    next_step: Boolean(explainer?.whats_next),
    useful_scale: project.scale_fields.some((field) => surfacedScale.has(field)),
    location: detail.geometry !== null || project.location_fields.some((field) => held.has(field)),
    official_evidence: (detail.sources ?? []).length > 0,
    // Collector run time is not project activity, so freshness is only satisfied by a
    // real published timestamp on the record itself.
    source_freshness: Boolean(detail.last_activity_at),
  };
}

export async function GET() {
  const projects = fixtures.projects as FixtureProject[];
  try {
    const results = await Promise.all(
      projects.map(async (project) => {
        const match = await findProject(project.name);
        if (!match) {
          return { key: project.key, jurisdiction: project.jurisdiction, found: false, answers: null };
        }
        const response = await fetch(`${API_BASE}/projects/${match.id}`, { cache: "no-store" });
        if (!response.ok) {
          return { key: project.key, jurisdiction: project.jurisdiction, found: true, answers: null };
        }
        const detail = (await response.json()) as ProjectDetail;
        const answers = assess(project, detail);
        return {
          key: project.key,
          jurisdiction: project.jurisdiction,
          found: true,
          project_id: match.id,
          name: detail.name,
          answers,
          unanswered: Object.entries(answers)
            .filter(([, ok]) => !ok)
            .map(([question]) => question),
        };
      }),
    );

    const missing = results.filter((result) => !result.found).map((result) => result.key);
    const degraded = results
      .filter((result) => result.answers && (result.unanswered?.length ?? 0) > 0)
      .map((result) => ({ key: result.key, unanswered: result.unanswered }));

    return NextResponse.json({
      ok: missing.length === 0 && degraded.length === 0,
      checked_at: new Date().toISOString(),
      questions: fixtures.questions,
      results,
      missing,
      degraded,
      awaiting_source: fixtures.awaiting_source,
    });
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: error instanceof Error ? error.message : "answerability probe failed" },
      { status: 502 },
    );
  }
}
