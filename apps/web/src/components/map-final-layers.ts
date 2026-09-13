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

export const PROJECT_LAYERS = ["final-fill","final-fill-u","final-line","final-line-u","final-points","final-points-u"];

const categoryColor = ["match",["get","consumer_category"],"development","#d9ff61","roads","#ffb45f","utilities","#59edc5","places","#67d7ff","#d9ff61"] as ExpressionSpecification;

export function installFinalLayers(map: MapLibreMap, user: UserLocation | null, onOne: (project: MapProject) => void, onMany: (projects: MapProject[]) => void) {
  map.addSource(SOURCES.mask, { type: "geojson", data: serviceMask() });
  map.addSource(SOURCES.edge, { type: "geojson", data: serviceEdge() });
  map.addSource(SOURCES.shapes, { type: "geojson", data: emptyCollection() });
  map.addSource(SOURCES.points, { type: "geojson", data: emptyCollection(), cluster: true, clusterMaxZoom: 13, clusterRadius: 42 });
  map.addSource(SOURCES.selected, { type: "geojson", data: emptyCollection() });
  map.addSource(SOURCES.user, { type: "geojson", data: userLocationFeature(user) });

  map.addLayer({ id: "final-mask", type: "fill", source: SOURCES.mask, paint: { "fill-color": "#020705", "fill-opacity": 0.61 } });
  map.addLayer({ id: "final-edge-shadow-wide", type: "line", source: SOURCES.edge, paint: { "line-color": "rgba(0,0,0,0.46)", "line-width": 16, "line-blur": 8, "line-opacity": 0.48 } });
  map.addLayer({ id: "final-edge-shadow-soft", type: "line", source: SOURCES.edge, paint: { "line-color": "rgba(217,255,97,0.24)", "line-width": 5, "line-blur": 3.5, "line-opacity": 0.52 } });
  map.addLayer({ id: "final-edge", type: "line", source: SOURCES.edge, paint: { "line-color": "rgba(217,255,97,0.52)", "line-width": 1.15, "line-opacity": 0.82 } });

  const exact = ["!=", ["get", "location_uncertain"], true] as ExpressionSpecification;
  const uncertain = ["==", ["get", "location_uncertain"], true] as ExpressionSpecification;
  const unclustered = ["!", ["has", "point_count"]] as ExpressionSpecification;

  map.addLayer({ id: "final-fill", type: "fill", source: SOURCES.shapes, filter: ["all", ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]], exact], paint: { "fill-color": categoryColor, "fill-opacity": ["interpolate", ["linear"], ["zoom"], 7, 0.05, 11, 0.16, 15, 0.28] } });
  map.addLayer({ id: "final-fill-u", type: "fill", source: SOURCES.shapes, filter: ["all", ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]], uncertain], paint: { "fill-color": categoryColor, "fill-opacity": 0.07 } });
  map.addLayer({ id: "final-line", type: "line", source: SOURCES.shapes, filter: exact, paint: { "line-color": categoryColor, "line-width": ["interpolate", ["linear"], ["zoom"], 7, 1, 13, 2.4, 17, 4], "line-opacity": 0.75 } });
  map.addLayer({ id: "final-line-u", type: "line", source: SOURCES.shapes, filter: uncertain, paint: { "line-color": categoryColor, "line-width": 2, "line-opacity": 0.58, "line-dasharray": [2, 2] } });
  map.addLayer({ id: "final-clusters", type: "circle", source: SOURCES.points, filter: ["has", "point_count"], paint: { "circle-color": "#101a16", "circle-radius": ["step", ["get", "point_count"], 13, 10, 17, 50, 21, 200, 25], "circle-stroke-color": "#d9ff61", "circle-stroke-width": 1.7, "circle-opacity": 0.97 } });
  map.addLayer({ id: "final-cluster-count", type: "symbol", source: SOURCES.points, filter: ["has", "point_count"], layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 10, "text-font": ["Noto Sans Regular"] }, paint: { "text-color": "#f5ffd0" } });
  map.addLayer({ id: "final-points", type: "circle", source: SOURCES.points, filter: ["all", unclustered, exact], paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 4, 12, 5.7, 15, 7.2], "circle-color": categoryColor, "circle-opacity": 0.96, "circle-stroke-color": "#101416", "circle-stroke-width": 1.35 } });
  map.addLayer({ id: "final-points-u", type: "circle", source: SOURCES.points, filter: ["all", unclustered, uncertain], paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 4, 12, 5.7, 15, 7.2], "circle-color": categoryColor, "circle-opacity": 0.58, "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.2 } });
  map.addLayer({ id: "final-labels", type: "symbol", source: SOURCES.points, minzoom: 11.8, filter: unclustered, layout: { "text-field": ["get", "name"], "text-size": 10.5, "text-font": ["Noto Sans Regular"], "text-offset": [0, 1.1], "text-anchor": "top", "text-max-width": 12, "text-allow-overlap": false }, paint: { "text-color": "#eef5f0", "text-halo-color": "rgba(5,11,8,.92)", "text-halo-width": 1.4 } });

  map.addLayer({ id: "final-selected-fill", type: "fill", source: SOURCES.selected, filter: ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]], paint: { "fill-color": "#d9ff61", "fill-opacity": 0.34 } });
  map.addLayer({ id: "final-selected-line", type: "line", source: SOURCES.selected, paint: { "line-color": "#f5ffc9", "line-width": 3, "line-opacity": 1 } });
  map.addLayer({ id: "final-selected-point", type: "circle", source: SOURCES.selected, filter: ["==", ["geometry-type"], "Point"], paint: { "circle-radius": 8, "circle-color": "#d9ff61", "circle-stroke-color": "#ffffff", "circle-stroke-width": 2.5 } });
  map.addLayer({ id: "final-user", type: "circle", source: SOURCES.user, paint: { "circle-radius": 5.5, "circle-color": "#67d7ff", "circle-stroke-color": "#ffffff", "circle-stroke-width": 2 } });

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