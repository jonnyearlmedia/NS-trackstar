import type { Geometry } from "geojson";
import type { ConsumerCategory, LifecycleFilter, LifecycleStage, MapProject, MapViewportState, ViewportBounds } from "./map-final-model";
import { isInsideServiceArea } from "./service-area";

export type AppView = "explore" | "updates";
export type ExploreMode = "orientation" | "free";
export type LocationState = "idle" | "checking" | "outside" | "denied" | "error";
export type SelectionOrigin = {
  view: AppView;
  browseOpen: boolean;
  exploreMode: ExploreMode;
  bounds: ViewportBounds | null;
};

export type ProjectDetail = {
  id: string;
  name: string;
  project_type: string;
  geometry: Geometry | null;
  summary?: string | null;
  last_activity_at?: string | null;
  location: { accuracy: string; confidence: number | null } | null;
  statuses: Record<string, string>;
  assertions: Array<{ field: string; value: unknown }>;
  sources: Array<{ source_key: string; source_name: string; relationship_type: string; url: string | null }>;
};
export type ProjectClassification = {
  project_id: string;
  consumer_category: Exclude<ConsumerCategory, "all">;
  lifecycle_stage: LifecycleStage;
  lifecycle_evidence: { dimension: string | null; value: string | null };
};
export type ProjectEvent = {
  id: string;
  title: string;
  occurred_at: string | null;
  observed_at: string;
  summary?: string | null;
  event_type?: string;
  significance?: number;
};
export type SearchResult = {
  id: string;
  name: string;
  project_type: string;
  geometry: Geometry | null;
  statuses: Record<string, string>;
  summary: string | null;
  consumer_category: Exclude<ConsumerCategory, "all">;
  lifecycle_stage: LifecycleStage;
};
export type ChangeEvent = ProjectEvent & {
  project_id: string;
  project_name: string;
  project_type: string;
  summary: string | null;
};
export type AreaChangesResponse = {
  items: ChangeEvent[];
  metadata: { window: string; limit: number; truncated: boolean };
};

export const CATEGORIES: Array<{ key: ConsumerCategory; label: string; longLabel: string; icon: string }> = [
  { key: "all", label: "All", longLabel: "All projects", icon: "◎" },
  { key: "development", label: "Development", longLabel: "Development", icon: "▦" },
  { key: "roads", label: "Roads", longLabel: "Roads & transit", icon: "↔" },
  { key: "utilities", label: "Utilities", longLabel: "Utilities", icon: "⌁" },
  { key: "places", label: "Places", longLabel: "Public places", icon: "◇" },
];
export const LIFECYCLE_OPTIONS: Array<{ label: string; value: LifecycleFilter }> = [
  { label: "Current", value: "current" },
  { label: "Any stage", value: "all" },
  { label: "Proposed", value: "proposed" },
  { label: "Under review", value: "review" },
  { label: "Approved", value: "approved" },
  { label: "Under construction", value: "construction" },
  { label: "Completed", value: "completed" },
  { label: "Inactive / withdrawn", value: "inactive" },
  { label: "Status unclear", value: "unknown" },
];
export const ACTIVITY_OPTIONS = [
  { label: "Any time", value: "all" },
  { label: "Changed today", value: "today" },
  { label: "Changed recently", value: "week" },
  { label: "Coming up", value: "upcoming" },
] as const;

export function categoryLabel(category: Exclude<ConsumerCategory, "all">) {
  if (category === "development") return "Development";
  if (category === "roads") return "Roads & transit";
  if (category === "utilities") return "Utilities";
  return "Public places";
}
export function lifecycleLabel(stage: LifecycleStage | LifecycleFilter) {
  if (stage === "current") return "Current";
  if (stage === "all") return "Any stage";
  if (stage === "proposed") return "Proposed";
  if (stage === "review") return "Under review";
  if (stage === "approved") return "Approved";
  if (stage === "construction") return "Under construction";
  if (stage === "completed") return "Completed";
  if (stage === "inactive") return "Inactive";
  return "Status unclear";
}
export function readableValue(value: unknown) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return new Intl.NumberFormat("en-US").format(value);
  if (typeof value === "string") return value.replaceAll("_", " ");
  return String(value);
}
export function eventDate(value: string | null | undefined) {
  if (!value) return "Date not published";
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(new Date(value));
}
export function eventHeadline(event: ProjectEvent) {
  if (event.event_type === "ceqa_document_received") return "New environmental review document filed";
  if (event.summary && event.summary !== event.title) return event.summary;
  return event.title.replaceAll("_", " ");
}
export function projectSummary(detail: ProjectDetail | null, selected: MapProject | null) {
  const direct = detail?.summary?.trim();
  if (direct) return direct.length > 280 ? `${direct.slice(0, 277).trimEnd()}…` : direct;
  if (!selected) return "";
  return `A ${categoryLabel(selected.consumerCategory).toLowerCase()} project in Napa–Solano. Open details for official records and history.`;
}
export function locationUncertain(detail: ProjectDetail | null, selected: MapProject | null) {
  if (selected?.locationUncertain) return true;
  if (!detail?.location) return false;
  if (detail.location.confidence !== null && detail.location.confidence < 0.75) return true;
  return !["exact_source_geometry", "exact_parcel", "exact_address"].includes(detail.location.accuracy);
}

const CITY_CENTERS = [
  { name: "American Canyon", lng: -122.2608, lat: 38.1749 },
  { name: "Vallejo", lng: -122.2566, lat: 38.1041 },
  { name: "Benicia", lng: -122.1586, lat: 38.0494 },
  { name: "Napa", lng: -122.2869, lat: 38.2975 },
  { name: "Fairfield", lng: -122.0399, lat: 38.2494 },
  { name: "Suisun City", lng: -122.0402, lat: 38.2383 },
];
export function areaLabel(viewport: MapViewportState | null) {
  if (!viewport || viewport.zoom < 9.2) return "Napa + Solano";
  let best: { name: string; distance: number } | null = null;
  for (const city of CITY_CENTERS) {
    const distance = Math.hypot(viewport.center.lng - city.lng, viewport.center.lat - city.lat);
    if (!best || distance < best.distance) best = { name: city.name, distance };
  }
  return best && best.distance < 0.22 ? best.name : "This area";
}
export function isViewportOutside(viewport: MapViewportState | null) {
  return viewport ? !isInsideServiceArea(viewport.center) : false;
}
export function routeProjectId() {
  if (typeof window === "undefined") return null;
  return window.location.pathname.match(/^\/projects\/([^/]+)$/)?.[1] ?? null;
}
export function projectFromSearch(result: SearchResult): MapProject {
  return {
    id: result.id,
    name: result.name,
    projectType: result.project_type,
    consumerCategory: result.consumer_category,
    deliveryStage: result.statuses.delivery_stage ?? result.statuses.official_tracker_stage ?? null,
    lifecycleStage: result.lifecycle_stage,
    geometry: result.geometry,
  };
}
