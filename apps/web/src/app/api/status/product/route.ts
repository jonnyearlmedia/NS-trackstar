import { NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://15-204-82-184.sslip.io";
const ONE_LAKE_ID = "b4d202ca-d7c1-4518-8a39-0e61ac967363";

export const dynamic = "force-dynamic";

type MapProbe = {
  features?: Array<{
    properties?: {
      display_priority?: number;
      source_count?: number;
      project_type?: string;
    };
  }>;
};

type BriefingProbe = Array<{ project_type?: string; event?: { event_type?: string } | null }>;
type ChangesProbe = Array<{ project_type?: string; event_type?: string; significance?: number }>;

export async function GET() {
  try {
    const mapParams = new URLSearchParams({
      west: "-122.25",
      south: "38.05",
      east: "-121.85",
      north: "38.45",
      window: "all",
    });
    const [briefingResponse, contextResponse, mapResponse, changesResponse] = await Promise.all([
      fetch(`${API_BASE}/briefing?window=week&limit=3`, { cache: "no-store" }),
      fetch(`${API_BASE}/projects/${ONE_LAKE_ID}/context`, { cache: "no-store" }),
      fetch(`${API_BASE}/map/projects?${mapParams}`, { cache: "no-store" }),
      fetch(`${API_BASE}/changes?window=week&limit=5`, { cache: "no-store" }),
    ]);

    const briefingText = await briefingResponse.text();
    const contextText = await contextResponse.text();
    const mapText = await mapResponse.text();
    const changesText = await changesResponse.text();
    const parse = (text: string): unknown => {
      try {
        return JSON.parse(text) as unknown;
      } catch {
        return text.slice(0, 500);
      }
    };

    const briefing = parse(briefingText) as BriefingProbe;
    const changes = parse(changesText) as ChangesProbe;
    const map = parse(mapText) as MapProbe;
    const firstFeature = Array.isArray(map?.features) ? map.features[0] : undefined;
    const relevanceSignals =
      typeof firstFeature?.properties?.display_priority === "number" &&
      typeof firstFeature?.properties?.source_count === "number";
    const consumerBriefing =
      Array.isArray(briefing) &&
      briefing.every(
        (item) =>
          item.project_type !== "environmental_review" &&
          item.event?.event_type !== "project_discovered",
      );
    const consumerUpdates =
      Array.isArray(changes) &&
      changes.every(
        (item) =>
          item.project_type !== "environmental_review" &&
          (item.event_type !== "project_discovered" || Number(item.significance ?? 0) > 0.5),
      );
    const ok =
      briefingResponse.ok &&
      contextResponse.ok &&
      mapResponse.ok &&
      changesResponse.ok &&
      relevanceSignals &&
      consumerBriefing &&
      consumerUpdates;

    return NextResponse.json(
      {
        ok,
        briefing_status: briefingResponse.status,
        context_status: contextResponse.status,
        map_status: mapResponse.status,
        changes_status: changesResponse.status,
        relevance_signals: relevanceSignals,
        consumer_briefing: consumerBriefing,
        consumer_updates: consumerUpdates,
        briefing,
        updates: changes,
        context: parse(contextText),
        map_sample: firstFeature ?? null,
        checked_at: new Date().toISOString(),
      },
      { status: ok ? 200 : 502 },
    );
  } catch (error) {
    return NextResponse.json(
      { ok: false, error: error instanceof Error ? error.message : "product probe failed" },
      { status: 502 },
    );
  }
}