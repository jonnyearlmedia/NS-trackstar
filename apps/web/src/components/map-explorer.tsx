"use client";

import { useEffect, useState } from "react";

import { MapCanvas, type MapProject, type TimeWindow } from "@/components/map-canvas";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const FILTERS: { label: string; value: TimeWindow }[] = [
  { label: "Today", value: "today" },
  { label: "This Week", value: "week" },
  { label: "Upcoming", value: "upcoming" },
  { label: "All", value: "all" },
];

type Assertion = {
  field: string;
  value: unknown;
  authority_type: string;
  confidence: number;
};

type ProjectDetail = {
  id: string;
  name: string;
  project_type: string;
  statuses: Record<string, string>;
  assertions: Assertion[];
};

type ProjectEvent = {
  id: string;
  title: string;
  occurred_at: string | null;
  observed_at: string;
};

function readableField(field: string) {
  return field.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function readableValue(value: unknown) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return new Intl.NumberFormat("en-US").format(value);
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

export function MapExplorer() {
  const [timeWindow, setTimeWindow] = useState<TimeWindow>("week");
  const [selected, setSelected] = useState<MapProject | null>(null);
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [events, setEvents] = useState<ProjectEvent[]>([]);

  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();

    async function loadProject() {
      const [detailResponse, eventsResponse] = await Promise.all([
        fetch(`${API_BASE}/projects/${selected!.id}`, { signal: controller.signal }),
        fetch(`${API_BASE}/projects/${selected!.id}/events`, { signal: controller.signal }),
      ]);
      if (!detailResponse.ok || !eventsResponse.ok) return;
      setDetail(await detailResponse.json());
      setEvents(await eventsResponse.json());
    }

    void loadProject();
    return () => controller.abort();
  }, [selected]);

  function changeWindow(next: TimeWindow) {
    setTimeWindow(next);
    setSelected(null);
    setDetail(null);
    setEvents([]);
  }

  const assertions =
    detail?.assertions.filter((assertion) => !assertion.field.startsWith("status.")) ?? [];
  const activeFilter = FILTERS.find((filter) => filter.value === timeWindow)?.label ?? "This Week";

  return (
    <>
      <nav className="filters" aria-label="Time filters">
        {FILTERS.map((filter) => (
          <button
            aria-pressed={filter.value === timeWindow}
            className={filter.value === timeWindow ? "filter active" : "filter"}
            key={filter.value}
            onClick={() => changeWindow(filter.value)}
            type="button"
          >
            {filter.label}
          </button>
        ))}
      </nav>

      <section className="mapStage" aria-label="Napa and Solano intelligence map">
        <MapCanvas onSelectProject={setSelected} timeWindow={timeWindow} />
        <div className="mapShade" />

        <article className="projectCard" aria-live="polite">
          {selected ? (
            <>
              <div className="cardTopline">
                <p className="cardMeta">SOURCE-BACKED PROJECT</p>
                {selected.deliveryStage ? (
                  <span className="stagePill">{selected.deliveryStage}</span>
                ) : null}
              </div>
              <h2>{detail?.name ?? selected.name}</h2>
              {assertions.length ? (
                <dl className="facts">
                  {assertions.slice(0, 4).map((assertion) => (
                    <div key={`${assertion.field}-${JSON.stringify(assertion.value)}`}>
                      <dt>{readableField(assertion.field)}</dt>
                      <dd>{readableValue(assertion.value)}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p>Loading source-backed project details…</p>
              )}
              {events[0] ? (
                <div className="latestEvent">
                  <span>Latest tracked event</span>
                  <strong>{events[0].title}</strong>
                </div>
              ) : null}
            </>
          ) : (
            <>
              <p className="cardMeta">{activeFilter.toUpperCase()} · NAPA + SOLANO</p>
              <h2>Tap a highlighted project</h2>
              <p>
                The map is now filtered by activity window and loads official project geometry
                in the current view with the underlying government evidence attached.
              </p>
              <div className="cardFooter">
                <span>Real geometry</span>
                <span>Source-backed</span>
                <span>Change-aware</span>
              </div>
            </>
          )}
        </article>
      </section>
    </>
  );
}
