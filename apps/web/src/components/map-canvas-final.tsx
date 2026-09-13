"use client";

import type { Feature, Point } from "geojson";
import { useEffect, useRef, useState } from "react";
import { installFinalLayers, SOURCES, updateMapData, updateSelected, updateUser } from "./map-final-layers";
import { loadViewportTruth } from "./map-final-data";
import { categoryCounts, lifecycleCounts, minimumPriorityForZoom, NAPA_SOLANO_BOUNDS, readSavedViewport, LAST_VIEWPORT_KEY, type ConsumerCategory, type LifecycleFilter, type MapCoverage, type MapProject, type MapViewportState, type TimeWindow, type UserLocation, type ViewportBounds } from "./map-final-model";

const REVIEW_PRIORITY = 0.4;

type Props = {
  onSelectProject: (project: MapProject) => void;
  onSelectProjects?: (projects: MapProject[]) => void;
  onCoverageChange?: (coverage: MapCoverage) => void;
  onViewportChange?: (viewport: MapViewportState) => void;
  onUserInteraction?: () => void;
  selectedProject: MapProject | null;
  timeWindow: TimeWindow;
  category: ConsumerCategory;
  lifecycle: LifecycleFilter;
  resetNonce: number;
  userLocation?: UserLocation | null;
  briefingActive?: boolean;
  restoreBounds?: ViewportBounds | null;
  restoreNonce?: number;
};

function geometryBounds(project: MapProject) {
  const geometry = project.geometry;
  if (!geometry || !("coordinates" in geometry)) return null;
  let west = Infinity, south = Infinity, east = -Infinity, north = -Infinity;
  const visit = (value: unknown) => {
    if (!Array.isArray(value) || value.length === 0) return;
    if (value.length >= 2 && typeof value[0] === "number" && typeof value[1] === "number") {
      west = Math.min(west, value[0]); south = Math.min(south, value[1]); east = Math.max(east, value[0]); north = Math.max(north, value[1]); return;
    }
    for (const child of value) visit(child);
  };
  visit(geometry.coordinates);
  return Number.isFinite(west) ? [[west, south], [east, north]] as [[number, number], [number, number]] : null;
}

