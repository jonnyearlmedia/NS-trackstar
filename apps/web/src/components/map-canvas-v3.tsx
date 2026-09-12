"use client";

import type { Feature, FeatureCollection, Geometry, Point } from "geojson";
import { useEffect, useRef, useState } from "react";

export type TimeWindow = "today" | "week" | "upcoming" | "all";
export type ConsumerCategory = "all" | "development" | "roads" | "utilities" | "places";
export type LifecycleStage = "review" | "approved" | "construction" | "completed" | "inactive" | "unknown";
export type LifecycleFilter = LifecycleStage | "all";

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

export type MapCoverage = {
  visibleMapped: number;
  mappedMatching: number;
  locationPending: number;
  totalMatching: number;
};

export type ViewportBounds = {
  west: number;
  south: number;
  east: number;
  north: number;
};

export type MapViewportState = {
  bounds: ViewportBounds;
  zoom: number;
  center: { lng: number; lat: number };
  projects: MapProject[];
  categoryCounts: Record<ConsumerCategory, number>;
  lifecycleCounts: Record<LifecycleFilter, number>;
};

type MapCanvasProps = {
  onSelectProject: (project: MapProject) => void;
  onCoverageChange?: (coverage: MapCoverage) => void;
  onViewportChange?: (viewport: MapViewportState) => void;
  onUserInteraction?: () => void;
  selectedProject: MapProject | null;
  timeWindow: TimeWindow;
  category: ConsumerCategory;
  lifecycle: LifecycleFilter;
  resetNonce: number;
  locateNonce: number;
  briefingActive?: boolean;
  restoreBounds?: ViewportBounds | null;
  restoreNonce?: number;
};

type ProjectCollection = FeatureCollection & {
  metadata?: {
    mapped_matching?: number;
    location_pending?: number;
    total_matching?: number;
  };
};

type LocationTruth = {
  id: string;
  accuracy: string | null;
  accuracy_meters: number | null;
  confidence: number | null;
};

type LifecycleTruth = {
  id: string;
  lifecycle_stage: LifecycleStage;
  matched_dimension: string | null;
  matched_value: string | null;
};

type CategoryTruth = {
  id: string;
  consumer_category: Exclude<ConsumerCategory, "all">;
  category_basis: string;
  category_evidence: string | null;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const NAPA_SOLANO_BOUNDS: [[number, number], [number, number]] = [
  [-122.72, 37.95],
  [-121.54, 38.88],
];
const PROJECT_SOURCE = "trackstar-v3-shapes";
const POINT_SOURCE = "trackstar-v3-points";
const SELECTED_SOURCE = "trackstar-v3-selected";
const MAJOR_REVIEW_PRIORITY = 0.4;

const ROAD_WORDS = [
  " road", "road ", "street", "avenue", "boulevard", "highway", "route", "sr-", "sr ",
  "bridge", "overcrossing", "interchange", "intersection", "pavement", "paving", "sidewalk",
  "bicycle", "bike ", "pedestrian", "traffic", "transit", "corridor",
];
const UTILITY_WORDS = [
  "water", "sewer", "stormwater", "storm water", "drainage", "storm drain", "flood", "pump station",
  "pipeline", "water main", "sewer main", "reservoir", "wastewater", "recycled water", "treatment plant",
  "well ", " well", "levee",
];
const PLACE_WORDS = [
  "park", "trail", "school", "library", "civic", "community center", "recreation", "playground",
  "fire station", "police station", "city hall", "facility", "facilities",
];

function emptyCollection(): FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}

function includesAny(value: string, words: string[]) {
  return words.some((word) => value.includes(word));
}

function isConsumerCategory(value: unknown): value is Exclude<ConsumerCategory, "all"> {
  return value === "development" || value === "roads" || value === "utilities" || value === "places";
}

