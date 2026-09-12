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
  selectedProject: MapProject | null;
  timeWindow: TimeWindow;
  projectType?: string | null;
  displayMode: MapDisplayMode;
  resetNonce: number;
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

const NAPA_SOLANO_BOUNDS: [[number, number], [number, number]] = [
  [-122.72, 37.95],
  [-121.54, 38.88],
];
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const PROJECT_SOURCE = "trackstar-project-shapes";
const POINT_SOURCE = "trackstar-project-points";
const DENSITY_SOURCE = "trackstar-density-points";
const SELECTED_SOURCE = "trackstar-selected-project";
const PROJECT_LAYERS = ["projects-fill", "projects-line", "projects-points"] as const;

function emptyCollection(): FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}

function visitCoordinates(value: unknown, visit: (coordinate: [number, number]) => void) {
  if (!Array.isArray(value) || value.length === 0) return;
  if (
    value.length >= 2 &&
    typeof value[0] === "number" &&
    typeof value[1] === "number"
  ) {
    visit([value[0], value[1]]);
    return;
  }
  for (const child of value) visitCoordinates(child, visit);
}

function frameFeature(
  map: import("maplibre-gl").Map,
  geometry: Geometry,
  maplibregl: MapLibreModule,
  perspective: boolean,
) {
  const narrow = map.getContainer().clientWidth < 700;
  if (geometry.type === "Point") {
    map.flyTo({
      center: geometry.coordinates as [number, number],
      zoom: narrow ? 14.8 : 15.5,
      pitch: perspective ? 58 : 38,
      bearing: perspective ? -16 : -7,
      duration: 1100,
      essential: true,
    });
    return;
  }

  if (geometry.type === "GeometryCollection") return;

  const bounds = new maplibregl.LngLatBounds();
  visitCoordinates(geometry.coordinates, (coordinate) => bounds.extend(coordinate));
  if (!bounds.isEmpty()) {
    map.fitBounds(bounds, {
      padding: narrow
        ? { top: 190, right: 30, bottom: 300, left: 30 }
        : { top: 115, right: 90, bottom: 180, left: 90 },
      maxZoom: 15.5,
      pitch: perspective ? 58 : 36,
      bearing: perspective ? -15 : -5,
      duration: 1200,
      essential: true,
    });
  }
}

