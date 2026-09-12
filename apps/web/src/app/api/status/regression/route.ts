import { NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://15-204-82-184.sslip.io";

export const dynamic = "force-dynamic";

type SearchResult = {
  id: string;
  name: string;
  project_type: string;
  geometry: unknown | null;
  matched_on: string;
};

type ProjectDetail = {
  sources?: Array<{ source_key?: string }>;
};

type Fixture = {
  key: string;
  label: string;
  queries: string[];
  expectedNames: string[];
  requiredSourceKeys?: string[];
};

const FIXTURES: Fixture[] = [
  {
    key: "scotts-valley-casino",
    label: "Scotts Valley casino",
    queries: ["Scotts Valley", "casino"],
    expectedNames: ["scotts valley casino", "scotts valley casino and tribal housing project"],
  },
  {
    key: "sr37-sears-point-mare-island",
    label: "SR 37 Sears Point–Mare Island",
    queries: ["SR 37", "Sears Point", "Mare Island"],
    expectedNames: [
      "state route 37 sears point to mare island improvement project",
      "state route (sr) 37 sears point to mare island improvement project",
    ],
  },
  {
    key: "napa-pipe",
    label: "Napa Pipe",
    queries: ["Napa Pipe"],
    expectedNames: ["napa pipe"],
    requiredSourceKeys: ["napa-city.napa-pipe-amendments"],
  },
  {
    key: "one-lake-canon-station",
    label: "One Lake / Canon Station",
    queries: ["One Lake", "Canon Station"],
    expectedNames: ["one lake", "canon station"],
    requiredSourceKeys: ["fairfield.one-lake-council-goals"],
  },
  {
    key: "dutch-bros-suisun",
    label: "Dutch Bros Suisun",
    queries: ["Dutch Bros", "Suisun"],
    expectedNames: ["dutch bros"],
    requiredSourceKeys: ["suisun-city.development-calendar"],
  },
];

async function search(query: string): Promise<SearchResult[]> {
  const response = await fetch(
    `${API_BASE}/search/projects?${new URLSearchParams({ q: query, limit: "10" })}`,
    { cache: "no-store" },
  );
  if (!response.ok) throw new Error(`search ${query} returned ${response.status}`);
  return response.json() as Promise<SearchResult[]>;
}

async function sourceKeys(projectId: string): Promise<string[]> {
  const response = await fetch(`${API_BASE}/projects/${projectId}`, { cache: "no-store" });
  if (!response.ok) return [];
  const detail = (await response.json()) as ProjectDetail;
  return (detail.sources ?? [])
    .map((source) => source.source_key)
    .filter((key): key is string => Boolean(key));
}

export async function GET() {
  try {
    const todayCatalogPromise = fetch(`${API_BASE}/projects?window=today`, { cache: "no-store" });
    const fixtureResults = await Promise.all(
      FIXTURES.map(async (fixture) => {
        const batches = await Promise.all(fixture.queries.map(search));
        const unique = new Map<string, SearchResult>();
        for (const batch of batches) {
          for (const result of batch) unique.set(result.id, result);
        }
        const matches = [...unique.values()].slice(0, 12);
        const nameMatches = matches.filter((match) => {
          const name = match.name.toLocaleLowerCase();
          return fixture.expectedNames.some(
            (expected) => name === expected || name.includes(expected) || expected.includes(name),
          );
        });
        const candidates = await Promise.all(
          nameMatches.map(async (match) => ({ match, source_keys: await sourceKeys(match.id) })),
        );
        const canonicalMatches = candidates.filter(({ source_keys }) => {
          if (!fixture.requiredSourceKeys?.length) return true;
          return fixture.requiredSourceKeys.every((required) => source_keys.includes(required));
        });
        return {
          key: fixture.key,
          label: fixture.label,
          found: canonicalMatches.length > 0,
          map_ready: canonicalMatches.some(({ match }) => match.geometry !== null),
          evidence_found: matches.length > 0,
          required_source_keys: fixture.requiredSourceKeys ?? [],
          canonical_matches: canonicalMatches.map(({ match, source_keys }) => ({
            id: match.id,
            name: match.name,
            project_type: match.project_type,
            mapped: match.geometry !== null,
            matched_on: match.matched_on,
            source_keys,
          })),
          search_matches: matches.map((match) => ({
            id: match.id,
            name: match.name,
            project_type: match.project_type,
            mapped: match.geometry !== null,
            matched_on: match.matched_on,
          })),
        };
      }),
    );

    const todayCatalogResponse = await todayCatalogPromise;
    const todayCatalog = todayCatalogResponse.ok
      ? ((await todayCatalogResponse.json()) as unknown[])
      : [];
    const missing = fixtureResults.filter((fixture) => !fixture.found).map((fixture) => fixture.key);
    const unmapped = fixtureResults.filter((fixture) => fixture.found && !fixture.map_ready).map((fixture) => fixture.key);

    return NextResponse.json({
      ok: missing.length === 0 && unmapped.length === 0 && todayCatalogResponse.ok,
      catalog: {
        endpoint_ok: todayCatalogResponse.ok,
        today_count: todayCatalog.length,
      },
      fixtures: fixtureResults,
      missing,
      unmapped,
      checked_at: new Date().toISOString(),
    });
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: error instanceof Error ? error.message : "regression probe failed" },
      { status: 502 },
    );
  }
}
