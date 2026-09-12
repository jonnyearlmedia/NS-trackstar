"use client";

import type { Feature, FeatureCollection, Geometry, Point } from "geojson";
import { useEffect, useRef, useState } from "react";

export type TimeWindow = "today" | "week" | "upcoming" | "all";
export type MapDisplayMode = "projects" | "density" | "perspective";

export type MapProject = {
  id: string;
  name: string;
  projectType: string;
  deliveryStage: string | null;
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

type MapCanvasProps = {
  onSelectProject: (project: MapProject) => void;
  onCoverageChange?: (coverage: MapCoverage) => void;
  onHighlightsChange?: (projects: MapProject[]) => void;
  selectedProject: MapProject | null;
  timeWindow: TimeWindow;
  projectType?: string | null;
  displayMode: MapDisplayMode;
  resetNonce: number;
  locateNonce: number;
  briefingActive?: boolean;
};

type MapLibreModule = typeof import("maplibre-gl");
type ProjectCollection = FeatureCollection & {
  metadata?: {
    visible_mapped?: number;
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
  method: string | null;
  source: string | null;
};

const NAPA_SOLANO_BOUNDS: [[number, number], [number, number]] = [
  [-122.72, 37.95],
  [-121.54, 38.88],
];
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const PROJECT_SOURCE = "trackstar-project-shapes";
const POINT_SOURCE = "trackstar-project-points";
const DENSITY_SOURCE = "trackstar-density-points";
const SELECTED_SOURCE = "trackstar-selected-project";
const MAJOR_REVIEW_PRIORITY = 0.4;
const PROJECT_LAYERS = [
  "projects-fill",
  "projects-fill-uncertain",
  "projects-line",
  "projects-line-uncertain",
  "projects-points",
  "projects-points-uncertain",
  "uncertain-point-halo",
  "recent-point-glow",
  "recent-line-glow",
] as const;

function emptyCollection(): FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}

function visitCoordinates(value: unknown, visit: (coordinate: [number, number]) => void) {
  if (!Array.isArray(value) || value.length === 0) return;
  if (value.length >= 2 && typeof value[0] === "number" && typeof value[1] === "number") {
    visit([value[0], value[1]]);
    return;
  }
  for (const child of value) visitCoordinates(child, visit);
}

function isLocationUncertain(accuracy?: string | null, confidence?: number | null) {
  if (confidence !== null && confidence !== undefined && confidence < 0.75) return true;
  return Boolean(
    accuracy && !["exact_source_geometry", "exact_parcel", "exact_address"].includes(accuracy),
  );
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
    deliveryStage: feature.properties.delivery_stage ? String(feature.properties.delivery_stage) : null,
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
  if (zoom < 9) return 0.18;
  if (zoom < 10.5) return 0.1;
  return 0;
}

function projectBearing(projectId: string) {
  let value = 0;
  for (const character of projectId.slice(0, 12)) value += character.charCodeAt(0);
  return (value % 34) - 17;
}

function frameFeature(
  map: import("maplibre-gl").Map,
  geometry: Geometry,
  maplibregl: MapLibreModule,
  perspective: boolean,
  briefing: boolean,
  projectId: string,
) {
  const narrow = map.getContainer().clientWidth < 700;
  const cinematic = perspective || briefing;
  const bearing = cinematic ? projectBearing(projectId) : -4;
  const duration = briefing ? 1550 : 1050;
  if (geometry.type === "Point") {
    map.flyTo({
      center: geometry.coordinates as [number, number],
      zoom: narrow ? 15 : 15.7,
      pitch: cinematic ? 56 : 32,
      bearing,
      duration,
      essential: true,
    });
    return;
  }
  if (geometry.type === "GeometryCollection") return;
  const bounds = new maplibregl.LngLatBounds();
  visitCoordinates(geometry.coordinates, (coordinate) => bounds.extend(coordinate));
  if (bounds.isEmpty()) return;
  map.fitBounds(bounds, {
    padding: narrow
      ? { top: 145, right: 26, bottom: 260, left: 26 }
      : { top: 90, right: 100, bottom: 150, left: 100 },
    maxZoom: 15.7,
    pitch: cinematic ? 54 : 30,
    bearing,
    duration: briefing ? 1650 : 1100,
    essential: true,
  });
}

export function MapCanvas({
  onSelectProject,
  onCoverageChange,
  onHighlightsChange,
  selectedProject,
  timeWindow,
  projectType,
  displayMode,
  resetNonce,
  locateNonce,
  briefingActive = false,
}: MapCanvasProps) {
  const [mapState, setMapState] = useState<"loading" | "ready" | "error">("loading");
  const containerRef = useRef<HTMLDivElement | null>(null);
  const onSelectRef = useRef(onSelectProject);
  const onCoverageRef = useRef(onCoverageChange);
  const onHighlightsRef = useRef(onHighlightsChange);
  const timeWindowRef = useRef(timeWindow);
  const projectTypeRef = useRef(projectType);
  const selectedProjectRef = useRef(selectedProject);
  const displayModeRef = useRef(displayMode);
  const briefingActiveRef = useRef(briefingActive);
  const refreshProjectsRef = useRef<(() => void) | null>(null);
  const focusProjectRef = useRef<((project: MapProject | null) => void) | null>(null);
  const applyDisplayModeRef = useRef<((mode: MapDisplayMode) => void) | null>(null);
  const resetRegionRef = useRef<(() => void) | null>(null);
  const locateRef = useRef<(() => void) | null>(null);

  useEffect(() => { onSelectRef.current = onSelectProject; }, [onSelectProject]);
  useEffect(() => { onCoverageRef.current = onCoverageChange; }, [onCoverageChange]);
  useEffect(() => { onHighlightsRef.current = onHighlightsChange; }, [onHighlightsChange]);
  useEffect(() => { timeWindowRef.current = timeWindow; refreshProjectsRef.current?.(); }, [timeWindow]);
  useEffect(() => { projectTypeRef.current = projectType; refreshProjectsRef.current?.(); }, [projectType]);
  useEffect(() => { selectedProjectRef.current = selectedProject; focusProjectRef.current?.(selectedProject); }, [selectedProject]);
  useEffect(() => { displayModeRef.current = displayMode; applyDisplayModeRef.current?.(displayMode); }, [displayMode]);
  useEffect(() => { briefingActiveRef.current = briefingActive; }, [briefingActive]);
  useEffect(() => { if (resetNonce > 0) resetRegionRef.current?.(); }, [resetNonce]);
  useEffect(() => { if (locateNonce > 0) locateRef.current?.(); }, [locateNonce]);

  useEffect(() => {
    let disposed = false;
    let map: import("maplibre-gl").Map | undefined;
    let refreshAbort: AbortController | undefined;
    let pulseFrame: number | undefined;
    let moveRefreshTimer: number | undefined;
    let ignoreMoveEndUntil = performance.now() + 1000;

    async function mount() {
      if (!containerRef.current) return;
      const maplibregl = await import("maplibre-gl");
      if (disposed || !containerRef.current) return;

      maplibregl.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");
      map = new maplibregl.Map({
        container: containerRef.current,
        style: "https://tiles.openfreemap.org/styles/liberty",
        bounds: NAPA_SOLANO_BOUNDS,
        fitBoundsOptions: { padding: { top: 120, right: 18, bottom: 145, left: 18 } },
        attributionControl: false,
      });

      map.on("error", () => {
        if (!map?.isStyleLoaded()) setMapState("error");
      });

      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
      const geolocate = new maplibregl.GeolocateControl({
        positionOptions: { enableHighAccuracy: true },
        trackUserLocation: false,
        showUserLocation: true,
        fitBoundsOptions: { maxZoom: 13.8 },
      });
      map.addControl(geolocate, "bottom-right");
      locateRef.current = () => geolocate.trigger();
      map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-left");

      const normalFillOpacity = [
        "interpolate", ["linear"], ["zoom"],
        7, ["interpolate", ["linear"], ["coalesce", ["get", "display_priority"], 0], 0, 0.025, 0.5, 0.12, 1, 0.22],
        11, ["interpolate", ["linear"], ["coalesce", ["get", "display_priority"], 0], 0, 0.08, 0.5, 0.2, 1, 0.32],
        15, 0.32,
      ] as import("maplibre-gl").ExpressionSpecification;
      const normalLineOpacity = [
        "interpolate", ["linear"], ["zoom"],
        7, ["interpolate", ["linear"], ["coalesce", ["get", "display_priority"], 0], 0, 0.12, 0.5, 0.45, 1, 0.78],
        13, 0.82,
      ] as import("maplibre-gl").ExpressionSpecification;
      const normalPointOpacity = [
        "interpolate", ["linear"], ["coalesce", ["get", "display_priority"], 0],
        0, 0.48, 0.25, 0.68, 0.55, 0.86, 1, 1,
      ] as import("maplibre-gl").ExpressionSpecification;

      function setContextOpacity(hasSelection: boolean) {
        if (!map) return;
        for (const layer of ["projects-fill", "projects-fill-uncertain"]) {
          if (map.getLayer(layer)) map.setPaintProperty(layer, "fill-opacity", hasSelection ? 0.025 : layer.endsWith("uncertain") ? 0.08 : normalFillOpacity);
        }
        for (const layer of ["projects-line", "projects-line-uncertain", "recent-line-glow"]) {
          if (map.getLayer(layer)) map.setPaintProperty(layer, "line-opacity", hasSelection ? 0.08 : layer === "recent-line-glow" ? 0.16 : normalLineOpacity);
        }
        for (const layer of ["projects-points", "projects-points-uncertain", "uncertain-point-halo", "recent-point-glow"]) {
          if (map.getLayer(layer)) map.setPaintProperty(layer, "circle-opacity", hasSelection ? 0.1 : layer.includes("halo") || layer.includes("glow") ? 0.18 : normalPointOpacity);
        }
        if (map.getLayer("project-clusters")) map.setPaintProperty("project-clusters", "circle-opacity", hasSelection ? 0.1 : 0.86);
        if (map.getLayer("project-cluster-count")) map.setPaintProperty("project-cluster-count", "text-opacity", hasSelection ? 0.13 : 1);
        if (map.getLayer("project-labels")) map.setPaintProperty("project-labels", "text-opacity", hasSelection ? 0.12 : 0.9);
      }

      function stopSelectionPulse() {
        if (pulseFrame !== undefined) cancelAnimationFrame(pulseFrame);
        pulseFrame = undefined;
      }

      function startSelectionPulse() {
        stopSelectionPulse();
        if (!map || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
        const startedAt = performance.now();
        const animate = (now: number) => {
          if (!map || disposed) return;
          const wave = (Math.sin((now - startedAt) / 430) + 1) / 2;
          if (map.getLayer("selected-point-glow")) {
            map.setPaintProperty("selected-point-glow", "circle-radius", 16 + wave * 10);
            map.setPaintProperty("selected-point-glow", "circle-opacity", 0.1 + wave * 0.2);
          }
          if (map.getLayer("selected-line-glow")) {
            map.setPaintProperty("selected-line-glow", "line-width", 8 + wave * 9);
            map.setPaintProperty("selected-line-glow", "line-opacity", 0.12 + wave * 0.18);
          }
          pulseFrame = requestAnimationFrame(animate);
        };
        pulseFrame = requestAnimationFrame(animate);
      }

      function applyDisplayMode(mode: MapDisplayMode) {
        if (!map || !map.isStyleLoaded()) return;
        const density = mode === "density";
        const perspective = mode === "perspective";
        const projectVisibility = density ? "none" : "visible";
        for (const layer of [...PROJECT_LAYERS, "project-clusters", "project-cluster-count", "project-labels"]) {
          if (map.getLayer(layer)) map.setLayoutProperty(layer, "visibility", projectVisibility);
        }
        if (map.getLayer("density-heat")) map.setLayoutProperty("density-heat", "visibility", density ? "visible" : "none");
        if (!selectedProjectRef.current) {
          map.easeTo({ pitch: perspective ? 52 : 0, bearing: perspective ? -10 : 0, duration: 600, essential: true });
        }
      }

      applyDisplayModeRef.current = applyDisplayMode;
      resetRegionRef.current = () => {
        if (!map) return;
        ignoreMoveEndUntil = performance.now() + 1100;
        map.fitBounds(NAPA_SOLANO_BOUNDS, {
          padding: { top: 120, right: 18, bottom: 145, left: 18 },
          pitch: displayModeRef.current === "perspective" ? 45 : 0,
          bearing: displayModeRef.current === "perspective" ? -9 : 0,
          duration: 850,
          essential: true,
        });
        window.setTimeout(() => refreshProjectsRef.current?.(), 900);
      };

      async function refreshProjects() {
        if (!map || !map.isStyleLoaded()) return;
        refreshAbort?.abort();
        refreshAbort = new AbortController();
        const bounds = map.getBounds();
        const viewport = {
          west: String(bounds.getWest()),
          south: String(bounds.getSouth()),
          east: String(bounds.getEast()),
          north: String(bounds.getNorth()),
        };
        const params = new URLSearchParams({ ...viewport, window: timeWindowRef.current });
        if (projectTypeRef.current) params.set("project_type", projectTypeRef.current);
        const truthParams = new URLSearchParams(viewport);

        try {
          const [response, truthResponse] = await Promise.all([
            fetch(`${API_BASE}/map/projects?${params}`, { signal: refreshAbort.signal }),
            fetch(`${API_BASE}/map/location-truth?${truthParams}`, { signal: refreshAbort.signal }),
          ]);
          if (!response.ok) throw new Error(`Project API returned ${response.status}`);
          const data = (await response.json()) as ProjectCollection;
          const truthRows = truthResponse.ok ? await truthResponse.json() as LocationTruth[] : [];
          const truthById = new Map(truthRows.map((row) => [row.id, row]));
          const enrichedFeatures = data.features.map((feature) => {
            const id = feature.properties?.id ? String(feature.properties.id) : "";
            const truth = truthById.get(id);
            const uncertain = isLocationUncertain(truth?.accuracy, truth?.confidence);
            return {
              ...feature,
              properties: {
                ...(feature.properties ?? {}),
                location_accuracy: truth?.accuracy ?? null,
                geometry_confidence: truth?.confidence ?? null,
                geometry_accuracy_meters: truth?.accuracy_meters ?? null,
                location_uncertain: uncertain,
                changed_recently: changedRecently(feature.properties?.last_activity_at),
              },
            } as Feature;
          });
          const consumerFeatures = projectTypeRef.current
            ? enrichedFeatures
            : enrichedFeatures.filter((feature) => {
                if (feature.properties?.project_type !== "environmental_review") return true;
                return Number(feature.properties?.display_priority ?? 0) >= MAJOR_REVIEW_PRIORITY;
              });
          const priorityFloor = projectTypeRef.current ? 0 : minimumPriorityForZoom(map.getZoom());
          const displayFeatures = consumerFeatures.filter(
            (feature) => Number(feature.properties?.display_priority ?? 0) >= priorityFloor,
          );
          const pointFeatures = displayFeatures.filter((feature): feature is Feature<Point> => feature.geometry?.type === "Point");
          const shapeFeatures = displayFeatures.filter((feature) => feature.geometry?.type !== "Point");
          (map.getSource(PROJECT_SOURCE) as import("maplibre-gl").GeoJSONSource)?.setData({ type: "FeatureCollection", features: shapeFeatures });
          (map.getSource(POINT_SOURCE) as import("maplibre-gl").GeoJSONSource)?.setData({ type: "FeatureCollection", features: pointFeatures });
          (map.getSource(DENSITY_SOURCE) as import("maplibre-gl").GeoJSONSource)?.setData({ type: "FeatureCollection", features: pointFeatures });

          const highlights = displayFeatures
            .map(featureProject)
            .filter((project): project is MapProject => project !== null)
            .sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0) || String(b.lastActivityAt ?? "").localeCompare(String(a.lastActivityAt ?? "")))
            .slice(0, 3);
          onHighlightsRef.current?.(highlights);

          const metadata = data.metadata;
          if (metadata) {
            onCoverageRef.current?.({
              visibleMapped: displayFeatures.length,
              mappedMatching: Number(metadata.mapped_matching ?? consumerFeatures.length),
              locationPending: Number(metadata.location_pending ?? 0),
              totalMatching: Number(metadata.total_matching ?? consumerFeatures.length),
            });
          }
        } catch (error) {
          if (error instanceof DOMException && error.name === "AbortError") return;
          console.error("Failed to refresh NS Trackstar projects", error);
        }
      }

      refreshProjectsRef.current = () => void refreshProjects();

      map.on("load", () => {
        if (!map) return;
        setMapState("ready");
        map.addSource(PROJECT_SOURCE, { type: "geojson", data: emptyCollection() });
        map.addSource(POINT_SOURCE, { type: "geojson", data: emptyCollection(), cluster: true, clusterMaxZoom: 13, clusterRadius: 44 });
        map.addSource(DENSITY_SOURCE, { type: "geojson", data: emptyCollection() });
        map.addSource(SELECTED_SOURCE, { type: "geojson", data: emptyCollection() });

        const categoryColor = [
          "match", ["get", "project_type"],
          "municipal_development", "#d9ff61",
          "environmental_review", "#b9a7ff",
          "transportation_project", "#ffb45f",
          "public_works", "#67d7ff",
          "water_infrastructure", "#59edc5",
          "#d9ff61",
        ] as import("maplibre-gl").ExpressionSpecification;
        const exactFilter = ["!=", ["get", "location_uncertain"], true] as import("maplibre-gl").FilterSpecification;
        const uncertainFilter = ["==", ["get", "location_uncertain"], true] as import("maplibre-gl").FilterSpecification;
        const unclusteredFilter = ["!", ["has", "point_count"]] as import("maplibre-gl").FilterSpecification;

        map.addLayer({
          id: "density-heat", type: "heatmap", source: DENSITY_SOURCE, maxzoom: 15, layout: { visibility: "none" },
          paint: {
            "heatmap-weight": ["interpolate", ["linear"], ["coalesce", ["get", "display_priority"], 0], 0, 0.35, 1, 1],
            "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 7, 0.6, 13, 1.45],
            "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 7, 14, 14, 34],
            "heatmap-opacity": ["interpolate", ["linear"], ["zoom"], 7, 0.72, 15, 0.32],
            "heatmap-color": ["interpolate", ["linear"], ["heatmap-density"], 0, "rgba(8,16,13,0)", 0.18, "rgba(89,237,197,.35)", 0.42, "rgba(103,215,255,.55)", 0.68, "rgba(217,255,97,.72)", 1, "rgba(255,180,95,.92)"],
          },
        });
        map.addLayer({ id: "recent-line-glow", type: "line", source: PROJECT_SOURCE, filter: ["==", ["get", "changed_recently"], true], paint: { "line-color": categoryColor, "line-width": ["interpolate", ["linear"], ["zoom"], 7, 5, 14, 10], "line-opacity": 0.16, "line-blur": 5 } });
        map.addLayer({ id: "projects-fill", type: "fill", source: PROJECT_SOURCE, filter: ["all", ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]], exactFilter], paint: { "fill-color": categoryColor, "fill-opacity": normalFillOpacity } });
        map.addLayer({ id: "projects-fill-uncertain", type: "fill", source: PROJECT_SOURCE, filter: ["all", ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]], uncertainFilter], paint: { "fill-color": categoryColor, "fill-opacity": 0.08 } });
        map.addLayer({ id: "projects-line", type: "line", source: PROJECT_SOURCE, filter: exactFilter, paint: { "line-color": categoryColor, "line-width": ["interpolate", ["linear"], ["zoom"], 7, 1, 13, 2.4, 17, 4], "line-opacity": normalLineOpacity } });
        map.addLayer({ id: "projects-line-uncertain", type: "line", source: PROJECT_SOURCE, filter: uncertainFilter, paint: { "line-color": categoryColor, "line-width": ["interpolate", ["linear"], ["zoom"], 7, 1.3, 13, 2.5, 17, 4], "line-opacity": 0.62, "line-dasharray": [2, 2] } });
        map.addLayer({ id: "project-clusters", type: "circle", source: POINT_SOURCE, filter: ["has", "point_count"], paint: { "circle-color": "#111b17", "circle-radius": ["step", ["get", "point_count"], 14, 10, 18, 50, 23, 200, 28], "circle-stroke-color": "#d9ff61", "circle-stroke-width": 1.7, "circle-opacity": 0.86 } });
        map.addLayer({ id: "project-cluster-count", type: "symbol", source: POINT_SOURCE, filter: ["has", "point_count"], layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 10, "text-font": ["Noto Sans Regular"] }, paint: { "text-color": "#f5ffd0" } });
        map.addLayer({ id: "recent-point-glow", type: "circle", source: POINT_SOURCE, filter: ["all", unclusteredFilter, ["==", ["get", "changed_recently"], true]], paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 8, 14, 15], "circle-color": categoryColor, "circle-opacity": 0.18, "circle-blur": 0.5 } });
        map.addLayer({ id: "uncertain-point-halo", type: "circle", source: POINT_SOURCE, filter: ["all", unclusteredFilter, uncertainFilter], paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 9, 14, 15], "circle-color": categoryColor, "circle-opacity": 0.14, "circle-blur": 0.35 } });
        map.addLayer({
          id: "projects-points", type: "circle", source: POINT_SOURCE, filter: ["all", unclusteredFilter, exactFilter],
          paint: { "circle-radius": ["interpolate", ["linear"], ["coalesce", ["get", "display_priority"], 0], 0, 3.5, 0.5, 5.6, 1, 8.5], "circle-color": categoryColor, "circle-opacity": normalPointOpacity, "circle-stroke-color": "#101416", "circle-stroke-width": ["interpolate", ["linear"], ["coalesce", ["get", "display_priority"], 0], 0, 1, 1, 2.2], "circle-stroke-opacity": 0.9 },
        });
        map.addLayer({
          id: "projects-points-uncertain", type: "circle", source: POINT_SOURCE, filter: ["all", unclusteredFilter, uncertainFilter],
          paint: { "circle-radius": ["interpolate", ["linear"], ["coalesce", ["get", "display_priority"], 0], 0, 3.5, 0.5, 5.6, 1, 8.5], "circle-color": categoryColor, "circle-opacity": 0.62, "circle-stroke-color": "#f5faf7", "circle-stroke-width": 1.4, "circle-stroke-opacity": 0.58 },
        });
        map.addLayer({
          id: "project-labels", type: "symbol", source: DENSITY_SOURCE, minzoom: 11.6,
          layout: { "text-field": ["get", "name"], "text-size": ["interpolate", ["linear"], ["coalesce", ["get", "display_priority"], 0], 0, 9, 1, 12], "text-font": ["Noto Sans Regular"], "text-offset": [0, 1.25], "text-anchor": "top", "text-max-width": 13, "text-allow-overlap": false },
          paint: { "text-color": "#eef5f0", "text-halo-color": "rgba(5,11,8,.92)", "text-halo-width": 1.5, "text-opacity": ["interpolate", ["linear"], ["coalesce", ["get", "display_priority"], 0], 0, 0.35, 1, 0.94] },
        });

        map.addLayer({ id: "selected-fill", type: "fill", source: SELECTED_SOURCE, filter: ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]], paint: { "fill-color": "#d9ff61", "fill-opacity": 0.38 } });
        map.addLayer({ id: "selected-line-glow", type: "line", source: SELECTED_SOURCE, paint: { "line-color": "#d9ff61", "line-width": 11, "line-opacity": 0.24, "line-blur": 5 } });
        map.addLayer({ id: "selected-line", type: "line", source: SELECTED_SOURCE, filter: ["!=", ["get", "location_uncertain"], true], paint: { "line-color": "#f5ffc9", "line-width": 3.5, "line-opacity": 1 } });
        map.addLayer({ id: "selected-line-uncertain", type: "line", source: SELECTED_SOURCE, filter: ["==", ["get", "location_uncertain"], true], paint: { "line-color": "#f5ffc9", "line-width": 3.5, "line-opacity": 0.92, "line-dasharray": [2, 2] } });
        map.addLayer({ id: "selected-point-glow", type: "circle", source: SELECTED_SOURCE, filter: ["==", ["geometry-type"], "Point"], paint: { "circle-radius": 18, "circle-color": "#d9ff61", "circle-opacity": 0.2, "circle-blur": 0.45 } });
        map.addLayer({ id: "selected-point", type: "circle", source: SELECTED_SOURCE, filter: ["==", ["geometry-type"], "Point"], paint: { "circle-radius": 9, "circle-color": "#d9ff61", "circle-stroke-color": "#f7ffd7", "circle-stroke-width": 3 } });

        focusProjectRef.current = (project) => {
          if (!map) return;
          const selectedSource = map.getSource(SELECTED_SOURCE) as import("maplibre-gl").GeoJSONSource;
          stopSelectionPulse();
          setContextOpacity(Boolean(project?.geometry));
          if (!project?.geometry) {
            selectedSource.setData(emptyCollection());
            return;
          }
          selectedSource.setData({
            type: "Feature",
            geometry: project.geometry,
            properties: {
              id: project.id,
              name: project.name,
              project_type: project.projectType,
              delivery_stage: project.deliveryStage,
              location_uncertain: Boolean(project.locationUncertain),
            },
          });
          ignoreMoveEndUntil = performance.now() + (briefingActiveRef.current ? 1900 : 1400);
          frameFeature(
            map,
            project.geometry,
            maplibregl,
            displayModeRef.current === "perspective",
            briefingActiveRef.current,
            project.id,
          );
          startSelectionPulse();
        };

        for (const layer of PROJECT_LAYERS) {
          map.on("mouseenter", layer, () => { if (map) map.getCanvas().style.cursor = "pointer"; });
          map.on("mouseleave", layer, () => { if (map) map.getCanvas().style.cursor = ""; });
          map.on("click", layer, (event) => {
            const project = event.features?.[0] ? featureProject(event.features[0] as Feature) : null;
            if (project) onSelectRef.current(project);
          });
        }

        map.on("mouseenter", "project-clusters", () => { if (map) map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", "project-clusters", () => { if (map) map.getCanvas().style.cursor = ""; });
        map.on("click", "project-clusters", async (event) => {
          if (!map) return;
          const feature = event.features?.[0];
          const clusterId = Number(feature?.properties?.cluster_id);
          if (!Number.isFinite(clusterId) || feature?.geometry.type !== "Point") return;
          const pointSource = map.getSource(POINT_SOURCE) as import("maplibre-gl").GeoJSONSource;
          const zoom = await pointSource.getClusterExpansionZoom(clusterId);
          map.easeTo({ center: feature.geometry.coordinates as [number, number], zoom, duration: 600 });
        });

        void refreshProjects();
        applyDisplayMode(displayModeRef.current);
        focusProjectRef.current?.(selectedProjectRef.current);
      });

      map.on("moveend", () => {
        if (performance.now() < ignoreMoveEndUntil || briefingActiveRef.current || selectedProjectRef.current) return;
        if (moveRefreshTimer !== undefined) window.clearTimeout(moveRefreshTimer);
        moveRefreshTimer = window.setTimeout(() => refreshProjectsRef.current?.(), 220);
      });
    }

    void mount();
    return () => {
      disposed = true;
      if (pulseFrame !== undefined) cancelAnimationFrame(pulseFrame);
      if (moveRefreshTimer !== undefined) window.clearTimeout(moveRefreshTimer);
      refreshProjectsRef.current = null;
      focusProjectRef.current = null;
      applyDisplayModeRef.current = null;
      resetRegionRef.current = null;
      locateRef.current = null;
      refreshAbort?.abort();
      map?.remove();
    };
  }, []);

  return (
    <>
      <div className="mapCanvas" ref={containerRef} />
      {mapState !== "ready" ? (
        <div className={mapState === "error" ? "mapStatus error" : "mapStatus"} role="status">
          {mapState === "error" ? <><strong>Map could not load</strong><button onClick={() => window.location.reload()} type="button">Retry</button></> : "Loading what’s changing around you…"}
        </div>
      ) : null}
    </>
  );
}
