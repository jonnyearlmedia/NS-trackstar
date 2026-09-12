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
  { label: "All", value: null },
  { label: "Development", value: "municipal_development" },
  { label: "Environmental", value: "environmental_review" },
  { label: "Public works", value: "public_works" },
  { label: "Water", value: "water_infrastructure" },
  { label: "Transportation", value: "transportation_project" },
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

function SearchIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m21 21-4.35-4.35m2.35-5.65a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z" /></svg>
  );
}

function PulseIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M3 12h4l2.2-6 4.1 12 2.1-6H21" /></svg>
  );
}

function LayersIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m12 3 9 5-9 5-9-5 9-5Zm-9 10 9 5 9-5M3 18l9 5 9-5" /></svg>
  );
}

export function MapExplorer({ initialProjectId }: { initialProjectId?: string }) {
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
  const [searchState, setSearchState] = useState<"idle" | "loading" | "done" | "error">("idle");

  useEffect(() => {
    const projectId = initialProjectId ?? new URLSearchParams(window.location.search).get("project");
    if (projectId) setSelectedProjectId(projectId);
  }, [initialProjectId]);

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
        if (!detailResponse.ok || !eventsResponse.ok) throw new Error("Project evidence could not be loaded");
        const nextDetail: ProjectDetail = await detailResponse.json();
        setDetail(nextDetail);
        setEvents(await eventsResponse.json());
        setSelected({
          id: nextDetail.id,
          name: nextDetail.name,
          projectType: nextDetail.project_type,
          deliveryStage: nextDetail.statuses.delivery_stage ?? nextDetail.statuses.official_tracker_stage ?? null,
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
    window.history.replaceState({}, "", `/projects/${project.id}`);
  }

  function clearSelection() {
    setSelected(null);
    setSelectedProjectId(null);
    setDetail(null);
    setEvents([]);
    window.history.replaceState({}, "", "/");
  }

  async function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = searchQuery.trim();
    if (query.length < 2) return;
    setSearchState("loading");
    try {
      const response = await fetch(`${API_BASE}/search/projects?${new URLSearchParams({ q: query })}`);
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
      deliveryStage: result.statuses.delivery_stage ?? result.statuses.official_tracker_stage ?? null,
      geometry: result.geometry,
    });
    setSearchOpen(false);
  }

  function changeWindow(next: TimeWindow) {
    setTimeWindow(next);
    clearSelection();
  }

  const assertions = detail?.assertions.filter((assertion) => !assertion.field.startsWith("status.")) ?? [];
  const activeFilter = FILTERS.find((filter) => filter.value === timeWindow)?.label ?? "This Week";

  return (
    <section className="trackstarApp" aria-label="NS Trackstar Napa and Solano intelligence map">
      <MapCanvas
        onSelectProject={selectProject}
        projectType={projectType}
        selectedProject={selected}
        timeWindow={timeWindow}
      />
      <div className={selected ? "mapAtmosphere selected" : "mapAtmosphere"} />

      <header className="floatingHeader">
        <div className="brandLockup">
          <span className="brandMark"><PulseIcon /></span>
          <div>
            <strong>Trackstar</strong>
            <small>Napa · Solano</small>
          </div>
        </div>
        <a className="liveStatus" href="/admin/sources"><i /> Live intelligence</a>
      </header>

      <button className="heroSearch" onClick={() => setSearchOpen(true)} type="button">
        <SearchIcon />
        <span>Search projects, roads, permits…</span>
        <kbd>⌘ K</kbd>
      </button>

      <nav className="timeRail" aria-label="Time filters">
        {FILTERS.map((filter) => (
          <button
            aria-pressed={filter.value === timeWindow}
            className={filter.value === timeWindow ? "timeChip active" : "timeChip"}
            key={filter.value}
            onClick={() => changeWindow(filter.value)}
            type="button"
          >
            {filter.label}
          </button>
        ))}
      </nav>

      <div className="categoryRail" aria-label="Project categories">
        <span className="categoryLead"><LayersIcon /></span>
        {CATEGORIES.map((category) => (
          <button
            aria-pressed={category.value === projectType}
            className={category.value === projectType ? "categoryChip active" : "categoryChip"}
            key={category.label}
            onClick={() => setProjectType(category.value)}
            type="button"
          >
            {category.label}
          </button>
        ))}
      </div>

      <div className="modeDock" role="group" aria-label="Map display mode">
        <button className={view === "map" ? "active" : ""} onClick={() => setView("map")} type="button">
          <span>Map</span>
        </button>
        <button className={view === "changes" ? "active" : ""} onClick={() => setView("changes")} type="button">
          <span>Updates</span>
          {changes.length ? <b>{Math.min(changes.length, 99)}</b> : null}
        </button>
      </div>

      {view === "changes" ? (
        <section className="updatesSheet" aria-label="Recent project changes">
          <div className="sheetHandle" />
          <header className="updatesHeader">
            <div>
              <p className="cardMeta">{activeFilter.toUpperCase()}</p>
              <h2>What changed</h2>
            </div>
            <button className="roundClose" aria-label="Return to map" onClick={() => setView("map")} type="button">×</button>
          </header>
          {changesState === "loading" ? <p className="emptyMessage">Loading source-backed updates…</p> : null}
          {changesState === "error" ? <p className="errorMessage">Updates are temporarily unavailable.</p> : null}
          {changesState === "done" && changes.length === 0 ? <p className="emptyMessage">No changes match these filters yet.</p> : null}
          <ol className="updateList">
            {changes.map((change) => (
              <li key={change.id}>
                <button
                  onClick={() => {
                    setSelectedProjectId(change.project_id);
                    setView("map");
                  }}
                  type="button"
                >
                  <span className="updateMeta">
                    <time dateTime={change.occurred_at ?? change.observed_at}>{eventDate(change.occurred_at ?? change.observed_at)}</time>
                    <em>{readableValue(change.event_type).replaceAll("_", " ")}</em>
                  </span>
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
        <aside className="searchOverlay" id="project-search" aria-label="Project search">
          <div className="searchOverlayInner">
            <header className="searchOverlayHeader">
              <div>
                <p className="cardMeta">SEARCH THE REGION</p>
                <h2>Find anything changing</h2>
              </div>
              <button aria-label="Close search" className="roundClose" onClick={() => setSearchOpen(false)} type="button">×</button>
            </header>
            <form className="spotlightSearch" onSubmit={submitSearch} role="search">
              <SearchIcon />
              <input
                autoFocus
                id="project-query"
                minLength={2}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Project, business, address, permit, APN, road…"
                type="search"
                value={searchQuery}
              />
              <button disabled={searchQuery.trim().length < 2 || searchState === "loading"} type="submit">
                {searchState === "loading" ? "…" : "Go"}
              </button>
            </form>
            <p className="searchHint">Try “Dutch Bros”, “Highway 12”, a permit number, or an address.</p>
            <div className="searchResults" aria-live="polite">
              {searchState === "done" && searchResults.length === 0 ? <p className="emptyMessage">No source-backed projects matched that search.</p> : null}
              {searchState === "error" ? <p className="errorMessage">Search is temporarily unavailable.</p> : null}
              {searchResults.map((result) => {
                const stage = result.statuses.delivery_stage ?? result.statuses.official_tracker_stage;
                return (
                  <button className="searchResult" key={result.id} onClick={() => chooseSearchResult(result)} type="button">
                    <span className="searchResultTopline">
                      <strong>{result.name}</strong>
                      {stage ? <em>{readableValue(stage).replaceAll("_", " ")}</em> : null}
                    </span>
                    {result.summary ? <span>{result.summary}</span> : null}
                    <small>{result.matched_on.replaceAll("_", " ")}{result.geometry ? " · mapped" : " · location pending"}</small>
                  </button>
                );
              })}
            </div>
          </div>
        </aside>
      ) : null}

      {view === "map" && selected ? (
        <article className="projectSheet" aria-live="polite">
          <div className="sheetHandle" />
          <div className="projectSheetTopline">
            <p className="cardMeta">SOURCE-BACKED PROJECT</p>
            <button className="roundClose small" aria-label="Close project" onClick={clearSelection} type="button">×</button>
          </div>
          <div className="projectTitleRow">
            <h2>{detail?.name ?? selected.name}</h2>
            {selected.deliveryStage ? <span className="stagePill">{selected.deliveryStage.replaceAll("_", " ")}</span> : null}
          </div>
          {!selected.geometry ? <p className="locationNotice">Source location is known, but precise geometry is not available yet.</p> : null}
          {detail?.location && detail.location.accuracy !== "exact_source_geometry" ? (
            <p className="locationNotice">Location confidence: {readableValue(detail.location.accuracy).replaceAll("_", " ")} · {readableValue(detail.location.method).replaceAll("_", " ")}</p>
          ) : null}
          {detailState === "error" ? <p className="errorMessage">Project evidence could not be loaded.</p> : null}
          {assertions.length ? (
            <dl className="facts">
              {assertions.slice(0, 4).map((assertion) => (
                <div key={`${assertion.field}-${JSON.stringify(assertion.value)}`}>
                  <dt>{readableField(assertion.field)}</dt>
                  <dd>{readableValue(assertion.value)}</dd>
                </div>
              ))}
            </dl>
          ) : <p className="detailLoading">{detailState === "loading" ? "Loading official project details…" : "No project facts loaded."}</p>}
          {events.length ? (
            <section className="timeline" aria-labelledby="project-timeline-heading">
              <h3 id="project-timeline-heading">Latest activity</h3>
              <ol>
                {events.slice(0, 4).map((projectEvent) => (
                  <li key={projectEvent.id}>
                    <time dateTime={projectEvent.occurred_at ?? projectEvent.observed_at}>{eventDate(projectEvent.occurred_at ?? projectEvent.observed_at)}</time>
                    <strong>{projectEvent.title}</strong>
                  </li>
                ))}
              </ol>
            </section>
          ) : null}
          {detail?.sources.length ? (
            <details className="sourceDrawer">
              <summary>Official evidence <span>{detail.sources.length}</span></summary>
              <ul>
                {detail.sources.map((source) => (
                  <li key={`${source.source_key}-${source.relationship_type}-${source.url}`}>
                    {source.url ? <a href={source.url} rel="noreferrer" target="_blank">{source.source_name}</a> : <span>{source.source_name}</span>}
                    <small>{source.relationship_type.replaceAll("_", " ")}</small>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </article>
      ) : null}

      {view === "map" && !selected ? (
        <div className="discoveryHint"><i /> <span><strong>{activeFilter}</strong> · tap a highlighted project</span></div>
      ) : null}
    </section>
  );
}
