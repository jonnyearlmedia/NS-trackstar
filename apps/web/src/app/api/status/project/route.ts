import { NextRequest, NextResponse } from "next/server";

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
  id: string;
  name: string;
  project_type: string;
  geometry: unknown | null;
  location: unknown;
  statuses: Record<string, string>;
  assertions: Array<{
    field: string;
    value: unknown;
    authority_type: string;
    confidence: number;
    source_url?: string | null;
  }>;
  sources: Array<{
    source_key: string;
    source_name: string;
    relationship_type: string;
    confidence: number;
    url?: string | null;
  }>;
};

export async function GET(request: NextRequest) {
  const query = request.nextUrl.searchParams.get("q")?.trim();
  if (!query || query.length < 2) {
    return NextResponse.json({ ok: false, error: "q must be at least 2 characters" }, { status: 400 });
  }

  try {
    const searchResponse = await fetch(
      `${API_BASE}/search/projects?${new URLSearchParams({ q: query, limit: "8" })}`,
      { cache: "no-store" },
    );
    if (!searchResponse.ok) {
      return NextResponse.json({ ok: false, search_status: searchResponse.status }, { status: 502 });
    }

    const matches = (await searchResponse.json()) as SearchResult[];
    const projects = await Promise.all(
      matches.map(async (match) => {
        const detailResponse = await fetch(`${API_BASE}/projects/${match.id}`, { cache: "no-store" });
        if (!detailResponse.ok) {
          return { ...match, detail_status: detailResponse.status };
        }
        const detail = (await detailResponse.json()) as ProjectDetail;
        return {
          id: detail.id,
          name: detail.name,
          project_type: detail.project_type,
          mapped: detail.geometry !== null,
          location: detail.location,
          statuses: detail.statuses,
          assertions: detail.assertions,
          sources: detail.sources,
          matched_on: match.matched_on,
        };
      }),
    );

    return NextResponse.json({ ok: true, query, projects, checked_at: new Date().toISOString() });
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: error instanceof Error ? error.message : "project probe failed" },
      { status: 502 },
    );
  }
}
