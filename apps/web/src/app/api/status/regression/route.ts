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

type Fixture = {
  key: string;
  label: string;
  queries: string[];
};

const FIXTURES: Fixture[] = [
  {
    key: "scotts-valley-casino",
    label: "Scotts Valley casino",
    queries: ["Scotts Valley", "casino"],
  },
  {
    key: "sr37-sears-point-mare-island",
    label: "SR 37 Sears Point–Mare Island",
    queries: ["SR 37", "Sears Point", "Mare Island"],
  },
  {
    key: "napa-pipe",
    label: "Napa Pipe",
    queries: ["Napa Pipe"],
  },
  {
    key: "one-lake-canon-station",
    label: "One Lake / Canon Station",
    queries: ["One Lake", "Canon Station"],
  },
  {
    key: "dutch-bros-suisun",
    label: "Dutch Bros Suisun",
    queries: ["Dutch Bros", "Suisun"],
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
        return {
          key: fixture.key,
          label: fixture.label,
          found: matches.length > 0,
          matches: matches.map((match) => ({
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

    return NextResponse.json({
      ok: missing.length === 0 && todayCatalogResponse.ok,
      catalog: {
        endpoint_ok: todayCatalogResponse.ok,
        today_count: todayCatalog.length,
      },
      fixtures: fixtureResults,
      missing,
      checked_at: new Date().toISOString(),
    });
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: error instanceof Error ? error.message : "regression probe failed" },
      { status: 502 },
    );
  }
}
