"use client";

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

const NAPA_SOLANO_CENTER: [number, number] = [-122.2708, 38.218];
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const PROJECT_SOURCE = "trackstar-projects";
const PROJECT_LAYERS = ["projects-fill", "projects-line", "projects-points"] as const;

function emptyCollection() {
  return { type: "FeatureCollection" as const, features: [] };
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
              "#d7ff58",
            ],
            "fill-opacity": 0.35,
          },
        });
        map.addLayer({
          id: "projects-line",
          type: "line",
          source: PROJECT_SOURCE,
          paint: { "line-color": "#efffb6", "line-width": 2.5, "line-opacity": 0.9 },
        });
        map.addLayer({
          id: "projects-points",
          type: "circle",
          source: PROJECT_SOURCE,
          filter: ["==", ["geometry-type"], "Point"],
          paint: {
            "circle-radius": 7,
            "circle-color": "#d7ff58",
            "circle-stroke-color": "#101416",
            "circle-stroke-width": 2,
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
            const feature = event.features?.[0];
            if (!feature?.properties) return;
            const project: MapProject = {
              id: String(feature.properties.id),
              name: String(feature.properties.name),
              projectType: String(feature.properties.project_type),
              deliveryStage: feature.properties.delivery_stage
                ? String(feature.properties.delivery_stage)
                : null,
            };
            onSelectRef.current(project);

            const geometry = feature.geometry;
            if (geometry.type === "Point") {
              map?.flyTo({ center: geometry.coordinates as [number, number], zoom: 15, pitch: 42 });
            }
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