export function MapCanvasFinal(props: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<import("maplibre-gl").Map | null>(null);
  const refreshRef = useRef<(() => void) | null>(null);
  const selectedRef = useRef(props.selectedProject);
  const briefingRef = useRef(Boolean(props.briefingActive));
  const categoryRef = useRef(props.category);
  const lifecycleRef = useRef(props.lifecycle);
  const timeRef = useRef(props.timeWindow);
  const userRef = useRef<UserLocation | null>(props.userLocation ?? null);
  const callbacks = useRef(props);
  const [mapState, setMapState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => { callbacks.current = props; });
  useEffect(() => { selectedRef.current = props.selectedProject; }, [props.selectedProject]);
  useEffect(() => { briefingRef.current = Boolean(props.briefingActive); }, [props.briefingActive]);
  useEffect(() => { categoryRef.current = props.category; refreshRef.current?.(); }, [props.category]);
  useEffect(() => { lifecycleRef.current = props.lifecycle; refreshRef.current?.(); }, [props.lifecycle]);
  useEffect(() => { timeRef.current = props.timeWindow; refreshRef.current?.(); }, [props.timeWindow]);

  useEffect(() => {
    userRef.current = props.userLocation ?? null;
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    updateUser(map, userRef.current);
    if (userRef.current) map.easeTo({ center: [userRef.current.longitude, userRef.current.latitude], zoom: 13.5, duration: 650, essential: true });
  }, [props.userLocation]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    updateSelected(map, props.selectedProject);
    const project = props.selectedProject;
    if (!project?.geometry) return;
    if (project.geometry.type === "Point") {
      map.easeTo({ center: project.geometry.coordinates as [number, number], zoom: props.briefingActive ? 13.2 : 14, duration: 600, essential: true });
      return;
    }
    const bounds = geometryBounds(project);
    if (bounds) map.fitBounds(bounds, { padding: { top: 100, right: 42, bottom: 260, left: 42 }, maxZoom: 14.5, duration: 600, essential: true });
  }, [props.selectedProject, props.briefingActive]);

  useEffect(() => {
    if (props.resetNonce) mapRef.current?.fitBounds(NAPA_SOLANO_BOUNDS, { padding: { top: 100, right: 18, bottom: 140, left: 18 }, duration: 700, essential: true });
  }, [props.resetNonce]);
  useEffect(() => {
    if (!props.restoreNonce || !props.restoreBounds) return;
    mapRef.current?.fitBounds([[props.restoreBounds.west, props.restoreBounds.south], [props.restoreBounds.east, props.restoreBounds.north]], { padding: { top: 100, right: 18, bottom: 140, left: 18 }, duration: 700, essential: true });
  }, [props.restoreBounds, props.restoreNonce]);

  useEffect(() => {
    let disposed = false;
    let abort: AbortController | null = null;
    let moveTimer: number | undefined;
    async function mount() {
      if (!containerRef.current) return;
      const maplibre = await import("maplibre-gl");
      if (disposed || !containerRef.current) return;
      maplibre.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");
      const saved = readSavedViewport();
      const map = new maplibre.Map({
        container: containerRef.current,
        style: "https://tiles.openfreemap.org/styles/liberty",
        ...(saved ? { center: saved.center, zoom: saved.zoom } : { bounds: NAPA_SOLANO_BOUNDS, fitBoundsOptions: { padding: { top: 100, right: 18, bottom: 140, left: 18 } } }),
        attributionControl: false,
      });
      mapRef.current = map;
      map.on("error", () => { if (!map.isStyleLoaded()) setMapState("error"); });
      map.addControl(new maplibre.NavigationControl({ showCompass: false }), "bottom-right");
      map.addControl(new maplibre.AttributionControl({ compact: true }), "bottom-left");

      async function refresh() {
        if (!map.isStyleLoaded()) return;
        abort?.abort(); abort = new AbortController();
        try {
          const loaded = await loadViewportTruth(map, timeRef.current, abort.signal);
          const consumerFeatures = loaded.features.filter((feature) => feature.properties?.project_type !== "environmental_review" || Number(feature.properties?.display_priority ?? 0) >= REVIEW_PRIORITY);
          const allProjects = consumerFeatures.map((feature) => loaded.projects.find((project) => project.id === String(feature.properties?.id ?? ""))).filter((project): project is MapProject => Boolean(project));
          const lifeBase = lifecycleRef.current === "current" ? allProjects.filter((project) => !["completed", "inactive"].includes(project.lifecycleStage)) : lifecycleRef.current === "all" ? allProjects : allProjects.filter((project) => project.lifecycleStage === lifecycleRef.current);
          const filtered = categoryRef.current === "all" ? lifeBase : lifeBase.filter((project) => project.consumerCategory === categoryRef.current);
          const ids = new Set(filtered.map((project) => project.id));
          const filteredFeatures = consumerFeatures.filter((feature) => ids.has(String(feature.properties?.id ?? "")));
          const priorityFloor = categoryRef.current === "all" && lifecycleRef.current === "current" ? minimumPriorityForZoom(map.getZoom()) : 0;
          const shapes = filteredFeatures.filter((feature) => feature.geometry?.type !== "Point" && Number(feature.properties?.display_priority ?? 0) >= priorityFloor);
          const points = filteredFeatures.filter((feature): feature is Feature<Point> => feature.geometry?.type === "Point");
          updateMapData(map, shapes, points);
          const center = map.getCenter();
          callbacks.current.onViewportChange?.({ bounds: loaded.viewport, zoom: map.getZoom(), center: { lng: center.lng, lat: center.lat }, projects: filtered, categoryCounts: categoryCounts(lifeBase), lifecycleCounts: lifecycleCounts(categoryRef.current === "all" ? allProjects : allProjects.filter((project) => project.consumerCategory === categoryRef.current)) });
          callbacks.current.onCoverageChange?.({ visibleMapped: filtered.length, mappedMatching: Number(loaded.data.metadata?.mapped_matching ?? filtered.length), locationPending: Number(loaded.data.metadata?.location_pending ?? 0), totalMatching: Number(loaded.data.metadata?.total_matching ?? filtered.length) });
        } catch (error) {
          if (error instanceof DOMException && error.name === "AbortError") return;
          console.error("Trackstar map refresh failed", error);
        }
      }
      refreshRef.current = () => void refresh();

      map.on("load", () => {
        setMapState("ready");
        installFinalLayers(map, userRef.current, (project) => callbacks.current.onSelectProject(project), (projects) => callbacks.current.onSelectProjects?.(projects));
        map.on("dragstart", () => callbacks.current.onUserInteraction?.());
        map.on("zoomstart", (event) => { if ((event as unknown as { originalEvent?: unknown }).originalEvent) callbacks.current.onUserInteraction?.(); });
        map.on("moveend", () => {
          if (selectedRef.current || briefingRef.current) return;
          const center = map.getCenter();
          try { window.localStorage.setItem(LAST_VIEWPORT_KEY, JSON.stringify({ center: [center.lng, center.lat], zoom: map.getZoom() })); } catch { /* optional */ }
          if (moveTimer !== undefined) window.clearTimeout(moveTimer);
          moveTimer = window.setTimeout(() => refreshRef.current?.(), 160);
        });
        void refresh();
      });
    }
    void mount();
    return () => { disposed = true; abort?.abort(); if (moveTimer !== undefined) window.clearTimeout(moveTimer); refreshRef.current = null; mapRef.current?.remove(); mapRef.current = null; };
  }, []);

  return <><div className="mapCanvas" ref={containerRef} />{mapState !== "ready" ? <div className={mapState === "error" ? "mapStatus error" : "mapStatus"} role="status">{mapState === "error" ? <><strong>Map could not load</strong><button onClick={() => window.location.reload()} type="button">Retry</button></> : "Loading Trackstar…"}</div> : null}</>;
}
