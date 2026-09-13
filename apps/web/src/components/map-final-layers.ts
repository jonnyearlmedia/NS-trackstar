import type { Feature, Geometry } from "geojson";
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

export const PROJECT_LAYERS = ["final-fill", "final-fill-u", "final-line", "final-line-u", "final-point-pins", "final-point-hit"];

type MarkerKind = "development" | "roads" | "utilities" | "places";

/**
 * The canonical category palette from docs/VISUAL_SYSTEM_V1.md. Every surface
 * that colours a category reads from here, because the same category must look
 * identical on the marker, the browse control and the project card. The
 * regional dots previously carried their own lighter variants of roads,
 * utilities and places, so a project visibly changed colour as you zoomed in.
 */
const markerColors: Record<MarkerKind, string> = {
  development: "#2f7f65",
  roads: "#d97616",
  utilities: "#18839b",
  places: "#5567cf",
};

const categoryColor = [
  "match",
  ["get", "consumer_category"],
  "development", markerColors.development,
  "roads", markerColors.roads,
  "utilities", markerColors.utilities,
  "places", markerColors.places,
  markerColors.development,
] as ExpressionSpecification;

const categoryMarker = [
  "match",
  ["get", "consumer_category"],
  "development", "trackstar-marker-development",
  "roads", "trackstar-marker-roads",
  "utilities", "trackstar-marker-utilities",
  "places", "trackstar-marker-places",
  "trackstar-marker-development",
] as ExpressionSpecification;


// Geometry of the pointer silhouette drawn by pinPath, in the marker image's
// own pixels. pinPath draws the rounded bubble between y=3 and y=33 and the
// tail tip at y=43, and clusterImage translates the whole path down by 2.
const MARKER_IMAGE_HEIGHT = 50;
const CLUSTER_BUBBLE_TOP = 3 + 2;
const CLUSTER_BUBBLE_BOTTOM = 33 + 2;
/** Distance from the icon's bottom edge up to the centre of the bubble. */
const CLUSTER_BUBBLE_CENTRE_FROM_BASE =
  MARKER_IMAGE_HEIGHT - (CLUSTER_BUBBLE_TOP + CLUSTER_BUBBLE_BOTTOM) / 2;
const CLUSTER_TEXT_SIZE = 11.5;

function pinPath(ctx: CanvasRenderingContext2D) {
  ctx.beginPath();
  ctx.moveTo(11, 3);
  ctx.lineTo(29, 3);
  ctx.quadraticCurveTo(37, 3, 37, 11);
  ctx.lineTo(37, 25);
  ctx.quadraticCurveTo(37, 33, 29, 33);
  ctx.lineTo(24.5, 33);
  ctx.lineTo(20, 43);
  ctx.lineTo(15.5, 33);
  ctx.lineTo(11, 33);
  ctx.quadraticCurveTo(3, 33, 3, 25);
  ctx.lineTo(3, 11);
  ctx.quadraticCurveTo(3, 3, 11, 3);
  ctx.closePath();
}

function drawCategoryGlyph(ctx: CanvasRenderingContext2D, kind: MarkerKind, color: string) {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 2;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";

  if (kind === "development") {
    ctx.strokeRect(14, 11, 12, 13);
    ctx.beginPath();
    ctx.moveTo(17, 14); ctx.lineTo(19, 14);
    ctx.moveTo(22, 14); ctx.lineTo(24, 14);
    ctx.moveTo(17, 18); ctx.lineTo(19, 18);
    ctx.moveTo(22, 18); ctx.lineTo(24, 18);
    ctx.moveTo(20, 24); ctx.lineTo(20, 20);
    ctx.stroke();
  } else if (kind === "roads") {
    ctx.beginPath();
    ctx.moveTo(15, 25); ctx.bezierCurveTo(17, 20, 17, 15, 18, 10);
    ctx.moveTo(25, 25); ctx.bezierCurveTo(23, 20, 23, 15, 22, 10);
    ctx.stroke();
    ctx.setLineDash([2.1, 2.1]);
    ctx.beginPath();
    ctx.moveTo(20, 24); ctx.lineTo(20, 11);
    ctx.stroke();
    ctx.setLineDash([]);
  } else if (kind === "utilities") {
    ctx.beginPath();
    ctx.moveTo(22, 9); ctx.lineTo(15.5, 19);
    ctx.lineTo(20, 19); ctx.lineTo(18.5, 26);
    ctx.lineTo(25, 16); ctx.lineTo(20.5, 16);
    ctx.closePath();
    ctx.fill();
  } else {
    ctx.beginPath();
    ctx.moveTo(14, 15); ctx.lineTo(20, 10); ctx.lineTo(26, 15);
    ctx.moveTo(15.5, 14); ctx.lineTo(15.5, 24); ctx.lineTo(24.5, 24); ctx.lineTo(24.5, 14);
    ctx.moveTo(18.5, 24); ctx.lineTo(18.5, 19); ctx.lineTo(21.5, 19); ctx.lineTo(21.5, 24);
    ctx.stroke();
  }
  ctx.restore();
}

