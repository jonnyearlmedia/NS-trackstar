"use client";

import type { Feature, FeatureCollection, Geometry, Point } from "geojson";
import { useEffect, useRef, useState } from "react";

export type TimeWindow = "today" | "week" | "upcoming" | "all";

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
) {
  const narrow = map.getContainer().clientWidth < 700;
  if (geometry.type === "Point") {
    map.flyTo({
      center: geometry.coordinates as [number, number],
      zoom: 15.5,
      pitch: 42,
      bearing: -8,
      duration: 1150,
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
        ? { top: 190, right: 34, bottom: 310, left: 34 }
        : { top: 120, right: 90, bottom: 180, left: 90 },
      maxZoom: 15.5,
      pitch: 38,
      bearing: -6,
      duration: 1250,
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
}: MapCanvasProps) {
  const [areaMoved, setAreaMoved] = useState(false);
  const [mapState, setMapState] = useState<"loading" | "ready" | "error">("loading");
  const containerRef = useRef<HTMLDivElement | null>(null);
  const onSelectRef = useRef(onSelectProject);
  const onCoverageRef = useRef(onCoverageChange);
  const timeWindowRef = useRef(timeWindow);
  const projectTypeRef = useRef(projectType);
  const selectedProjectRef = useRef(selectedProject);
  const refreshProjectsRef = useRef<(() => void) | null>(null);
  const focusProjectRef = useRef<((project: MapProject | null) => void) | null>(null);

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
    let disposed = false;
    let map: import("maplibre-gl").Map | undefined;
    let refreshAbort: AbortController | undefined;

    async function mount() {
      if (!containerRef.current) return;
      const maplibregl = await import("maplibre-gl");
      if (disposed || !containerRef.current) return;

      maplibregl.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

      map = new maplibregl.Map({
        container: containerRef.current,
        style: "https://tiles.openfreemap.org/styles/liberty",
        bounds: NAPA_SOLANO_BOUNDS,
        fitBoundsOptions: {
          padding: { top: 175, right: 22, bottom: 92, left: 22 },
        },
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
          map.setPaintProperty("projects-fill", "fill-opacity", hasSelection ? 0.07 : 0.3);
        }
        if (map.getLayer("projects-line")) {
          map.setPaintProperty("projects-line", "line-opacity", hasSelection ? 0.14 : 0.78);
        }
        if (map.getLayer("projects-points")) {
          map.setPaintProperty("projects-points", "circle-opacity", hasSelection ? 0.18 : 0.96);
          map.setPaintProperty("projects-points", "circle-stroke-opacity", hasSelection ? 0.22 : 1);
        }
        if (map.getLayer("project-clusters")) {
          map.setPaintProperty("project-clusters", "circle-opacity", hasSelection ? 0.14 : 0.9);
        }
        if (map.getLayer("project-cluster-count")) {
          map.setPaintProperty("project-cluster-count", "text-opacity", hasSelection ? 0.18 : 1);
        }
      }

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
          shapeSource?.setData({ type: "FeatureCollection", features: shapeFeatures });
          pointSource?.setData({ type: "FeatureCollection", features: pointFeatures });

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
        map.addSource(SELECTED_SOURCE, { type: "geojson", data: emptyCollection() });

        map.addLayer({
          id: "projects-fill",
          type: "fill",
          source: PROJECT_SOURCE,
          filter: ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]],
          paint: {
            "fill-color": [
              "match",
              ["get", "delivery_stage"],
              "Construction",
              "#d7ff58",
              "Design",
              "#ffb38a",
              "Planning",
              "#b6a7ff",
              "Completed",
              "#8fd18a",
              "#d7ff58",
            ],
            "fill-opacity": 0.3,
          },
        });
        map.addLayer({
          id: "projects-line",
          type: "line",
          source: PROJECT_SOURCE,
          paint: {
            "line-color": "#efffb6",
            "line-width": ["interpolate", ["linear"], ["zoom"], 8, 1.1, 13, 2.2, 17, 3.5],
            "line-opacity": 0.78,
          },
        });
        map.addLayer({
          id: "project-clusters",
          type: "circle",
          source: POINT_SOURCE,
          filter: ["has", "point_count"],
          paint: {
            "circle-color": "#17211b",
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
            "circle-color": "#d7ff58",
            "circle-opacity": 0.96,
            "circle-stroke-color": "#101416",
            "circle-stroke-width": 2,
            "circle-stroke-opacity": 1,
          },
        });

        map.addLayer({
          id: "selected-fill",
          type: "fill",
          source: SELECTED_SOURCE,
          filter: ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]],
          paint: { "fill-color": "#d7ff58", "fill-opacity": 0.52 },
        });
        map.addLayer({
          id: "selected-line-glow",
          type: "line",
          source: SELECTED_SOURCE,
          paint: {
            "line-color": "#d7ff58",
            "line-width": 11,
            "line-opacity": 0.26,
            "line-blur": 5,
          },
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
          paint: {
            "circle-radius": 18,
            "circle-color": "#d7ff58",
            "circle-opacity": 0.2,
            "circle-blur": 0.45,
          },
        });
        map.addLayer({
          id: "selected-point",
          type: "circle",
          source: SELECTED_SOURCE,
          filter: ["==", ["geometry-type"], "Point"],
          paint: {
            "circle-radius": 10,
            "circle-color": "#d7ff58",
            "circle-stroke-color": "#f7ffd7",
            "circle-stroke-width": 3,
          },
        });

        focusProjectRef.current = (project) => {
          if (!map) return;
          const selectedSource = map.getSource(SELECTED_SOURCE) as import("maplibre-gl").GeoJSONSource;
          setContextOpacity(Boolean(project));
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
          frameFeature(map, project.geometry, maplibregl);
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
              deliveryStage: feature.properties.delivery_stage
                ? String(feature.properties.delivery_stage)
                : null,
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
        focusProjectRef.current?.(selectedProjectRef.current);
      });

      map.on("moveend", () => setAreaMoved(true));
    }

    void mount();
    return () => {
      disposed = true;
      refreshProjectsRef.current = null;
      focusProjectRef.current = null;
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
      {areaMoved ? (
        <button className="searchAreaButton" onClick={() => refreshProjectsRef.current?.()} type="button">
          Search This Area
        </button>
      ) : null}
    </>
  );
}
