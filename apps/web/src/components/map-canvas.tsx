"use client";

import type { Geometry } from "geojson";
import { useEffect, useRef } from "react";

export type MapProject = {
  id: string;
  name: string;
  projectType: string;
  deliveryStage: string | null;
};

type MapCanvasProps = {
  onSelectProject: (project: MapProject) => void;
};

type MapLibreModule = typeof import("maplibre-gl");

const NAPA_SOLANO_CENTER: [number, number] = [-122.2708, 38.218];
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const PROJECT_SOURCE = "trackstar-projects";
const SELECTED_SOURCE = "trackstar-selected-project";
const PROJECT_LAYERS = ["projects-fill", "projects-line", "projects-points"] as const;

function emptyCollection() {
  return { type: "FeatureCollection" as const, features: [] };
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

function frameFeature(map: import("maplibre-gl").Map, geometry: Geometry, maplibregl: MapLibreModule) {
  if (geometry.type === "Point") {
    map.flyTo({
      center: geometry.coordinates as [number, number],
      zoom: 15.5,
      pitch: 42,
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
      padding: { top: 110, right: 55, bottom: 260, left: 55 },
      maxZoom: 15.5,
      pitch: 38,
      duration: 1200,
      essential: true,
    });
  }
}

export function MapCanvas({ onSelectProject }: MapCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const onSelectRef = useRef(onSelectProject);

  useEffect(() => {
    onSelectRef.current = onSelectProject;
  }, [onSelectProject]);

  useEffect(() => {
    let disposed = false;
    let map: import("maplibre-gl").Map | undefined;
    let refreshAbort: AbortController | undefined;

    async function mount() {
      if (!containerRef.current) return;
      const maplibregl = await import("maplibre-gl");
      if (disposed || !containerRef.current) return;

      map = new maplibregl.Map({
        container: containerRef.current,
        style: "https://tiles.openfreemap.org/styles/liberty",
        center: NAPA_SOLANO_CENTER,
        zoom: 9,
        attributionControl: false,
      });

      map.addControl(new maplibregl.NavigationControl({ showCompass: true }), "bottom-right");
      map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-left");

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
        });

        try {
          const response = await fetch(`${API_BASE}/map/projects?${params}`, {
            signal: refreshAbort.signal,
          });
          if (!response.ok) throw new Error(`Project API returned ${response.status}`);
          const data = await response.json();
          const source = map.getSource(PROJECT_SOURCE) as import("maplibre-gl").GeoJSONSource;
          source?.setData(data);
        } catch (error) {
          if (error instanceof DOMException && error.name === "AbortError") return;
          console.error("Failed to refresh NS Trackstar projects", error);
        }
      }

      map.on("load", () => {
        if (!map) return;
        map.addSource(PROJECT_SOURCE, { type: "geojson", data: emptyCollection() });
        map.addSource(SELECTED_SOURCE, { type: "geojson", data: emptyCollection() });

        map.addLayer({
          id: "projects-fill",
          type: "fill",
          source: PROJECT_SOURCE,
          filter: ["==", ["geometry-type"], "Polygon"],
          paint: {
            "fill-color": [
              "match",
              ["get", "delivery_stage"],
              "Construction", "#d7ff58",
              "Design", "#ffb38a",
              "Planning", "#b6a7ff",
              "Completed", "#8fd18a",
              "#d7ff58"
            ],
            "fill-opacity": 0.28,
          },
        });
        map.addLayer({
          id: "projects-line",
          type: "line",
          source: PROJECT_SOURCE,
          paint: { "line-color": "#efffb6", "line-width": 2, "line-opacity": 0.7 },
        });
        map.addLayer({
          id: "projects-points",
          type: "circle",
          source: PROJECT_SOURCE,
          filter: ["==", ["geometry-type"], "Point"],
          paint: {
            "circle-radius": 6,
            "circle-color": "#d7ff58",
            "circle-stroke-color": "#101416",
            "circle-stroke-width": 2,
          },
        });
        map.addLayer({
          id: "selected-fill",
          type: "fill",
          source: SELECTED_SOURCE,
          filter: ["==", ["geometry-type"], "Polygon"],
          paint: { "fill-color": "#d7ff58", "fill-opacity": 0.5 },
        });
        map.addLayer({
          id: "selected-line-glow",
          type: "line",
          source: SELECTED_SOURCE,
          paint: { "line-color": "#d7ff58", "line-width": 9, "line-opacity": 0.18, "line-blur": 4 },
        });
        map.addLayer({
          id: "selected-line",
          type: "line",
          source: SELECTED_SOURCE,
          paint: { "line-color": "#f5ffc9", "line-width": 3.5, "line-opacity": 1 },
        });
        map.addLayer({
          id: "selected-point",
          type: "circle",
          source: SELECTED_SOURCE,
          filter: ["==", ["geometry-type"], "Point"],
          paint: {
            "circle-radius": 10,
            "circle-color": "#d7ff58",
            "circle-blur": 0.08,
            "circle-stroke-color": "#f7ffd7",
            "circle-stroke-width": 3,
          },
        });

        for (const layer of PROJECT_LAYERS) {
          map.on("mouseenter", layer, () => {
            if (map) map.getCanvas().style.cursor = "pointer";
          });
          map.on("mouseleave", layer, () => {
            if (map) map.getCanvas().style.cursor = "";
          });
          map.on("click", layer, (event) => {
            if (!map) return;
            const feature = event.features?.[0];
            if (!feature?.properties || !feature.geometry) return;
            const project: MapProject = {
              id: String(feature.properties.id),
              name: String(feature.properties.name),
              projectType: String(feature.properties.project_type),
              deliveryStage: feature.properties.delivery_stage
                ? String(feature.properties.delivery_stage)
                : null,
            };
            onSelectRef.current(project);

            const selectedSource = map.getSource(SELECTED_SOURCE) as import("maplibre-gl").GeoJSONSource;
            selectedSource.setData({
              type: "Feature",
              geometry: feature.geometry,
              properties: feature.properties,
            });
            frameFeature(map, feature.geometry as Geometry, maplibregl);
          });
        }

        void refreshProjects();
      });

      map.on("moveend", () => void refreshProjects());
    }

    void mount();
    return () => {
      disposed = true;
      refreshAbort?.abort();
      map?.remove();
    };
  }, []);

  return <div className="mapCanvas" ref={containerRef} />;
}
