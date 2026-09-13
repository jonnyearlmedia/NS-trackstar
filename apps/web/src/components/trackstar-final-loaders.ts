import type { MapViewportState, TimeWindow } from "./map-final-model";
import type { AreaChangesResponse, ProjectClassification, ProjectDetail, ProjectEvent, SearchResult } from "./trackstar-final-ui";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function loadProjectBundle(id: string, signal: AbortSignal) {
  const [detailResponse, eventsResponse, classificationResponse] = await Promise.all([
    fetch(`${API_BASE}/projects/${id}`, { signal }),
    fetch(`${API_BASE}/projects/${id}/events`, { signal }),
    fetch(`${API_BASE}/projects/${id}/classification`, { signal }),
  ]);
  if (!detailResponse.ok || !eventsResponse.ok || !classificationResponse.ok) throw new Error("Project unavailable");
  return {
    detail: await detailResponse.json() as ProjectDetail,
    events: await eventsResponse.json() as ProjectEvent[],
    classification: await classificationResponse.json() as ProjectClassification,
  };
}

export async function searchProjects(query: string, signal: AbortSignal) {
  const response = await fetch(`${API_BASE}/search/projects/classified?${new URLSearchParams({ q: query, limit: "20" })}`, { signal });
  if (!response.ok) throw new Error("Search failed");
  return response.json() as Promise<SearchResult[]>;
}

export async function loadAreaChanges(viewport: MapViewportState, window: TimeWindow, signal: AbortSignal) {
  const params = new URLSearchParams({
    west: String(viewport.bounds.west),
    south: String(viewport.bounds.south),
    east: String(viewport.bounds.east),
    north: String(viewport.bounds.north),
    window: window === "all" ? "week" : window,
    limit: "250",
  });
  const response = await fetch(`${API_BASE}/area/changes/public?${params}`, { signal });
  if (!response.ok) throw new Error("Area updates failed");
  return response.json() as Promise<AreaChangesResponse>;
}
