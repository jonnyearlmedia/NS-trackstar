import type { Feature, Geometry, Point, Position } from "geojson";

type Coordinate = [number, number];

function coordinate(value: Position | undefined): Coordinate | null {
  if (!value || value.length < 2 || typeof value[0] !== "number" || typeof value[1] !== "number") return null;
  return [value[0], value[1]];
}

function distance(a: Coordinate, b: Coordinate) {
  const x = b[0] - a[0];
  const y = b[1] - a[1];
  return Math.hypot(x, y);
}

function pathLength(path: Position[]) {
  let total = 0;
  for (let index = 1; index < path.length; index += 1) {
    const a = coordinate(path[index - 1]);
    const b = coordinate(path[index]);
    if (a && b) total += distance(a, b);
  }
  return total;
}

function midpointAlong(path: Position[]): Coordinate | null {
  const points = path.map(coordinate).filter((value): value is Coordinate => Boolean(value));
  if (points.length === 0) return null;
  if (points.length === 1) return points[0];
  const lengths = points.slice(1).map((point, index) => distance(points[index], point));
  const total = lengths.reduce((sum, value) => sum + value, 0);
  if (total <= 0) return points[Math.floor(points.length / 2)];
  const target = total / 2;
  let walked = 0;
  for (let index = 0; index < lengths.length; index += 1) {
    const segment = lengths[index];
    if (walked + segment >= target && segment > 0) {
      const ratio = (target - walked) / segment;
      const a = points[index];
      const b = points[index + 1];
      return [a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio];
    }
    walked += segment;
  }
  return points[points.length - 1];
}

function ringArea(ring: Position[]) {
  let area = 0;
  for (let index = 0; index < ring.length; index += 1) {
    const a = coordinate(ring[index]);
    const b = coordinate(ring[(index + 1) % ring.length]);
    if (!a || !b) continue;
    area += a[0] * b[1] - b[0] * a[1];
  }
  return area / 2;
}

function ringCentroid(ring: Position[]): Coordinate | null {
  let crossSum = 0;
  let xSum = 0;
  let ySum = 0;
  for (let index = 0; index < ring.length; index += 1) {
    const a = coordinate(ring[index]);
    const b = coordinate(ring[(index + 1) % ring.length]);
    if (!a || !b) continue;
    const cross = a[0] * b[1] - b[0] * a[1];
    crossSum += cross;
    xSum += (a[0] + b[0]) * cross;
    ySum += (a[1] + b[1]) * cross;
  }
  if (Math.abs(crossSum) < 1e-12) return midpointAlong(ring);
  return [xSum / (3 * crossSum), ySum / (3 * crossSum)];
}

function average(points: Position[]): Coordinate | null {
  const valid = points.map(coordinate).filter((value): value is Coordinate => Boolean(value));
  if (!valid.length) return null;
  return [valid.reduce((sum, point) => sum + point[0], 0) / valid.length, valid.reduce((sum, point) => sum + point[1], 0) / valid.length];
}

export function representativeCoordinate(geometry: Geometry): Coordinate | null {
  switch (geometry.type) {
    case "Point":
      return coordinate(geometry.coordinates);
    case "MultiPoint":
      return average(geometry.coordinates);
    case "LineString":
      return midpointAlong(geometry.coordinates);
    case "MultiLineString": {
      const longest = [...geometry.coordinates].sort((a, b) => pathLength(b) - pathLength(a))[0];
      return longest ? midpointAlong(longest) : null;
    }
    case "Polygon":
      return geometry.coordinates[0] ? ringCentroid(geometry.coordinates[0]) : null;
    case "MultiPolygon": {
      const rings = geometry.coordinates.flatMap((polygon) => polygon[0] ? [polygon[0]] : []);
      const largest = rings.sort((a, b) => Math.abs(ringArea(b)) - Math.abs(ringArea(a)))[0];
      return largest ? ringCentroid(largest) : null;
    }
    case "GeometryCollection": {
      for (const child of geometry.geometries) {
        const result = representativeCoordinate(child);
        if (result) return result;
      }
      return null;
    }
    default:
      return null;
  }
}

export function markerFeature(feature: Feature): Feature<Point> | null {
  if (!feature.geometry) return null;
  const anchor = representativeCoordinate(feature.geometry);
  if (!anchor) return null;
  return {
    type: "Feature",
    geometry: { type: "Point", coordinates: anchor },
    properties: {
      ...(feature.properties ?? {}),
      original_geometry: JSON.stringify(feature.geometry),
    },
  };
}
