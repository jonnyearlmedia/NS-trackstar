"use client";

import { useEffect, useRef } from "react";

const NAPA_SOLANO_CENTER: [number, number] = [-122.2708, 38.218];

export function MapCanvas() {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let disposed = false;
    let map: import("maplibre-gl").Map | undefined;

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
    }

    void mount();
    return () => {
      disposed = true;
      map?.remove();
    };
  }, []);

  return <div className="mapCanvas" ref={containerRef} />;
}
