import type { Feature, FeatureCollection, Geometry } from "geojson";

export type TimeWindow = "today" | "week" | "upcoming" | "all";
export type ConsumerCategory = "all" | "development" | "roads" | "utilities" | "places";
export type LifecycleStage = "proposed" | "review" | "approved" | "construction" | "completed" | "inactive" | "unknown";
export type LifecycleFilter = LifecycleStage | "current" | "all";
export type UserLocation = { longitude: number; latitude: number; accuracy?: number };
export type ViewportBounds = { west: number; south: number; east: number; north: number };

export type MapProject = {
  id: string;
  name: string;
  projectType: string;
  consumerCategory: Exclude<ConsumerCategory, "all">;
  deliveryStage: string | null;
  lifecycleStage: LifecycleStage;
  lifecycleEvidence?: { dimension: string | null; value: string | null };
  geometry: Geometry | null;
  priority?: number;
  sourceCount?: number;
  lastActivityAt?: string | null;
  locationAccuracy?: string | null;
  locationConfidence?: number | null;
  locationUncertain?: boolean;
};

export type MapCoverage = { visibleMapped: number; mappedMatching: number; locationPending: number; totalMatching: number };
export type MapViewportState = {
  bounds: ViewportBounds;
  zoom: number;
  center: { lng: number; lat: number };
  projects: MapProject[];
  categoryCounts: Record<ConsumerCategory, number>;
  lifecycleCounts: Record<LifecycleFilter, number>;
};

export type ProjectCollection = FeatureCollection & { metadata?: { mapped_matching?: number; location_pending?: number; total_matching?: number } };
export type LocationTruth = { id: string; accuracy: string | null; accuracy_meters: number | null; confidence: number | null };
export type LifecycleTruth = { id: string; lifecycle_stage: LifecycleStage; matched_dimension: string | null; matched_value: string | null };
export type CategoryTruth = { id: string; consumer_category: Exclude<ConsumerCategory, "all">; category_basis: string; category_evidence: string | null };

export const NAPA_SOLANO_BOUNDS: [[number, number], [number, number]] = [[-122.72, 37.95], [-121.54, 38.88]];
export const LAST_VIEWPORT_KEY = "trackstar:last-viewport:v2";

const ROAD_WORDS = [" road", "road ", "street", "avenue", "boulevard", "highway", "route", "sr-", "bridge", "interchange", "intersection", "pavement", "paving", "sidewalk", "bicycle", "bike ", "pedestrian", "traffic", "transit", "corridor"];
const UTILITY_WORDS = ["water", "sewer", "stormwater", "storm water", "drainage", "storm drain", "flood", "pump station", "pipeline", "reservoir", "wastewater", "recycled water", "treatment plant", "well ", " well", "levee"];
const PLACE_WORDS = ["park", "trail", "school", "library", "civic", "community center", "recreation", "playground", "fire station", "police station", "city hall", "facility", "facilities"];

export function emptyCollection(): FeatureCollection { return { type: "FeatureCollection", features: [] }; }
function includesAny(value: string, words: string[]) { return words.some((word) => value.includes(word)); }
function isConsumerCategory(value: unknown): value is Exclude<ConsumerCategory, "all"> { return value === "development" || value === "roads" || value === "utilities" || value === "places"; }

export function classifyFeature(feature: Feature): Exclude<ConsumerCategory, "all"> {
  const existing = feature.properties?.consumer_category;
  if (isConsumerCategory(existing)) return existing;
  const type = String(feature.properties?.project_type ?? "");
  const name = ` ${String(feature.properties?.name ?? "").toLowerCase()} `;
  if (type === "transportation_project") return "roads";
  if (type === "water_infrastructure") return "utilities";
  if (type === "municipal_development") return "development";
  if (includesAny(name, UTILITY_WORDS)) return "utilities";
  if (includesAny(name, ROAD_WORDS)) return "roads";
  if (includesAny(name, PLACE_WORDS)) return "places";
  if (type === "public_works") return "places";
  return "development";
}

