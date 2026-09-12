"use client";

import type { Geometry } from "geojson";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { MapCanvas, type MapProject, type TimeWindow } from "@/components/map-canvas";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const FILTERS: { label: string; value: TimeWindow }[] = [
  { label: "Today", value: "today" },
  { label: "This Week", value: "week" },
  { label: "Upcoming", value: "upcoming" },
  { label: "All", value: "all" },
];
const CATEGORIES = [
  { label: "All projects", value: null },
  { label: "Development", value: "municipal_development" },
  { label: "Environmental", value: "environmental_review" },
] as const;

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
  geometry: Geometry | null;
  location: {
    method: string;
    source: string;
    accuracy: string;
    accuracy_meters: number | null;
    confidence: number | null;
  } | null;
  statuses: Record<string, string>;
  assertions: Assertion[];
  sources: Array<{
    source_key: string;
    source_name: string;
    relationship_type: string;
    confidence: number;
    evidence: Record<string, unknown>;
    url: string | null;
  }>;
};

type ProjectEvent = {
  id: string;
  title: string;
  occurred_at: string | null;
  observed_at: string;
};

type ChangeEvent = ProjectEvent & {
  project_id: string;
  project_name: string;
  project_type: string;
  event_type: string;
  summary: string | null;
};

type SearchResult = {
  id: string;
  name: string;
  project_type: string;
  geometry: Geometry | null;
  statuses: Record<string, string>;
  summary: string | null;
  matched_on: string;
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

function eventDate(value: string | null) {
  if (!value) return "Date not published";
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" })
    .format(new Date(value));
}

export function MapExplorer() {
  const [timeWindow, setTimeWindow] = useState<TimeWindow>("week");
  const [projectType, setProjectType] = useState<string | null>(null);
  const [view, setView] = useState<"map" | "changes">("map");
  const [changes, setChanges] = useState<ChangeEvent[]>([]);
  const [changesState, setChangesState] = useState<"loading" | "done" | "error">("loading");
  const [selected, setSelected] = useState<MapProject | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [events, setEvents] = useState<ProjectEvent[]>([]);
  const [detailState, setDetailState] = useState<"idle" | "loading" | "error">("idle");
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchState, setSearchState] = useState<"idle" | "loading" | "done" | "error">(
    "idle",
  );

  useEffect(() => {
    const initialProjectId = new URLSearchParams(window.location.search).get("project");
    if (initialProjectId) setSelectedProjectId(initialProjectId);
  }, []);

  useEffect(() => {
    if (!selectedProjectId) return;
    const controller = new AbortController();

    async function loadProject() {
      setDetailState("loading");
      try {
        const [detailResponse, eventsResponse] = await Promise.all([
          fetch(`${API_BASE}/projects/${selectedProjectId}`, { signal: controller.signal }),
          fetch(`${API_BASE}/projects/${selectedProjectId}/events`, { signal: controller.signal }),
        ]);
        if (!detailResponse.ok || !eventsResponse.ok) {
          throw new Error("Project evidence could not be loaded");
        }
        const nextDetail: ProjectDetail = await detailResponse.json();
        setDetail(nextDetail);
        setEvents(await eventsResponse.json());
        setSelected({
          id: nextDetail.id,
          name: nextDetail.name,
          projectType: nextDetail.project_type,
          deliveryStage:
            nextDetail.statuses.delivery_stage ??
            nextDetail.statuses.official_tracker_stage ??
            null,
          geometry: nextDetail.geometry,
        });
        setDetailState("idle");
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setDetailState("error");
      }
    }

    void loadProject();
    return () => controller.abort();
  }, [selectedProjectId]);

  useEffect(() => {
    if (!searchOpen) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setSearchOpen(false);
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [searchOpen]);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ window: timeWindow, limit: "100" });
    if (projectType) params.set("project_type", projectType);
    setChangesState("loading");
    fetch(`${API_BASE}/changes?${params}`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Changes API returned ${response.status}`);
        return response.json() as Promise<ChangeEvent[]>;
      })
      .then((nextChanges) => {
        setChanges(nextChanges);
        setChangesState("done");
      })
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setChangesState("error");
      });
    return () => controller.abort();
  }, [projectType, timeWindow]);

  function selectProject(project: MapProject) {
    setSelected(project);
    setSelectedProjectId(project.id);
    setDetail(null);
    setEvents([]);
    const url = new URL(window.location.href);
    url.searchParams.set("project", project.id);
    window.history.replaceState({}, "", url);
  }

  async function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = searchQuery.trim();
    if (query.length < 2) return;
    setSearchState("loading");
    try {
      const response = await fetch(
        `${API_BASE}/search/projects?${new URLSearchParams({ q: query })}`,
      );
      if (!response.ok) throw new Error(`Search API returned ${response.status}`);
      setSearchResults(await response.json());
      setSearchState("done");
    } catch {
      setSearchState("error");
    }
  }

  function chooseSearchResult(result: SearchResult) {
    selectProject({
      id: result.id,
      name: result.name,
      projectType: result.project_type,
      deliveryStage:
        result.statuses.delivery_stage ?? result.statuses.official_tracker_stage ?? null,
      geometry: result.geometry,
    });
    setSearchOpen(false);
  }

  function changeWindow(next: TimeWindow) {
    setTimeWindow(next);
    setSelected(null);
    setSelectedProjectId(null);
    setDetail(null);
    setEvents([]);
    const url = new URL(window.location.href);
    url.searchParams.delete("project");
    window.history.replaceState({}, "", url);
  }

  const assertions =
    detail?.assertions.filter((assertion) => !assertion.field.startsWith("status.")) ?? [];
  const activeFilter = FILTERS.find((filter) => filter.value === timeWindow)?.label ?? "This Week";

  return (
    <>
      <header className="topbar">
        <div>
          <p className="eyebrow">NAPA · SOLANO</p>
          <h1>NS Trackstar</h1>
        </div>
        <div className="topbarActions">
          <a className="healthLink" href="/admin/sources">Source health</a>
          <button
            aria-controls="project-search"
            aria-expanded={searchOpen}
            className="searchButton"
            onClick={() => setSearchOpen(true)}
            type="button"
          >
            Search
          </button>
        </div>
      </header>

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
        <MapCanvas
          onSelectProject={selectProject}
          projectType={projectType}
          selectedProject={selected}
          timeWindow={timeWindow}
        />
        <div className="mapShade" />

        <div className="mapToolbar" aria-label="Map display controls">
          <div className="categoryFilters" role="group" aria-label="Project category">
            {CATEGORIES.map((category) => (
              <button
                aria-pressed={category.value === projectType}
                className={category.value === projectType ? "toolButton active" : "toolButton"}
                key={category.label}
                onClick={() => setProjectType(category.value)}
                type="button"
              >
                {category.label}
              </button>
            ))}
          </div>
          <div className="viewToggle" role="group" aria-label="Map or change feed">
            <button className={view === "map" ? "toolButton active" : "toolButton"} onClick={() => setView("map")} type="button">Map</button>
            <button className={view === "changes" ? "toolButton active" : "toolButton"} onClick={() => setView("changes")} type="button">Changes</button>
          </div>
        </div>

        {view === "changes" ? (
          <section className="changeFeed" aria-label="Recent project changes">
            <header>
              <p className="cardMeta">{activeFilter.toUpperCase()}</p>
              <h2>What changed</h2>
            </header>
            {changesState === "loading" ? <p className="emptyMessage">Loading source-backed changes…</p> : null}
            {changesState === "error" ? <p className="errorMessage">The change feed is temporarily unavailable.</p> : null}
            {changesState === "done" && changes.length === 0 ? <p className="emptyMessage">No semantic changes match these filters yet.</p> : null}
            <ol>
              {changes.map((change) => (
                <li key={change.id}>
                  <button
                    onClick={() => {
                      setSelectedProjectId(change.project_id);
                      setView("map");
                    }}
                    type="button"
                  >
                    <span><time dateTime={change.occurred_at ?? change.observed_at}>{eventDate(change.occurred_at ?? change.observed_at)}</time><em>{readableValue(change.event_type).replaceAll("_", " ")}</em></span>
                    <strong>{change.project_name}</strong>
                    <b>{change.title}</b>
                    {change.summary ? <small>{change.summary}</small> : null}
                  </button>
                </li>
              ))}
            </ol>
          </section>
        ) : null}

        {searchOpen ? (
          <aside className="searchPanel" id="project-search" aria-label="Project search">
            <div className="searchPanelHeader">
              <div>
                <p className="cardMeta">DETERMINISTIC SEARCH</p>
                <h2>Find what is changing</h2>
              </div>
              <button
                aria-label="Close search"
                className="iconButton"
                onClick={() => setSearchOpen(false)}
                type="button"
              >
                ×
              </button>
            </div>
            <form className="searchForm" onSubmit={submitSearch} role="search">
              <label htmlFor="project-query">Project, business, address, permit, case, APN, or road</label>
              <div>
                <input
                  autoFocus
                  id="project-query"
                  minLength={2}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder="Try Dutch Bros or Highway 12"
                  type="search"
                  value={searchQuery}
                />
                <button disabled={searchQuery.trim().length < 2 || searchState === "loading"} type="submit">
                  {searchState === "loading" ? "Searching…" : "Search"}
                </button>
              </div>
            </form>

            <div className="searchResults" aria-live="polite">
              {searchState === "done" && searchResults.length === 0 ? (
                <p className="emptyMessage">No source-backed projects matched that search.</p>
              ) : null}
              {searchState === "error" ? (
                <p className="errorMessage">Search is temporarily unavailable. Please try again.</p>
              ) : null}
              {searchResults.map((result) => {
                const stage =
                  result.statuses.delivery_stage ?? result.statuses.official_tracker_stage;
                return (
                  <button
                    className="searchResult"
                    key={result.id}
                    onClick={() => chooseSearchResult(result)}
                    type="button"
                  >
                    <span className="searchResultTopline">
                      <strong>{result.name}</strong>
                      {stage ? <em>{readableValue(stage).replaceAll("_", " ")}</em> : null}
                    </span>
                    {result.summary ? <span>{result.summary}</span> : null}
                    <small>
                      Matched {result.matched_on.replaceAll("_", " ")}
                      {result.geometry ? " · mapped geometry" : " · location not mapped yet"}
                    </small>
                  </button>
                );
              })}
            </div>
          </aside>
        ) : null}

        {view === "map" ? <article className="projectCard" aria-live="polite">
          {selected ? (
            <>
              <div className="cardTopline">
                <p className="cardMeta">SOURCE-BACKED PROJECT</p>
                {selected.deliveryStage ? (
                  <span className="stagePill">
                    {selected.deliveryStage.replaceAll("_", " ")}
                  </span>
                ) : null}
              </div>
              <h2>{detail?.name ?? selected.name}</h2>
              {!selected.geometry ? (
                <p className="locationNotice">Location is described by the source but has not been mapped precisely.</p>
              ) : null}
              {detail?.location && detail.location.accuracy !== "exact_source_geometry" ? (
                <p className="locationNotice">
                  Map location: {readableValue(detail.location.accuracy).replaceAll("_", " ")} · {readableValue(detail.location.method).replaceAll("_", " ")}
                </p>
              ) : null}
              {detailState === "error" ? (
                <p className="errorMessage">Project evidence could not be loaded.</p>
              ) : null}
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
                <p>{detailState === "loading" ? "Loading source-backed project details…" : "No project facts loaded."}</p>
              )}
              {events.length ? (
                <section className="timeline" aria-labelledby="project-timeline-heading">
                  <h3 id="project-timeline-heading">Timeline</h3>
                  <ol>
                    {events.slice(0, 4).map((projectEvent) => (
                      <li key={projectEvent.id}>
                        <time dateTime={projectEvent.occurred_at ?? projectEvent.observed_at}>
                          {eventDate(projectEvent.occurred_at ?? projectEvent.observed_at)}
                        </time>
                        <strong>{projectEvent.title}</strong>
                      </li>
                    ))}
                  </ol>
                </section>
              ) : null}
              {detail?.sources.length ? (
                <details className="sourceDrawer">
                  <summary>Government sources <span>{detail.sources.length}</span></summary>
                  <ul>
                    {detail.sources.map((source) => (
                      <li key={`${source.source_key}-${source.relationship_type}-${source.url}`}>
                        {source.url ? (
                          <a href={source.url} rel="noreferrer" target="_blank">{source.source_name}</a>
                        ) : <span>{source.source_name}</span>}
                        <small>{source.relationship_type.replaceAll("_", " ")}</small>
                      </li>
                    ))}
                  </ul>
                </details>
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
        </article> : null}
      </section>
    </>
  );
}
