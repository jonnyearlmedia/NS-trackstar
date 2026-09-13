import type { FeatureCollection } from "geojson";

export const SERVICE_BOUNDS: [[number, number], [number, number]] = [[-122.65, 38.03], [-121.58, 38.88]];
export const INITIAL_CENTER: [number, number] = [-122.13, 38.37];
export const INITIAL_ZOOM = 9.4;

// Simplified union outline of Napa + Solano counties, derived from public county boundary data.
// This is used for the visible service-area mask and point-in-coverage checks.
export const SERVICE_RING: [number, number][] = [
  [-122.6274,38.6675],[-122.6447,38.6022],[-122.6208,38.5603],[-122.5698,38.53],[-122.5073,38.4573],[-122.4955,38.4235],[-122.3946,38.3047],[-122.4046,38.2814],[-122.3668,38.247],[-122.3504,38.2006],[-122.3679,38.1835],[-122.3662,38.1609],[-122.4068,38.1556],[-122.311,38.1086],[-122.2761,38.0662],[-122.242,38.0782],[-122.1985,38.0606],[-122.1881,38.0707],[-122.1526,38.0426],[-122.1313,38.0435],[-122.0734,38.1006],[-122.0622,38.1323],[-122.0033,38.1394],[-121.9843,38.1135],[-122.013,38.094],[-121.973,38.0734],[-121.9128,38.0832],[-121.8931,38.0536],[-121.8433,38.0769],[-121.802,38.0626],[-121.7065,38.1117],[-121.6856,38.1596],[-121.6624,38.1821],[-121.6154,38.1957],[-121.6024,38.2204],[-121.6045,38.2974],[-121.5933,38.3131],[-121.6937,38.3137],[-121.6951,38.5232],[-121.712,38.538],[-121.7836,38.5233],[-121.8494,38.5367],[-121.9403,38.5334],[-122.0115,38.4891],[-122.0574,38.5174],[-122.1033,38.5133],[-122.1399,38.6099],[-122.1761,38.6587],[-122.1983,38.6692],[-122.2021,38.6885],[-122.2242,38.7],[-122.2898,38.8393],[-122.3716,38.8447],[-122.3951,38.8642],[-122.4039,38.8556],[-122.3735,38.817],[-122.398,38.804],[-122.4639,38.7052],[-122.6274,38.6675]
];

export function serviceMask(): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: [{
      type: "Feature",
      properties: {},
      geometry: {
        type: "Polygon",
        coordinates: [
          [[-180,-85],[180,-85],[180,85],[-180,85],[-180,-85]],
          [...SERVICE_RING].reverse(),
        ],
      },
    }],
  };
}

export function serviceEdge(): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [SERVICE_RING] } }],
  };
}

export function isInsideServiceArea(point: { lng: number; lat: number }) {
  let inside = false;
  for (let i = 0, j = SERVICE_RING.length - 1; i < SERVICE_RING.length; j = i++) {
    const [xi, yi] = SERVICE_RING[i];
    const [xj, yj] = SERVICE_RING[j];
    const intersects = yi > point.lat !== yj > point.lat && point.lng < ((xj - xi) * (point.lat - yi)) / (yj - yi) + xi;
    if (intersects) inside = !inside;
  }
  return inside;
}

export function savedViewportIsReasonable(center: [number, number]) {
  const [lng, lat] = center;
  return lng >= -122.9 && lng <= -121.4 && lat >= 37.85 && lat <= 39.0;
}
