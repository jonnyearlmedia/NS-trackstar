import type { Feature } from "geojson";
import type { ExpressionSpecification, GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";

import {
  emptyCollection,
  featureProject,
  userLocationFeature,
  type MapProject,
  type UserLocation,
} from "./map-final-model";
import { serviceEdge, serviceMask } from "./service-area";

export const SOURCES = {
  shapes: "trackstar-final-shapes",
  points: "trackstar-final-points",
  selected: "trackstar-final-selected",
  user: "trackstar-final-user",
  mask: "trackstar-final-mask",
  edge: "trackstar-final-edge",
} as const;

export const PROJECT_LAYERS = ["final-fill","final-fill-u","final-line","final-line-u","final-point-hit"];

const categoryColor = [
  "match",
  ["get", "consumer_category"],
  "development", "#2f7f65",
  "roads", "#e58a2b",
  "utilities", "#238ca4",
  "places", "#5d70d8",
  "#2f7f65",
] as ExpressionSpecification;

export function installFinalLayers(map: MapLibreMap, user: UserLocation | null, onOne: (project: MapProject) => void, onMany: (projects: MapProject[]) => void) {
  map.addSource(SOURCES.mask, { type: "geojson", data: serviceMask() });
  map.addSource(SOURCES.edge, { type: "geojson", data: serviceEdge() });
  map.addSource(SOURCES.shapes, { type: "geojson", data: emptyCollection() });
  map.addSource(SOURCES.points, { type: "geojson", data: emptyCollection(), cluster: true, clusterMaxZoom: 13, clusterRadius: 50 });
  map.addSource(SOURCES.selected, { type: "geojson", data: emptyCollection() });
  map.addSource(SOURCES.user, { type: "geojson", data: userLocationFeature(user) });

  map.addLayer({ id: "final-mask", type: "fill", source: SOURCES.mask, paint: { "fill-color": "#dfe9ec", "fill-opacity": 0.44 } });
  map.addLayer({ id: "final-edge-shadow-wide", type: "line", source: SOURCES.edge, paint: { "line-color": "rgba(30,92,122,0.12)", "line-width": 14, "line-blur": 8, "line-opacity": 0.46 } });
  map.addLayer({ id: "final-edge-shadow-soft", type: "line", source: SOURCES.edge, paint: { "line-color": "rgba(11,103,199,0.18)", "line-width": 5, "line-blur": 3.5, "line-opacity": 0.5 } });
  map.addLayer({ id: "final-edge", type: "line", source: SOURCES.edge, paint: { "line-color": "rgba(11,103,199,0.52)", "line-width": 1.25, "line-opacity": 0.78 } });

  const exact = ["!=", ["get", "location_uncertain"], true] as ExpressionSpecification;
  const uncertain = ["==", ["get", "location_uncertain"], true] as ExpressionSpecification;
  const unclustered = ["!", ["has", "point_count"]] as ExpressionSpecification;

  map.addLayer({ id: "final-fill", type: "fill", source: SOURCES.shapes, filter: ["all", ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]], exact], paint: { "fill-color": categoryColor, "fill-opacity": ["interpolate", ["linear"], ["zoom"], 7, 0.05, 11, 0.14, 15, 0.24] } });
  map.addLayer({ id: "final-fill-u", type: "fill", source: SOURCES.shapes, filter: ["all", ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]], uncertain], paint: { "fill-color": categoryColor, "fill-opacity": 0.06 } });
  map.addLayer({ id: "final-line", type: "line", source: SOURCES.shapes, filter: exact, paint: { "line-color": categoryColor, "line-width": ["interpolate", ["linear"], ["zoom"], 7, 1, 13, 2.2, 17, 3.6], "line-opacity": 0.74 } });
  map.addLayer({ id: "final-line-u", type: "line", source: SOURCES.shapes, filter: uncertain, paint: { "line-color": categoryColor, "line-width": 2, "line-opacity": 0.5, "line-dasharray": [2, 2] } });

  map.addLayer({
    id: "final-clusters",
    type: "circle",
    source: SOURCES.points,
    filter: ["has", "point_count"],
    paint: {
      "circle-color": "#ffffff",
      "circle-radius": ["step", ["get", "point_count"], 17, 10, 20, 50, 24, 200, 28],
      "circle-stroke-color": "#0b67c7",
      "circle-stroke-width": 2.4,
      "circle-opacity": 0.98,
      "circle-stroke-opacity": 0.96,
    },
  });
  map.addLayer({
    id: "final-cluster-count",
    type: "symbol",
    source: SOURCES.points,
    filter: ["has", "point_count"],
    layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 11.5, "text-font": ["Noto Sans Regular"] },
    paint: { "text-color": "#174a70" },
  });

  // A soft white ring separates project markers from busy basemap detail.
  map.addLayer({
    id: "final-point-ring",
    type: "circle",
    source: SOURCES.points,
    filter: unclustered,
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 8, 12, 10, 15, 12],
      "circle-color": "rgba(255,255,255,0.97)",
      "circle-stroke-color": "rgba(35,61,73,0.14)",
      "circle-stroke-width": 1,
    },
  });
  map.addLayer({
    id: "final-points",
    type: "circle",
    source: SOURCES.points,
    filter: ["all", unclustered, exact],
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 5.5, 12, 7.2, 15, 8.8],
      "circle-color": categoryColor,
      "circle-opacity": 1,
      "circle-stroke-color": "rgba(255,255,255,0.95)",
      "circle-stroke-width": 1.3,
    },
  });
  map.addLayer({
    id: "final-points-u",
    type: "circle",
    source: SOURCES.points,
    filter: ["all", unclustered, uncertain],
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 5.5, 12, 7.2, 15, 8.8],
      "circle-color": categoryColor,
      "circle-opacity": 0.68,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1.5,
    },
  });

  // Invisible interaction halo. The marker stays visually restrained while the
  // tappable/queryable area is much more forgiving on touch screens.
  map.addLayer({
    id: "final-point-hit",
    type: "circle",
    source: SOURCES.points,
    filter: unclustered,
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 14, 12, 17, 15, 20],
      "circle-color": "#000000",
      "circle-opacity": 0.001,
    },
  });

  map.addLayer({
    id: "final-labels",
    type: "symbol",
    source: SOURCES.points,
    minzoom: 12.2,
    filter: unclustered,
    layout: {
      "text-field": ["get", "name"],
      "text-size": 11.5,
      "text-font": ["Noto Sans Regular"],
      "text-offset": [0, 1.45],
      "text-anchor": "top",
      "text-max-width": 12,
      "text-allow-overlap": false,
    },
    paint: {
      "text-color": "#263b45",
      "text-halo-color": "rgba(255,255,255,.96)",
      "text-halo-width": 1.8,
    },
  });

  map.addLayer({ id: "final-selected-fill", type: "fill", source: SOURCES.selected, filter: ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]], paint: { "fill-color": "#0b67c7", "fill-opacity": 0.20 } });
  map.addLayer({ id: "final-selected-line", type: "line", source: SOURCES.selected, paint: { "line-color": "#0b67c7", "line-width": 3.2, "line-opacity": 1 } });
  map.addLayer({ id: "final-selected-point-halo", type: "circle", source: SOURCES.selected, filter: ["==", ["geometry-type"], "Point"], paint: { "circle-radius": 15, "circle-color": "rgba(11,103,199,.14)", "circle-stroke-color": "rgba(11,103,199,.22)", "circle-stroke-width": 2 } });
  map.addLayer({ id: "final-selected-point", type: "circle", source: SOURCES.selected, filter: ["==", ["geometry-type"], "Point"], paint: { "circle-radius": 9, "circle-color": "#0b67c7", "circle-stroke-color": "#ffffff", "circle-stroke-width": 3 } });
  map.addLayer({ id: "final-user-halo", type: "circle", source: SOURCES.user, paint: { "circle-radius": 13, "circle-color": "rgba(21,128,197,.16)" } });
  map.addLayer({ id: "final-user", type: "circle", source: SOURCES.user, paint: { "circle-radius": 6, "circle-color": "#1580c5", "circle-stroke-color": "#ffffff", "circle-stroke-width": 2.5 } });

  for (const layer of PROJECT_LAYERS) {
    map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; });
  }
  map.on("click", (event) => {
    const unique = new globalThis.Map<string, MapProject>();
    for (const feature of map.queryRenderedFeatures(event.point, { layers: PROJECT_LAYERS })) {
      const project = featureProject(feature as Feature);
      if (project) unique.set(project.id, project);
    }
    const projects = [...unique.values()];
    if (projects.length > 1) onMany(projects); else if (projects[0]) onOne(projects[0]);
  });
  map.on("click", "final-clusters", async (event) => {
    const feature = event.features?.[0];
    const clusterId = Number(feature?.properties?.cluster_id);
    if (!Number.isFinite(clusterId) || feature?.geometry.type !== "Point") return;
    const source = map.getSource(SOURCES.points) as GeoJSONSource;
    map.easeTo({ center: feature.geometry.coordinates as [number, number], zoom: await source.getClusterExpansionZoom(clusterId), duration: 500, essential: true });
  });
}

export function updateMapData(map: MapLibreMap, shapes: Feature[], points: Feature[]) {
  (map.getSource(SOURCES.shapes) as GeoJSONSource)?.setData({ type: "FeatureCollection", features: shapes });
  (map.getSource(SOURCES.points) as GeoJSONSource)?.setData({ type: "FeatureCollection", features: points });
}
export function updateSelected(map: MapLibreMap, project: MapProject | null) {
  const source = map.getSource(SOURCES.selected) as GeoJSONSource | undefined;
  if (!source) return;
  if (!project?.geometry) { source.setData(emptyCollection()); return; }
  source.setData({ type: "Feature", geometry: project.geometry, properties: { id: project.id, name: project.name, consumer_category: project.consumerCategory } });
}
export function updateUser(map: MapLibreMap, user: UserLocation | null) {
  (map.getSource(SOURCES.user) as GeoJSONSource | undefined)?.setData(userLocationFeature(user));
}