function markerImage(kind: MarkerKind, color: string) {
  const pixelRatio = 2;
  const width = 40;
  const height = 46;
  const canvas = document.createElement("canvas");
  canvas.width = width * pixelRatio;
  canvas.height = height * pixelRatio;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) throw new Error("Trackstar marker canvas unavailable");
  ctx.scale(pixelRatio, pixelRatio);

  ctx.save();
  ctx.shadowColor = "rgba(24, 45, 56, 0.22)";
  ctx.shadowBlur = 6;
  ctx.shadowOffsetY = 2;
  ctx.fillStyle = "rgba(255,255,255,0.985)";
  ctx.strokeStyle = color;
  ctx.lineWidth = 2.4;
  pinPath(ctx);
  ctx.fill();
  ctx.stroke();
  ctx.restore();

  drawCategoryGlyph(ctx, kind, color);
  return ctx.getImageData(0, 0, canvas.width, canvas.height);
}

function clusterImage() {
  const pixelRatio = 2;
  const width = 44;
  const height = 50;
  const canvas = document.createElement("canvas");
  canvas.width = width * pixelRatio;
  canvas.height = height * pixelRatio;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) throw new Error("Trackstar cluster canvas unavailable");
  ctx.scale(pixelRatio, pixelRatio);
  ctx.translate(2, 2);
  ctx.save();
  ctx.shadowColor = "rgba(24, 45, 56, 0.20)";
  ctx.shadowBlur = 6;
  ctx.shadowOffsetY = 2;
  ctx.fillStyle = "rgba(255,255,255,0.99)";
  ctx.strokeStyle = "#0b67c7";
  ctx.lineWidth = 2.4;
  pinPath(ctx);
  ctx.fill();
  ctx.stroke();
  ctx.restore();
  return ctx.getImageData(0, 0, canvas.width, canvas.height);
}

function registerMarkerImages(map: MapLibreMap) {
  for (const kind of Object.keys(markerColors) as MarkerKind[]) {
    const name = `trackstar-marker-${kind}`;
    if (map.hasImage(name)) continue;
    map.addImage(name, markerImage(kind, markerColors[kind]), { pixelRatio: 2 });
  }
  if (!map.hasImage("trackstar-marker-cluster")) map.addImage("trackstar-marker-cluster", clusterImage(), { pixelRatio: 2 });
}

function projectFromRenderedFeature(feature: Feature): MapProject | null {
  const project = featureProject(feature);
  if (!project) return null;
  const original = feature.properties?.original_geometry;
  if (typeof original !== "string") return project;
  try {
    const geometry = JSON.parse(original) as Geometry;
    if (geometry && typeof geometry === "object" && typeof geometry.type === "string") return { ...project, geometry };
  } catch {
    // A marker still remains selectable even if a malformed helper property is encountered.
  }
  return project;
}