export function isLocationUncertain(accuracy?: string | null, confidence?: number | null) {
  if (confidence !== null && confidence !== undefined && confidence < 0.75) return true;
  return Boolean(accuracy && !["exact_source_geometry", "exact_parcel", "exact_address"].includes(accuracy));
}
export function changedRecently(value: unknown) {
  if (typeof value !== "string" || !value) return false;
  const timestamp = new Date(value).getTime();
  return Number.isFinite(timestamp) && Date.now() - timestamp <= 7 * 24 * 60 * 60 * 1000;
}
export function featureProject(feature: Feature): MapProject | null {
  if (!feature.geometry || !feature.properties?.id || !feature.properties?.name) return null;
  return {
    id: String(feature.properties.id), name: String(feature.properties.name), projectType: String(feature.properties.project_type ?? "project"), consumerCategory: classifyFeature(feature),
    deliveryStage: feature.properties.delivery_stage ? String(feature.properties.delivery_stage) : null, lifecycleStage: (feature.properties.lifecycle_stage as LifecycleStage | undefined) ?? "unknown",
    lifecycleEvidence: { dimension: feature.properties.lifecycle_dimension ? String(feature.properties.lifecycle_dimension) : null, value: feature.properties.lifecycle_value ? String(feature.properties.lifecycle_value) : null }, geometry: feature.geometry,
    priority: Number(feature.properties.display_priority ?? 0), sourceCount: Number(feature.properties.source_count ?? 0), lastActivityAt: feature.properties.last_activity_at ? String(feature.properties.last_activity_at) : null,
    locationAccuracy: feature.properties.location_accuracy ? String(feature.properties.location_accuracy) : null, locationConfidence: feature.properties.geometry_confidence === null || feature.properties.geometry_confidence === undefined ? null : Number(feature.properties.geometry_confidence), locationUncertain: Boolean(feature.properties.location_uncertain),
  };
}
export function minimumPriorityForZoom(zoom: number) { if (zoom < 8.5) return 0.13; if (zoom < 9.5) return 0.08; if (zoom < 10.5) return 0.035; return 0; }
export function categoryCounts(projects: MapProject[]): Record<ConsumerCategory, number> {
  const counts: Record<ConsumerCategory, number> = { all: projects.length, development: 0, roads: 0, utilities: 0, places: 0 };
  for (const project of projects) counts[project.consumerCategory] += 1;
  return counts;
}
export function lifecycleCounts(projects: MapProject[]): Record<LifecycleFilter, number> {
  const counts: Record<LifecycleFilter, number> = { all: projects.length, current: projects.filter((p) => !["completed", "inactive"].includes(p.lifecycleStage)).length, proposed: 0, review: 0, approved: 0, construction: 0, completed: 0, inactive: 0, unknown: 0 };
  for (const project of projects) counts[project.lifecycleStage] += 1;
  return counts;
}
export function userLocationFeature(userLocation?: UserLocation | null): FeatureCollection {
  if (!userLocation) return emptyCollection();
  return { type: "FeatureCollection", features: [{ type: "Feature", geometry: { type: "Point", coordinates: [userLocation.longitude, userLocation.latitude] }, properties: { accuracy: userLocation.accuracy ?? null } }] };
}
export function coverageMask(): FeatureCollection {
  const [[west, south], [east, north]] = NAPA_SOLANO_BOUNDS;
  return { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [[[-180,-85],[180,-85],[180,85],[-180,85],[-180,-85]],[[west,south],[west,north],[east,north],[east,south],[west,south]]] } }] };
}
export function coverageEdge(): FeatureCollection {
  const [[west, south], [east, north]] = NAPA_SOLANO_BOUNDS;
  return { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [[[west,south],[east,south],[east,north],[west,north],[west,south]]] } }] };
}
export function readSavedViewport(): { center: [number, number]; zoom: number } | null {
  if (typeof window === "undefined") return null;
  try { const raw = window.localStorage.getItem(LAST_VIEWPORT_KEY); if (!raw) return null; const value = JSON.parse(raw) as { center?: [number, number]; zoom?: number }; if (!Array.isArray(value.center) || typeof value.zoom !== "number") return null; return { center: value.center, zoom: Math.max(7.5, Math.min(16, value.zoom)) }; } catch { return null; }
}
