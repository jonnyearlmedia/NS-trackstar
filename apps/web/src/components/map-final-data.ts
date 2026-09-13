import type { Feature, Point } from "geojson";
import type { Map } from "maplibre-gl";
import { classifyFeature, featureProject, isLocationUncertain, type CategoryTruth, type LifecycleTruth, type LocationTruth, type MapProject, type ProjectCollection, type ViewportBounds } from "./map-final-model";

const API_BASE = "/api/backend";

export async function loadViewportTruth(map: Map, window: string, signal: AbortSignal) {
  const bounds = map.getBounds();
  const viewport: ViewportBounds = { west: bounds.getWest(), south: bounds.getSouth(), east: bounds.getEast(), north: bounds.getNorth() };
  const params = new URLSearchParams({ west: String(viewport.west), south: String(viewport.south), east: String(viewport.east), north: String(viewport.north), window });
  const truth = new URLSearchParams({ west: String(viewport.west), south: String(viewport.south), east: String(viewport.east), north: String(viewport.north) });
  const [projectsResponse, locationResponse, lifecycleResponse, categoryResponse] = await Promise.all([
    fetch(`${API_BASE}/map/projects?${params}`, { signal }),
    fetch(`${API_BASE}/map/location-truth?${truth}`, { signal }),
    fetch(`${API_BASE}/map/lifecycle-truth?${truth}`, { signal }),
    fetch(`${API_BASE}/map/category-truth?${truth}`, { signal }),
  ]);
  if (!projectsResponse.ok) throw new Error(`Project API returned ${projectsResponse.status}`);
  const data = await projectsResponse.json() as ProjectCollection;
  const locations = locationResponse.ok ? await locationResponse.json() as LocationTruth[] : [];
  const lifecycles = lifecycleResponse.ok ? await lifecycleResponse.json() as LifecycleTruth[] : [];
  const categories = categoryResponse.ok ? await categoryResponse.json() as CategoryTruth[] : [];
  const locationById = new globalThis.Map(locations.map((row) => [row.id, row]));
  const lifecycleById = new globalThis.Map(lifecycles.map((row) => [row.id, row]));
  const categoryById = new globalThis.Map(categories.map((row) => [row.id, row]));
  const features = data.features.map((feature) => {
    const id = String(feature.properties?.id ?? "");
    const location = locationById.get(id);
    const lifecycle = lifecycleById.get(id);
    const category = categoryById.get(id);
    return { ...feature, properties: { ...(feature.properties ?? {}), consumer_category: category?.consumer_category ?? classifyFeature(feature), lifecycle_stage: lifecycle?.lifecycle_stage ?? "unknown", lifecycle_dimension: lifecycle?.matched_dimension ?? null, lifecycle_value: lifecycle?.matched_value ?? null, location_accuracy: location?.accuracy ?? null, geometry_confidence: location?.confidence ?? null, location_uncertain: isLocationUncertain(location?.accuracy, location?.confidence) } } as Feature;
  });
  const projects = features.map(featureProject).filter((project): project is MapProject => project !== null);
  const points = features.filter((feature): feature is Feature<Point> => feature.geometry?.type === "Point");
  return { viewport, data, features, projects, points };
}