export function installFinalLayers(map: MapLibreMap, user: UserLocation | null, onOne: (project: MapProject) => void, onMany: (projects: MapProject[]) => void) {
  registerMarkerImages(map);
  map.addSource(SOURCES.mask, { type: "geojson", data: serviceMask() });
  map.addSource(SOURCES.edge, { type: "geojson", data: serviceEdge() });
  map.addSource(SOURCES.shapes, { type: "geojson", data: emptyCollection() });
  map.addSource(SOURCES.points, { type: "geojson", data: emptyCollection(), cluster: true, clusterMaxZoom: 13, clusterRadius: 58 });
  map.addSource(SOURCES.selected, { type: "geojson", data: emptyCollection() });
  map.addSource(SOURCES.user, { type: "geojson", data: userLocationFeature(user) });

  map.addLayer({ id: "final-mask", type: "fill", source: SOURCES.mask, paint: { "fill-color": "#dfe9ec", "fill-opacity": 0.44 } });
  map.addLayer({ id: "final-edge-shadow-wide", type: "line", source: SOURCES.edge, paint: { "line-color": "rgba(30,92,122,0.12)", "line-width": 14, "line-blur": 8, "line-opacity": 0.46 } });
  map.addLayer({ id: "final-edge-shadow-soft", type: "line", source: SOURCES.edge, paint: { "line-color": "rgba(11,103,199,0.18)", "line-width": 5, "line-blur": 3.5, "line-opacity": 0.5 } });
  map.addLayer({ id: "final-edge", type: "line", source: SOURCES.edge, paint: { "line-color": "rgba(11,103,199,0.52)", "line-width": 1.25, "line-opacity": 0.78 } });

  const exact = ["!=", ["get", "location_uncertain"], true] as ExpressionSpecification;
  const uncertain = ["==", ["get", "location_uncertain"], true] as ExpressionSpecification;
  const unclustered = ["!", ["has", "point_count"]] as ExpressionSpecification;

  // Project geometry is evidence/context, not the primary browse layer. Keep it
  // quiet until users zoom close; selected geometry remains fully emphasized.
  map.addLayer({
    id: "final-fill",
    type: "fill",
    source: SOURCES.shapes,
    minzoom: 13.6,
    filter: ["all", ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]], exact],
    paint: { "fill-color": categoryColor, "fill-opacity": ["interpolate", ["linear"], ["zoom"], 13.6, 0.035, 15, 0.08, 17, 0.14] },
  });
  map.addLayer({
    id: "final-fill-u",
    type: "fill",
    source: SOURCES.shapes,
    minzoom: 13.8,
    filter: ["all", ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]], uncertain],
    paint: { "fill-color": categoryColor, "fill-opacity": 0.035 },
  });
  map.addLayer({
    id: "final-line",
    type: "line",
    source: SOURCES.shapes,
    minzoom: 13.25,
    filter: exact,
    paint: {
      "line-color": categoryColor,
      "line-width": ["interpolate", ["linear"], ["zoom"], 13.25, 1.1, 15, 1.7, 17, 2.5],
      "line-opacity": ["interpolate", ["linear"], ["zoom"], 13.25, 0.24, 15, 0.36, 17, 0.52],
    },
  });
  map.addLayer({
    id: "final-line-u",
    type: "line",
    source: SOURCES.shapes,
    minzoom: 13.5,
    filter: uncertain,
    paint: { "line-color": categoryColor, "line-width": 1.4, "line-opacity": 0.24, "line-dasharray": [2, 2] },
  });

  // Clusters use the same pointer silhouette as projects so they feel like one
  // map language instead of MapLibre default bubbles dropped into Trackstar.
  //
  // The count has to sit in the middle of the bubble, not on its lower edge.
  // With "icon-anchor": "bottom" the icon's baseline is the map point, so the
  // bubble centre is CLUSTER_BUBBLE_CENTRE_FROM_BASE pixels above it, and
  // "text-offset" is measured in ems of "text-size". The offset must also track
  // "icon-size": a fixed em value drifts further off-centre as clusters grow.
  const clusterTextEm = (iconSize: number) =>
    -((CLUSTER_BUBBLE_CENTRE_FROM_BASE * iconSize) / CLUSTER_TEXT_SIZE);
  map.addLayer({
    id: "final-clusters",
    type: "symbol",
    source: SOURCES.points,
    filter: ["has", "point_count"],
    layout: {
      "icon-image": "trackstar-marker-cluster",
      "icon-size": ["step", ["get", "point_count"], 0.92, 10, 1, 50, 1.08, 200, 1.16],
      "icon-anchor": "bottom",
      "icon-allow-overlap": true,
      "text-field": ["get", "point_count_abbreviated"],
      "text-size": CLUSTER_TEXT_SIZE,
      "text-font": ["Noto Sans Regular"],
      "text-offset": ["step", ["get", "point_count"],
        ["literal", [0, clusterTextEm(0.92)]],
        10, ["literal", [0, clusterTextEm(1)]],
        50, ["literal", [0, clusterTextEm(1.08)]],
        200, ["literal", [0, clusterTextEm(1.16)]],
      ],
      "text-anchor": "center",
      "text-allow-overlap": true,
    },
    paint: { "text-color": "#174a70" },
  });

  // Regional view stays quiet. City/neighborhood scale progressively reveals
  // white pointer pins with category-colored iconography.
  map.addLayer({
    id: "final-point-overview-ring",
    type: "circle",
    source: SOURCES.points,
    maxzoom: 9.8,
    filter: unclustered,
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 6.5, 9.8, 8],
      "circle-color": "rgba(255,255,255,0.98)",
      "circle-stroke-color": "rgba(35,61,73,0.12)",
      "circle-stroke-width": 1,
    },
  });
  map.addLayer({
    id: "final-point-overview",
    type: "circle",
    source: SOURCES.points,
    maxzoom: 9.8,
    filter: unclustered,
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 4.5, 9.8, 5.8],
      "circle-color": categoryColor,
      "circle-opacity": ["case", uncertain, 0.55, 0.92],
      "circle-stroke-color": "rgba(255,255,255,0.96)",
      "circle-stroke-width": 1,
    },
  });
  map.addLayer({
    id: "final-point-pins",
    type: "symbol",
    source: SOURCES.points,
    minzoom: 9.55,
    filter: unclustered,
    layout: {
      "icon-image": categoryMarker,
      "icon-size": ["interpolate", ["linear"], ["zoom"], 9.55, 0.76, 12, 0.9, 15, 1.04],
      "icon-anchor": "bottom",
      "icon-allow-overlap": true,
      "icon-ignore-placement": false,
    },
    paint: { "icon-opacity": ["case", uncertain, 0.64, 1] },
  });

  // Invisible interaction halo. Visible markers carry meaning while the touch
  // target stays roughly 44–52px across on practical mobile zoom levels.
  map.addLayer({
    id: "final-point-hit",
    type: "circle",
    source: SOURCES.points,
    filter: unclustered,
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 22, 12, 24, 15, 26],
      "circle-color": "#000000",
      "circle-opacity": 0.001,
    },
  });

  map.addLayer({
    id: "final-labels",
    type: "symbol",
    source: SOURCES.points,
    minzoom: 14.15,
    filter: unclustered,
    layout: {
      "text-field": ["get", "name"],
      "text-size": 11.5,
      "text-font": ["Noto Sans Regular"],
      "text-offset": [0, 1.5],
      "text-anchor": "top",
      "text-max-width": 12,
      "text-allow-overlap": false,
    },
    paint: {
      "text-color": "#263b45",
      "text-halo-color": "rgba(255,255,255,.98)",
      "text-halo-width": 1.9,
    },
  });

  // Selection wakes the real geometry back up immediately.
  map.addLayer({ id: "final-selected-fill", type: "fill", source: SOURCES.selected, filter: ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]], paint: { "fill-color": "#0b67c7", "fill-opacity": 0.18 } });
  map.addLayer({ id: "final-selected-line", type: "line", source: SOURCES.selected, paint: { "line-color": "#0b67c7", "line-width": 3.2, "line-opacity": 0.95 } });
  map.addLayer({ id: "final-selected-point-halo", type: "circle", source: SOURCES.selected, filter: ["==", ["geometry-type"], "Point"], paint: { "circle-radius": 20, "circle-color": "rgba(11,103,199,.10)", "circle-stroke-color": "rgba(11,103,199,.20)", "circle-stroke-width": 2 } });
  map.addLayer({
    id: "final-selected-pin",
    type: "symbol",
    source: SOURCES.selected,
    filter: ["==", ["geometry-type"], "Point"],
    layout: { "icon-image": categoryMarker, "icon-size": 1.18, "icon-anchor": "bottom", "icon-allow-overlap": true },
  });
  map.addLayer({ id: "final-user-halo", type: "circle", source: SOURCES.user, paint: { "circle-radius": 13, "circle-color": "rgba(21,128,197,.16)" } });
  map.addLayer({ id: "final-user", type: "circle", source: SOURCES.user, paint: { "circle-radius": 6, "circle-color": "#1580c5", "circle-stroke-color": "#ffffff", "circle-stroke-width": 2.5 } });

  for (const layer of PROJECT_LAYERS) {
    map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; });
  }
  map.on("click", (event) => {
    const unique = new globalThis.Map<string, MapProject>();
    for (const feature of map.queryRenderedFeatures(event.point, { layers: PROJECT_LAYERS })) {
      const project = projectFromRenderedFeature(feature as Feature);
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