function classifyFeature(feature: Feature): Exclude<ConsumerCategory, "all"> {
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

function isLocationUncertain(accuracy?: string | null, confidence?: number | null) {
  if (confidence !== null && confidence !== undefined && confidence < 0.75) return true;
  return Boolean(accuracy && !["exact_source_geometry", "exact_parcel", "exact_address"].includes(accuracy));
}

function changedRecently(value: unknown) {
  if (typeof value !== "string" || !value) return false;
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return false;
  return Date.now() - timestamp <= 7 * 24 * 60 * 60 * 1000;
}

function featureProject(feature: Feature): MapProject | null {
  if (!feature.geometry || !feature.properties?.id || !feature.properties?.name) return null;
  return {
    id: String(feature.properties.id),
    name: String(feature.properties.name),
    projectType: String(feature.properties.project_type ?? "project"),
    consumerCategory: classifyFeature(feature),
    deliveryStage: feature.properties.delivery_stage ? String(feature.properties.delivery_stage) : null,
    lifecycleStage: (feature.properties.lifecycle_stage as LifecycleStage | undefined) ?? "unknown",
    lifecycleEvidence: {
      dimension: feature.properties.lifecycle_dimension ? String(feature.properties.lifecycle_dimension) : null,
      value: feature.properties.lifecycle_value ? String(feature.properties.lifecycle_value) : null,
    },
    geometry: feature.geometry,
    priority: Number(feature.properties.display_priority ?? 0),
    sourceCount: Number(feature.properties.source_count ?? 0),
    lastActivityAt: feature.properties.last_activity_at ? String(feature.properties.last_activity_at) : null,
    locationAccuracy: feature.properties.location_accuracy ? String(feature.properties.location_accuracy) : null,
    locationConfidence:
      feature.properties.geometry_confidence === null || feature.properties.geometry_confidence === undefined
        ? null
        : Number(feature.properties.geometry_confidence),
    locationUncertain: Boolean(feature.properties.location_uncertain),
  };
}

function minimumPriorityForZoom(zoom: number) {
  if (zoom < 8.5) return 0.13;
  if (zoom < 9.5) return 0.08;
  if (zoom < 10.5) return 0.035;
  return 0;
}

function visitCoordinates(value: unknown, visit: (coordinate: [number, number]) => void) {
  if (!Array.isArray(value) || value.length === 0) return;
  if (value.length >= 2 && typeof value[0] === "number" && typeof value[1] === "number") {
    visit([value[0], value[1]]);
    return;
  }
  for (const child of value) visitCoordinates(child, visit);
}

function geometryBounds(geometry: Geometry) {
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  if ("coordinates" in geometry) {
    visitCoordinates(geometry.coordinates, ([lng, lat]) => {
      west = Math.min(west, lng);
      south = Math.min(south, lat);
      east = Math.max(east, lng);
      north = Math.max(north, lat);
    });
  }
  return Number.isFinite(west) ? [[west, south], [east, north]] as [[number, number], [number, number]] : null;
}

function categoryCounts(projects: MapProject[]): Record<ConsumerCategory, number> {
  const counts: Record<ConsumerCategory, number> = {
    all: projects.length,
    development: 0,
    roads: 0,
    utilities: 0,
    places: 0,
  };
  for (const project of projects) counts[project.consumerCategory] += 1;
  return counts;
}

function lifecycleCounts(projects: MapProject[]): Record<LifecycleFilter, number> {
  const counts: Record<LifecycleFilter, number> = {
    all: projects.length,
    review: 0,
    approved: 0,
    construction: 0,
    completed: 0,
    inactive: 0,
    unknown: 0,
  };
  for (const project of projects) counts[project.lifecycleStage] += 1;
  return counts;
}

function categoryColorExpression() {
  return [
    "match", ["get", "consumer_category"],
    "development", "#d9ff61",
    "roads", "#ffb45f",
    "utilities", "#59edc5",
    "places", "#67d7ff",
    "#d9ff61",
  ] as import("maplibre-gl").ExpressionSpecification;
}

export function MapCanvasV3({
  onSelectProject,
  onCoverageChange,
  onViewportChange,
  onUserInteraction,
  selectedProject,
  timeWindow,
  category,
  lifecycle,
  resetNonce,
  locateNonce,
  briefingActive = false,
  restoreBounds = null,
  restoreNonce = 0,
}: MapCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<import("maplibre-gl").Map | null>(null);
  const geolocateRef = useRef<import("maplibre-gl").GeolocateControl | null>(null);
  const refreshRef = useRef<(() => void) | null>(null);
  const selectedRef = useRef(selectedProject);
  const timeRef = useRef(timeWindow);
  const categoryRef = useRef(category);
  const lifecycleRef = useRef(lifecycle);
  const onSelectRef = useRef(onSelectProject);
  const onCoverageRef = useRef(onCoverageChange);
  const onViewportRef = useRef(onViewportChange);
  const onInteractionRef = useRef(onUserInteraction);
  const briefingRef = useRef(briefingActive);
  const [mapState, setMapState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => { selectedRef.current = selectedProject; }, [selectedProject]);
  useEffect(() => { timeRef.current = timeWindow; refreshRef.current?.(); }, [timeWindow]);
  useEffect(() => { categoryRef.current = category; refreshRef.current?.(); }, [category]);
  useEffect(() => { lifecycleRef.current = lifecycle; refreshRef.current?.(); }, [lifecycle]);
  useEffect(() => { onSelectRef.current = onSelectProject; }, [onSelectProject]);
  useEffect(() => { onCoverageRef.current = onCoverageChange; }, [onCoverageChange]);
  useEffect(() => { onViewportRef.current = onViewportChange; }, [onViewportChange]);
  useEffect(() => { onInteractionRef.current = onUserInteraction; }, [onUserInteraction]);
  useEffect(() => { briefingRef.current = briefingActive; }, [briefingActive]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const source = map.getSource(SELECTED_SOURCE) as import("maplibre-gl").GeoJSONSource | undefined;
    if (!source) return;

    if (!selectedProject?.geometry) {
      source.setData(emptyCollection());
      return;
    }

    source.setData({
      type: "Feature",
      geometry: selectedProject.geometry,
      properties: {
        id: selectedProject.id,
        name: selectedProject.name,
        consumer_category: selectedProject.consumerCategory,
        lifecycle_stage: selectedProject.lifecycleStage,
        location_uncertain: Boolean(selectedProject.locationUncertain),
      },
    });

    const pointZoom = briefingRef.current ? Math.max(map.getZoom(), 13.2) : Math.max(map.getZoom(), 14);
    const duration = briefingRef.current ? 900 : 650;
    if (selectedProject.geometry.type === "Point") {
      map.easeTo({ center: selectedProject.geometry.coordinates as [number, number], zoom: pointZoom, duration, essential: true });
      return;
    }
    const bounds = geometryBounds(selectedProject.geometry);
    if (bounds) {
      map.fitBounds(bounds, {
        padding: briefingRef.current
          ? { top: 105, right: 44, bottom: 210, left: 44 }
          : { top: 105, right: 42, bottom: 250, left: 42 },
        maxZoom: briefingRef.current ? 14.2 : 15,
        duration,
        essential: true,
      });
    }
  }, [selectedProject]);

  useEffect(() => {
    if (resetNonce === 0) return;
    const map = mapRef.current;
    if (!map) return;
    map.fitBounds(NAPA_SOLANO_BOUNDS, { padding: { top: 105, right: 18, bottom: 130, left: 18 }, duration: 750, essential: true });
  }, [resetNonce]);

  useEffect(() => {
    if (locateNonce === 0) return;
    geolocateRef.current?.trigger();
  }, [locateNonce]);

  useEffect(() => {
    if (restoreNonce === 0 || !restoreBounds) return;
    const map = mapRef.current;
    if (!map) return;
    map.fitBounds(
      [[restoreBounds.west, restoreBounds.south], [restoreBounds.east, restoreBounds.north]],
      { padding: { top: 105, right: 18, bottom: 130, left: 18 }, duration: 750, essential: true },
    );
  }, [restoreBounds, restoreNonce]);

  useEffect(() => {
    let disposed = false;
    let refreshAbort: AbortController | null = null;
    let moveTimer: number | undefined;

    async function mount() {
      if (!containerRef.current) return;
      const maplibregl = await import("maplibre-gl");
      if (disposed || !containerRef.current) return;
      maplibregl.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

      const map = new maplibregl.Map({
        container: containerRef.current,
        style: "https://tiles.openfreemap.org/styles/liberty",
        bounds: NAPA_SOLANO_BOUNDS,
        fitBoundsOptions: { padding: { top: 105, right: 18, bottom: 130, left: 18 } },
        attributionControl: false,
      });
      mapRef.current = map;

      map.on("error", () => {
        if (!map.isStyleLoaded()) setMapState("error");
      });

      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
      const geolocate = new maplibregl.GeolocateControl({
        positionOptions: { enableHighAccuracy: true },
        trackUserLocation: false,
        showUserLocation: true,
        fitBoundsOptions: { maxZoom: 14 },
      });
      geolocateRef.current = geolocate;
      map.addControl(geolocate, "bottom-right");
      map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-left");

      async function refresh() {
        if (!map.isStyleLoaded()) return;
        refreshAbort?.abort();
        refreshAbort = new AbortController();
        const bounds = map.getBounds();
        const viewport: ViewportBounds = {
          west: bounds.getWest(),
          south: bounds.getSouth(),
          east: bounds.getEast(),
          north: bounds.getNorth(),
        };
        const params = new URLSearchParams({
          west: String(viewport.west),
          south: String(viewport.south),
          east: String(viewport.east),
          north: String(viewport.north),
          window: timeRef.current,
        });
        const truthParams = new URLSearchParams({
          west: String(viewport.west),
          south: String(viewport.south),
          east: String(viewport.east),
          north: String(viewport.north),
        });

        try {
          const [response, truthResponse, lifecycleResponse, categoryResponse] = await Promise.all([
            fetch(`${API_BASE}/map/projects?${params}`, { signal: refreshAbort.signal }),
            fetch(`${API_BASE}/map/location-truth?${truthParams}`, { signal: refreshAbort.signal }),
            fetch(`${API_BASE}/map/lifecycle-truth?${truthParams}`, { signal: refreshAbort.signal }),
            fetch(`${API_BASE}/map/category-truth?${truthParams}`, { signal: refreshAbort.signal }),
          ]);
          if (!response.ok) throw new Error(`Project API returned ${response.status}`);
          const data = await response.json() as ProjectCollection;
          const truthRows = truthResponse.ok ? await truthResponse.json() as LocationTruth[] : [];
          const lifecycleRows = lifecycleResponse.ok ? await lifecycleResponse.json() as LifecycleTruth[] : [];
          const categoryRows = categoryResponse.ok ? await categoryResponse.json() as CategoryTruth[] : [];
          const truthById = new Map(truthRows.map((row) => [row.id, row]));
          const lifecycleById = new Map(lifecycleRows.map((row) => [row.id, row]));
          const categoryById = new Map(categoryRows.map((row) => [row.id, row]));

          const enriched = data.features.map((feature) => {
            const id = feature.properties?.id ? String(feature.properties.id) : "";
            const truth = truthById.get(id);
            const lifecycleTruth = lifecycleById.get(id);
            const categoryTruth = categoryById.get(id);
            const consumerCategory = categoryTruth?.consumer_category ?? classifyFeature(feature);
            return {
              ...feature,
              properties: {
                ...(feature.properties ?? {}),
                consumer_category: consumerCategory,
                category_basis: categoryTruth?.category_basis ?? "fallback",
                category_evidence: categoryTruth?.category_evidence ?? null,
                lifecycle_stage: lifecycleTruth?.lifecycle_stage ?? "unknown",
                lifecycle_dimension: lifecycleTruth?.matched_dimension ?? null,
                lifecycle_value: lifecycleTruth?.matched_value ?? null,
                location_accuracy: truth?.accuracy ?? null,
                geometry_confidence: truth?.confidence ?? null,
                geometry_accuracy_meters: truth?.accuracy_meters ?? null,
                location_uncertain: isLocationUncertain(truth?.accuracy, truth?.confidence),
                changed_recently: changedRecently(feature.properties?.last_activity_at),
              },
            } as Feature;
          });

          const allConsumerFeatures = enriched.filter((feature) => {
            if (feature.properties?.project_type !== "environmental_review") return true;
            return Number(feature.properties?.display_priority ?? 0) >= MAJOR_REVIEW_PRIORITY;
          });
          const allProjects = allConsumerFeatures
            .map(featureProject)
            .filter((project): project is MapProject => project !== null);
          const categoryProjects = categoryRef.current === "all"
            ? allProjects
            : allProjects.filter((project) => project.consumerCategory === categoryRef.current);
          const filteredProjects = lifecycleRef.current === "all"
            ? categoryProjects
            : categoryProjects.filter((project) => project.lifecycleStage === lifecycleRef.current);
          const ids = new Set(filteredProjects.map((project) => project.id));
          const filteredFeatures = allConsumerFeatures.filter((feature) => ids.has(String(feature.properties?.id ?? "")));

          const floor = categoryRef.current === "all" && lifecycleRef.current === "all" ? minimumPriorityForZoom(map.getZoom()) : 0;
          const displayFeatures = filteredFeatures.filter((feature) => Number(feature.properties?.display_priority ?? 0) >= floor);
          const pointFeatures = displayFeatures.filter((feature): feature is Feature<Point> => feature.geometry?.type === "Point");
          const shapeFeatures = displayFeatures.filter((feature) => feature.geometry?.type !== "Point");

          (map.getSource(PROJECT_SOURCE) as import("maplibre-gl").GeoJSONSource)?.setData({ type: "FeatureCollection", features: shapeFeatures });
          (map.getSource(POINT_SOURCE) as import("maplibre-gl").GeoJSONSource)?.setData({ type: "FeatureCollection", features: pointFeatures });

          const metadata = data.metadata;
          onCoverageRef.current?.({
            visibleMapped: filteredProjects.length,
            mappedMatching: Number(metadata?.mapped_matching ?? filteredProjects.length),
            locationPending: Number(metadata?.location_pending ?? 0),
            totalMatching: Number(metadata?.total_matching ?? filteredProjects.length),
          });

          const center = map.getCenter();
          onViewportRef.current?.({
            bounds: viewport,
            zoom: map.getZoom(),
            center: { lng: center.lng, lat: center.lat },
            projects: filteredProjects,
            categoryCounts: categoryCounts(allProjects),
            lifecycleCounts: lifecycleCounts(categoryProjects),
          });
        } catch (error) {
          if (error instanceof DOMException && error.name === "AbortError") return;
          console.error("Failed to refresh Trackstar map", error);
        }
      }

      refreshRef.current = () => void refresh();

      map.on("load", () => {
        setMapState("ready");
        map.addSource(PROJECT_SOURCE, { type: "geojson", data: emptyCollection() });
        map.addSource(POINT_SOURCE, { type: "geojson", data: emptyCollection(), cluster: true, clusterMaxZoom: 13, clusterRadius: 44 });
        map.addSource(SELECTED_SOURCE, { type: "geojson", data: emptyCollection() });

        const categoryColor = categoryColorExpression();
        const exactFilter = ["!=", ["get", "location_uncertain"], true] as import("maplibre-gl").ExpressionSpecification;
        const uncertainFilter = ["==", ["get", "location_uncertain"], true] as import("maplibre-gl").ExpressionSpecification;
        const unclusteredFilter = ["!", ["has", "point_count"]] as import("maplibre-gl").ExpressionSpecification;

        map.addLayer({
          id: "v3-fill",
          type: "fill",
          source: PROJECT_SOURCE,
          filter: ["all", ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]], exactFilter],
          paint: { "fill-color": categoryColor, "fill-opacity": ["interpolate", ["linear"], ["zoom"], 7, 0.05, 11, 0.16, 15, 0.28] },
        });
        map.addLayer({
          id: "v3-fill-uncertain",
          type: "fill",
          source: PROJECT_SOURCE,
          filter: ["all", ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]], uncertainFilter],
          paint: { "fill-color": categoryColor, "fill-opacity": 0.07 },
        });
        map.addLayer({
          id: "v3-line",
          type: "line",
          source: PROJECT_SOURCE,
          filter: exactFilter,
          paint: { "line-color": categoryColor, "line-width": ["interpolate", ["linear"], ["zoom"], 7, 1, 13, 2.4, 17, 4], "line-opacity": 0.72 },
        });
        map.addLayer({
          id: "v3-line-uncertain",
          type: "line",
          source: PROJECT_SOURCE,
          filter: uncertainFilter,
          paint: { "line-color": categoryColor, "line-width": 2, "line-opacity": 0.58, "line-dasharray": [2, 2] },
        });
        map.addLayer({
          id: "v3-clusters",
          type: "circle",
          source: POINT_SOURCE,
          filter: ["has", "point_count"],
          paint: {
            "circle-color": "#111b17",
            "circle-radius": ["step", ["get", "point_count"], 14, 10, 18, 50, 23, 200, 28],
            "circle-stroke-color": "#d9ff61",
            "circle-stroke-width": 1.6,
            "circle-opacity": 0.88,
          },
        });
        map.addLayer({
          id: "v3-cluster-count",
          type: "symbol",
          source: POINT_SOURCE,
          filter: ["has", "point_count"],
          layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 10, "text-font": ["Noto Sans Regular"] },
          paint: { "text-color": "#f5ffd0" },
        });
        map.addLayer({
          id: "v3-points",
          type: "circle",
          source: POINT_SOURCE,
          filter: ["all", unclusteredFilter, exactFilter],
          paint: {
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 4, 12, 5.5, 15, 7.5],
            "circle-color": categoryColor,
            "circle-opacity": 0.9,
            "circle-stroke-color": "#101416",
            "circle-stroke-width": 1.4,
          },
        });
        map.addLayer({
          id: "v3-points-uncertain",
          type: "circle",
          source: POINT_SOURCE,
          filter: ["all", unclusteredFilter, uncertainFilter],
          paint: {
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 4, 12, 5.5, 15, 7.5],
            "circle-color": categoryColor,
            "circle-opacity": 0.62,
            "circle-stroke-color": "#f5faf7",
            "circle-stroke-width": 1.3,
          },
        });
        map.addLayer({
          id: "v3-labels",
          type: "symbol",
          source: POINT_SOURCE,
          minzoom: 11.8,
          filter: unclusteredFilter,
          layout: {
            "text-field": ["get", "name"],
            "text-size": 10,
            "text-font": ["Noto Sans Regular"],
            "text-offset": [0, 1.15],
            "text-anchor": "top",
            "text-max-width": 12,
            "text-allow-overlap": false,
          },
          paint: { "text-color": "#eef5f0", "text-halo-color": "rgba(5,11,8,.92)", "text-halo-width": 1.4 },
        });

        map.addLayer({ id: "v3-selected-fill", type: "fill", source: SELECTED_SOURCE, filter: ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]], paint: { "fill-color": "#d9ff61", "fill-opacity": 0.34 } });
        map.addLayer({ id: "v3-selected-line", type: "line", source: SELECTED_SOURCE, paint: { "line-color": "#f5ffc9", "line-width": 3.5, "line-opacity": 1 } });
        map.addLayer({ id: "v3-selected-point", type: "circle", source: SELECTED_SOURCE, filter: ["==", ["geometry-type"], "Point"], paint: { "circle-radius": 9, "circle-color": "#d9ff61", "circle-stroke-color": "#f7ffd7", "circle-stroke-width": 3 } });

        for (const layer of ["v3-fill", "v3-fill-uncertain", "v3-line", "v3-line-uncertain", "v3-points", "v3-points-uncertain"]) {
          map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
          map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; });
          map.on("click", layer, (event) => {
            const project = event.features?.[0] ? featureProject(event.features[0] as Feature) : null;
            if (project) onSelectRef.current(project);
          });
        }

        map.on("mouseenter", "v3-clusters", () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", "v3-clusters", () => { map.getCanvas().style.cursor = ""; });
        map.on("click", "v3-clusters", async (event) => {
          const feature = event.features?.[0];
          const clusterId = Number(feature?.properties?.cluster_id);
          if (!Number.isFinite(clusterId) || feature?.geometry.type !== "Point") return;
          const source = map.getSource(POINT_SOURCE) as import("maplibre-gl").GeoJSONSource;
          const zoom = await source.getClusterExpansionZoom(clusterId);
          map.easeTo({ center: feature.geometry.coordinates as [number, number], zoom, duration: 550, essential: true });
        });

        void refresh();
      });

      map.on("dragstart", () => onInteractionRef.current?.());
      map.on("zoomstart", (event) => {
        if ((event as unknown as { originalEvent?: unknown }).originalEvent) onInteractionRef.current?.();
      });
      map.on("moveend", () => {
        if (selectedRef.current || briefingRef.current) return;
        if (moveTimer !== undefined) window.clearTimeout(moveTimer);
        moveTimer = window.setTimeout(() => refreshRef.current?.(), 180);
      });
    }

    void mount();
    return () => {
      disposed = true;
      if (moveTimer !== undefined) window.clearTimeout(moveTimer);
      refreshAbort?.abort();
      refreshRef.current = null;
      geolocateRef.current = null;
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, []);

  return (
    <>
      <div className="mapCanvas" ref={containerRef} />
      <style jsx global>{`
        .maplibregl-ctrl-geolocate { display: none !important; }
      `}</style>
      {mapState !== "ready" ? (
        <div className={mapState === "error" ? "mapStatus error" : "mapStatus"} role="status">
          {mapState === "error" ? <><strong>Map could not load</strong><button onClick={() => window.location.reload()} type="button">Retry</button></> : "Loading what’s happening around you…"}
        </div>
      ) : null}
    </>
  );
}