export function MapCanvas({
  onSelectProject,
  onCoverageChange,
  selectedProject,
  timeWindow,
  projectType,
  displayMode,
  resetNonce,
  briefingActive = false,
}: MapCanvasProps) {
  const [areaMoved, setAreaMoved] = useState(false);
  const [mapState, setMapState] = useState<"loading" | "ready" | "error">("loading");
  const containerRef = useRef<HTMLDivElement | null>(null);
  const onSelectRef = useRef(onSelectProject);
  const onCoverageRef = useRef(onCoverageChange);
  const timeWindowRef = useRef(timeWindow);
  const projectTypeRef = useRef(projectType);
  const selectedProjectRef = useRef(selectedProject);
  const displayModeRef = useRef(displayMode);
  const briefingActiveRef = useRef(briefingActive);
  const refreshProjectsRef = useRef<(() => void) | null>(null);
  const focusProjectRef = useRef<((project: MapProject | null) => void) | null>(null);
  const applyDisplayModeRef = useRef<((mode: MapDisplayMode) => void) | null>(null);
  const resetRegionRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    onSelectRef.current = onSelectProject;
  }, [onSelectProject]);

  useEffect(() => {
    onCoverageRef.current = onCoverageChange;
  }, [onCoverageChange]);

  useEffect(() => {
    timeWindowRef.current = timeWindow;
    refreshProjectsRef.current?.();
  }, [timeWindow]);

  useEffect(() => {
    projectTypeRef.current = projectType;
    refreshProjectsRef.current?.();
  }, [projectType]);

  useEffect(() => {
    selectedProjectRef.current = selectedProject;
    focusProjectRef.current?.(selectedProject);
  }, [selectedProject]);

  useEffect(() => {
    displayModeRef.current = displayMode;
    applyDisplayModeRef.current?.(displayMode);
  }, [displayMode]);

  useEffect(() => {
    briefingActiveRef.current = briefingActive;
  }, [briefingActive]);

  useEffect(() => {
    if (resetNonce > 0) resetRegionRef.current?.();
  }, [resetNonce]);

  useEffect(() => {
    let disposed = false;
    let map: import("maplibre-gl").Map | undefined;
    let refreshAbort: AbortController | undefined;
    let pulseFrame: number | undefined;
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
        fitBoundsOptions: { padding: { top: 185, right: 22, bottom: 100, left: 22 } },
        attributionControl: false,
      });

      map.on("error", () => {
        if (!map?.isStyleLoaded()) setMapState("error");
      });

      map.addControl(new maplibregl.NavigationControl({ showCompass: true }), "bottom-right");
      map.addControl(
        new maplibregl.GeolocateControl({
          positionOptions: { enableHighAccuracy: true },
          trackUserLocation: false,
          showUserLocation: true,
        }),
        "bottom-right",
      );
      map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-left");

      function setContextOpacity(hasSelection: boolean) {
        if (!map) return;
        if (map.getLayer("projects-fill")) {
          map.setPaintProperty("projects-fill", "fill-opacity", hasSelection ? 0.055 : 0.28);
        }
        if (map.getLayer("projects-line")) {
          map.setPaintProperty("projects-line", "line-opacity", hasSelection ? 0.12 : 0.78);
        }
        if (map.getLayer("projects-points")) {
          map.setPaintProperty("projects-points", "circle-opacity", hasSelection ? 0.16 : 0.95);
          map.setPaintProperty("projects-points", "circle-stroke-opacity", hasSelection ? 0.2 : 1);
        }
        if (map.getLayer("project-clusters")) {
          map.setPaintProperty("project-clusters", "circle-opacity", hasSelection ? 0.12 : 0.9);
        }
        if (map.getLayer("project-cluster-count")) {
          map.setPaintProperty("project-cluster-count", "text-opacity", hasSelection ? 0.18 : 1);
        }
        if (map.getLayer("project-labels")) {
          map.setPaintProperty("project-labels", "text-opacity", hasSelection ? 0.18 : 0.92);
        }
      }

      function stopSelectionPulse() {
        if (pulseFrame !== undefined) cancelAnimationFrame(pulseFrame);
        pulseFrame = undefined;
        if (!map) return;
        if (map.getLayer("selected-point-glow")) {
          map.setPaintProperty("selected-point-glow", "circle-radius", 18);
          map.setPaintProperty("selected-point-glow", "circle-opacity", 0.2);
        }
        if (map.getLayer("selected-line-glow")) {
          map.setPaintProperty("selected-line-glow", "line-width", 11);
          map.setPaintProperty("selected-line-glow", "line-opacity", 0.26);
        }
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
            map.setPaintProperty("selected-point-glow", "circle-opacity", 0.1 + wave * 0.22);
          }
          if (map.getLayer("selected-line-glow")) {
            map.setPaintProperty("selected-line-glow", "line-width", 8 + wave * 9);
            map.setPaintProperty("selected-line-glow", "line-opacity", 0.14 + wave * 0.2);
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
        for (const layer of [
          "projects-fill",
          "projects-line",
          "project-clusters",
          "project-cluster-count",
          "projects-points",
          "project-labels",
        ]) {
          if (map.getLayer(layer)) map.setLayoutProperty(layer, "visibility", projectVisibility);
        }
        if (map.getLayer("density-heat")) {
          map.setLayoutProperty("density-heat", "visibility", density ? "visible" : "none");
        }
        if (!selectedProjectRef.current) {
          map.easeTo({
            pitch: perspective ? 56 : 0,
            bearing: perspective ? -12 : 0,
            duration: 650,
            essential: true,
          });
        }
      }

      applyDisplayModeRef.current = applyDisplayMode;
      resetRegionRef.current = () => {
        if (!map) return;
        ignoreMoveEndUntil = performance.now() + 1200;
        setAreaMoved(false);
        map.fitBounds(NAPA_SOLANO_BOUNDS, {
          padding: { top: 185, right: 22, bottom: 100, left: 22 },
          pitch: displayModeRef.current === "perspective" ? 48 : 0,
          bearing: displayModeRef.current === "perspective" ? -10 : 0,
          duration: 900,
          essential: true,
        });
      };

      async function refreshProjects() {
        if (!map || !map.isStyleLoaded()) return;
        refreshAbort?.abort();
        refreshAbort = new AbortController();
        const bounds = map.getBounds();
        const params = new URLSearchParams({
          west: String(bounds.getWest()),
          south: String(bounds.getSouth()),
          east: String(bounds.getEast()),
          north: String(bounds.getNorth()),
          window: timeWindowRef.current,
        });
        if (projectTypeRef.current) params.set("project_type", projectTypeRef.current);

        try {
          const response = await fetch(`${API_BASE}/map/projects?${params}`, {
            signal: refreshAbort.signal,
          });
          if (!response.ok) throw new Error(`Project API returned ${response.status}`);
          const data = (await response.json()) as ProjectCollection;
          const pointFeatures = data.features.filter(
            (feature): feature is Feature<Point> => feature.geometry?.type === "Point",
          );
          const shapeFeatures = data.features.filter((feature) => feature.geometry?.type !== "Point");
          const shapeSource = map.getSource(PROJECT_SOURCE) as import("maplibre-gl").GeoJSONSource;
          const pointSource = map.getSource(POINT_SOURCE) as import("maplibre-gl").GeoJSONSource;
          const densitySource = map.getSource(DENSITY_SOURCE) as import("maplibre-gl").GeoJSONSource;
          shapeSource?.setData({ type: "FeatureCollection", features: shapeFeatures });
          pointSource?.setData({ type: "FeatureCollection", features: pointFeatures });
          densitySource?.setData({ type: "FeatureCollection", features: pointFeatures });

          const metadata = data.metadata;
          if (metadata) {
            onCoverageRef.current?.({
              visibleMapped: Number(metadata.visible_mapped ?? data.features.length),
              mappedMatching: Number(metadata.mapped_matching ?? data.features.length),
              locationPending: Number(metadata.location_pending ?? 0),
              totalMatching: Number(metadata.total_matching ?? data.features.length),
            });
          }
          setAreaMoved(false);
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
        map.addSource(POINT_SOURCE, {
          type: "geojson",
          data: emptyCollection(),
          cluster: true,
          clusterMaxZoom: 13,
          clusterRadius: 42,
        });
        map.addSource(DENSITY_SOURCE, { type: "geojson", data: emptyCollection() });
        map.addSource(SELECTED_SOURCE, { type: "geojson", data: emptyCollection() });

        const categoryColor = [
          "match",
          ["get", "project_type"],
          "municipal_development", "#d9ff61",
          "environmental_review", "#b9a7ff",
          "transportation_project", "#ffb45f",
          "public_works", "#67d7ff",
          "water_infrastructure", "#59edc5",
          "#d9ff61",
        ] as import("maplibre-gl").ExpressionSpecification;

        map.addLayer({
          id: "density-heat",
          type: "heatmap",
          source: DENSITY_SOURCE,
          maxzoom: 15,
          layout: { visibility: "none" },
          paint: {
            "heatmap-weight": 1,
            "heatmap-intensity": ["interpolate", ["linear"], ["zoom"], 7, 0.65, 13, 1.5],
            "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 7, 14, 14, 34],
            "heatmap-opacity": ["interpolate", ["linear"], ["zoom"], 7, 0.75, 15, 0.36],
            "heatmap-color": [
              "interpolate", ["linear"], ["heatmap-density"],
              0, "rgba(8,16,13,0)",
              0.18, "rgba(89,237,197,.35)",
              0.42, "rgba(103,215,255,.55)",
              0.68, "rgba(217,255,97,.72)",
              1, "rgba(255,180,95,.92)",
            ],
          },
        });
        map.addLayer({
          id: "projects-fill",
          type: "fill",
          source: PROJECT_SOURCE,
          filter: ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]],
          paint: { "fill-color": categoryColor, "fill-opacity": 0.28 },
        });
        map.addLayer({
          id: "projects-line",
          type: "line",
          source: PROJECT_SOURCE,
          paint: {
            "line-color": categoryColor,
            "line-width": ["interpolate", ["linear"], ["zoom"], 8, 1.2, 13, 2.4, 17, 4],
            "line-opacity": 0.78,
          },
        });
        map.addLayer({
          id: "project-clusters",
          type: "circle",
          source: POINT_SOURCE,
          filter: ["has", "point_count"],
          paint: {
            "circle-color": "#111b17",
            "circle-radius": ["step", ["get", "point_count"], 15, 10, 19, 50, 24, 200, 29],
            "circle-stroke-color": "#d9ff61",
            "circle-stroke-width": 2,
            "circle-opacity": 0.9,
          },
        });
        map.addLayer({
          id: "project-cluster-count",
          type: "symbol",
          source: POINT_SOURCE,
          filter: ["has", "point_count"],
          layout: {
            "text-field": ["get", "point_count_abbreviated"],
            "text-size": 11,
            "text-font": ["Noto Sans Regular"],
          },
          paint: { "text-color": "#f5ffd0", "text-opacity": 1 },
        });
        map.addLayer({
          id: "projects-points",
          type: "circle",
          source: POINT_SOURCE,
          filter: ["!", ["has", "point_count"]],
          paint: {
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 4, 12, 6, 16, 8],
            "circle-color": categoryColor,
            "circle-opacity": 0.95,
            "circle-stroke-color": "#101416",
            "circle-stroke-width": 2,
            "circle-stroke-opacity": 1,
          },
        });
        map.addLayer({
          id: "project-labels",
          type: "symbol",
          source: DENSITY_SOURCE,
          minzoom: 13.2,
          layout: {
            "text-field": ["get", "name"],
            "text-size": ["interpolate", ["linear"], ["zoom"], 13, 10, 17, 12],
            "text-font": ["Noto Sans Regular"],
            "text-offset": [0, 1.3],
            "text-anchor": "top",
            "text-max-width": 14,
            "text-allow-overlap": false,
          },
          paint: {
            "text-color": "#eef5f0",
            "text-halo-color": "rgba(5,11,8,.92)",
            "text-halo-width": 1.5,
            "text-opacity": 0.92,
          },
        });

        map.addLayer({
          id: "selected-fill",
          type: "fill",
          source: SELECTED_SOURCE,
          filter: ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]],
          paint: { "fill-color": "#d9ff61", "fill-opacity": 0.5 },
        });
        map.addLayer({
          id: "selected-line-glow",
          type: "line",
          source: SELECTED_SOURCE,
          paint: { "line-color": "#d9ff61", "line-width": 11, "line-opacity": 0.26, "line-blur": 5 },
        });
        map.addLayer({
          id: "selected-line",
          type: "line",
          source: SELECTED_SOURCE,
          paint: { "line-color": "#f5ffc9", "line-width": 3.5, "line-opacity": 1 },
        });
        map.addLayer({
          id: "selected-point-glow",
          type: "circle",
          source: SELECTED_SOURCE,
          filter: ["==", ["geometry-type"], "Point"],
          paint: { "circle-radius": 18, "circle-color": "#d9ff61", "circle-opacity": 0.2, "circle-blur": 0.45 },
        });
        map.addLayer({
          id: "selected-point",
          type: "circle",
          source: SELECTED_SOURCE,
          filter: ["==", ["geometry-type"], "Point"],
          paint: { "circle-radius": 10, "circle-color": "#d9ff61", "circle-stroke-color": "#f7ffd7", "circle-stroke-width": 3 },
        });

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
            },
          });
          ignoreMoveEndUntil = performance.now() + 1500;
          frameFeature(map, project.geometry, maplibregl, displayModeRef.current === "perspective");
          startSelectionPulse();
        };

        for (const layer of PROJECT_LAYERS) {
          map.on("mouseenter", layer, () => {
            if (map) map.getCanvas().style.cursor = "pointer";
          });
          map.on("mouseleave", layer, () => {
            if (map) map.getCanvas().style.cursor = "";
          });
          map.on("click", layer, (event) => {
            const feature = event.features?.[0];
            if (!feature?.properties || !feature.geometry) return;
            onSelectRef.current({
              id: String(feature.properties.id),
              name: String(feature.properties.name),
              projectType: String(feature.properties.project_type),
              deliveryStage: feature.properties.delivery_stage ? String(feature.properties.delivery_stage) : null,
              geometry: feature.geometry as Geometry,
            });
          });
        }

        map.on("mouseenter", "project-clusters", () => {
          if (map) map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", "project-clusters", () => {
          if (map) map.getCanvas().style.cursor = "";
        });
        map.on("click", "project-clusters", async (event) => {
          if (!map) return;
          const feature = event.features?.[0];
          const clusterId = Number(feature?.properties?.cluster_id);
          if (!Number.isFinite(clusterId) || feature?.geometry.type !== "Point") return;
          const pointSource = map.getSource(POINT_SOURCE) as import("maplibre-gl").GeoJSONSource;
          const zoom = await pointSource.getClusterExpansionZoom(clusterId);
          map.easeTo({ center: feature.geometry.coordinates as [number, number], zoom, duration: 650 });
        });

        void refreshProjects();
        applyDisplayMode(displayModeRef.current);
        focusProjectRef.current?.(selectedProjectRef.current);
      });

      map.on("moveend", () => {
        if (performance.now() >= ignoreMoveEndUntil && !briefingActiveRef.current) setAreaMoved(true);
      });
    }

    void mount();
    return () => {
      disposed = true;
      if (pulseFrame !== undefined) cancelAnimationFrame(pulseFrame);
      refreshProjectsRef.current = null;
      focusProjectRef.current = null;
      applyDisplayModeRef.current = null;
      resetRegionRef.current = null;
      refreshAbort?.abort();
      map?.remove();
    };
  }, []);

  return (
    <>
      <div className="mapCanvas" ref={containerRef} />
      {mapState !== "ready" ? (
        <div className={mapState === "error" ? "mapStatus error" : "mapStatus"} role="status">
          {mapState === "error" ? (
            <>
              <strong>Map could not load</strong>
              <button onClick={() => window.location.reload()} type="button">Retry</button>
            </>
          ) : (
            "Loading map and project geometry…"
          )}
        </div>
      ) : null}
      {areaMoved && !briefingActive ? (
        <button className="searchAreaButton" onClick={() => refreshProjectsRef.current?.()} type="button">
          Search This Area
        </button>
      ) : null}
    </>
  );
}
