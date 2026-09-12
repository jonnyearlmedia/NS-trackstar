import { NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://15-204-82-184.sslip.io";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const coverageParams = new URLSearchParams({
      window: "all",
      west: "0",
      south: "0",
      east: "0.01",
      north: "0.01",
    });
    const [healthResponse, coverageResponse, sourcesResponse] = await Promise.all([
      fetch(`${API_BASE}/health`, { cache: "no-store" }),
      fetch(`${API_BASE}/map/projects?${coverageParams}`, { cache: "no-store" }),
      fetch(`${API_BASE}/admin/sources/health`, { cache: "no-store" }),
    ]);

    if (!healthResponse.ok || !coverageResponse.ok || !sourcesResponse.ok) {
      return NextResponse.json(
        {
          ok: false,
          backend: healthResponse.status,
          coverage: coverageResponse.status,
          sources: sourcesResponse.status,
        },
        { status: 502 },
      );
    }

    const health = (await healthResponse.json()) as { status?: string };
    const coverage = (await coverageResponse.json()) as {
      metadata?: {
        mapped_matching?: number;
        location_pending?: number;
        total_matching?: number;
      };
    };
    const sources = (await sourcesResponse.json()) as Array<{ health_state?: string | null }>;
    const sourceStates = sources.reduce<Record<string, number>>((counts, source) => {
      const state = source.health_state ?? "unknown";
      counts[state] = (counts[state] ?? 0) + 1;
      return counts;
    }, {});

    return NextResponse.json({
      ok: health.status === "ok",
      backend: health.status ?? "unknown",
      projects: {
        total: coverage.metadata?.total_matching ?? null,
        mapped: coverage.metadata?.mapped_matching ?? null,
        location_pending: coverage.metadata?.location_pending ?? null,
      },
      sources: {
        total: sources.length,
        states: sourceStates,
      },
      checked_at: new Date().toISOString(),
    });
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: error instanceof Error ? error.message : "status probe failed" },
      { status: 502 },
    );
  }
}
