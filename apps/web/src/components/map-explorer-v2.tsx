"use client";

import type { Geometry } from "geojson";
import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";

import {
  MapCanvas,
  type MapCoverage,
  type MapProject,
  type TimeWindow,
} from "@/components/map-canvas";
import styles from "./map-explorer-v2.module.css";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const ORIENTATION_SEEN_KEY = "trackstar:orientation-seen:v1";

type AppView = "explore" | "updates";
type ExploreMode = "orientation" | "free";

type ProjectDetail = {
  id: string;
  name: string;
  project_type: string;
  geometry: Geometry | null;
  summary?: string | null;
  last_activity_at?: string | null;
  location: {
    accuracy: string;
    confidence: number | null;
  } | null;
  statuses: Record<string, string>;
  assertions: Array<{ field: string; value: unknown }>;
  sources: Array<{
    source_key: string;
    source_name: string;
    relationship_type: string;
    url: string | null;
  }>;
};

type ProjectEvent = {
  id: string;
  title: string;
  occurred_at: string | null;
  observed_at: string;
  summary?: string | null;
  event_type?: string;
};

type SearchResult = {
  id: string;
  name: string;
  project_type: string;
  geometry: Geometry | null;
  statuses: Record<string, string>;
  summary: string | null;
};

type ChangeEvent = ProjectEvent & {
  project_id: string;
  project_name: string;
  project_type: string;
  summary: string | null;
};

const CATEGORIES = [
  { key: "all", label: "All", longLabel: "All projects", icon: "◎", value: null },
  { key: "development", label: "Development", longLabel: "Development", icon: "▦", value: "municipal_development" },
  { key: "roads", label: "Roads", longLabel: "Roads & transit", icon: "↔", value: "transportation_project" },
  { key: "utilities", label: "Utilities", longLabel: "Utilities", icon: "⌁", value: "water_infrastructure" },
  { key: "places", label: "Places", longLabel: "Public places", icon: "◇", value: "public_works" },
] as const;

const ACTIVITY_OPTIONS: Array<{ label: string; value: TimeWindow }> = [
  { label: "Any time", value: "all" },
  { label: "Changed today", value: "today" },
  { label: "Changed recently", value: "week" },
  { label: "Coming up", value: "upcoming" },
];

function routeProjectId() {
  if (typeof window === "undefined") return null;
  return window.location.pathname.match(/^\/projects\/([^/]+)$/)?.[1] ?? null;
}

function consumerType(type: string) {
  if (type === "municipal_development") return "Development";
  if (type === "transportation_project") return "Roads & transit";
  if (type === "water_infrastructure") return "Utilities";
  if (type === "public_works") return "Public places";
  if (type === "environmental_review") return "Development";
  return "Local project";
}

function readableValue(value: unknown) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return new Intl.NumberFormat("en-US").format(value);
  if (typeof value === "string") return value.replaceAll("_", " ");
  return String(value);
}

function eventDate(value: string | null | undefined) {
  if (!value) return "Date not published";
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(new Date(value));
}

function eventHeadline(event: ProjectEvent) {
  if (event.event_type === "ceqa_document_received") return "New environmental review document filed";
  if (event.summary && event.summary !== event.title) return event.summary;
  return event.title.replaceAll("_", " ");
}

function primaryStage(statuses: Record<string, string>, fallback?: string | null) {
  const order = [
    "construction",
    "operations",
    "delivery_stage",
    "official_tracker_stage",
    "official_program_status",
    "building_permit",
    "planning",
    "entitlement",
    "environmental",
  ];
  for (const key of order) {
    const value = statuses[key];
    if (value) return readableValue(value);
  }
  return fallback ? readableValue(fallback) : null;
}

function projectSummary(detail: ProjectDetail | null, selected: MapProject | null) {
  const direct = detail?.summary?.trim();
  if (direct) return direct.length > 280 ? `${direct.slice(0, 277).trimEnd()}…` : direct;
  if (!selected) return "";
  const type = consumerType(selected.projectType).toLowerCase();
  return `A ${type} project in Napa–Solano. Open details for the official records and history Trackstar has collected.`;
}

function locationUncertain(detail: ProjectDetail | null, selected: MapProject | null) {
  if (selected?.locationUncertain) return true;
  if (!detail?.location) return false;
  if (detail.location.confidence !== null && detail.location.confidence < 0.75) return true;
  return !["exact_source_geometry", "exact_parcel", "exact_address"].includes(detail.location.accuracy);
}

function SearchIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m21 21-4.3-4.3m2.3-5.7a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z" /></svg>;
}
function LocationIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 21s6-5.2 6-11a6 6 0 1 0-12 0c0 5.8 6 11 6 11Z" /><circle cx="12" cy="10" r="2" /></svg>;
}
function FilterIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 7h16M7 12h10M10 17h4" /></svg>;
}
function ChevronIcon({ up = false }: { up?: boolean }) {
  return <svg aria-hidden="true" className={up ? styles.chevronUp : ""} viewBox="0 0 24 24"><path d="m7 10 5 5 5-5" /></svg>;
}
function ShareIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 16V3m0 0L7 8m5-5 5 5M5 13v7h14v-7" /></svg>;
}

export function MapExplorerV2({ initialProjectId }: { initialProjectId?: string }) {
  const [view, setView] = useState<AppView>("explore");
  const [exploreMode, setExploreMode] = useState<ExploreMode>("orientation");
  const [coverage, setCoverage] = useState<MapCoverage | null>(null);
  const [projectType, setProjectType] = useState<string | null>(null);
  const [timeWindow, setTimeWindow] = useState<TimeWindow>("all");
  const [resetNonce, setResetNonce] = useState(0);
  const [locateNonce, setLocateNonce] = useState(0);

  const [selected, setSelected] = useState<MapProject | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [events, setEvents] = useState<ProjectEvent[]>([]);
  const [detailState, setDetailState] = useState<"idle" | "loading" | "error">("idle");
  const [detailExpanded, setDetailExpanded] = useState(false);
  const [shareState, setShareState] = useState<"idle" | "copied">("idle");

  const [filterOpen, setFilterOpen] = useState(false);
  const [locationPromptOpen, setLocationPromptOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchState, setSearchState] = useState<"idle" | "loading" | "done" | "error">("idle");

  const [changes, setChanges] = useState<ChangeEvent[]>([]);
  const [changesState, setChangesState] = useState<"loading" | "done" | "error">("loading");

  const firstCoverageSeen = useRef(false);
  const suppressCoverageCollapse = useRef(false);

  const currentCategory = CATEGORIES.find((category) => category.value === projectType) ?? CATEGORIES[0];
  const activeFilterCount = Number(projectType !== null) + Number(timeWindow !== "all");
  const latestMeaningfulEvent = events.find((event) => event.event_type !== "project_discovered") ?? null;
  const stage = primaryStage(detail?.statuses ?? {}, selected?.deliveryStage);
  const summary = projectSummary(detail, selected);
  const uncertain = locationUncertain(detail, selected);
  const visibleCount = coverage?.visibleMapped ?? 0;

  const projectFacts = useMemo(() => {
    if (!detail) return [];
    const preferred = [
      "address",
      "location_description",
      "residential_units",
      "units",
      "project_units",
      "site_acres",
      "location_acres",
      "building_area_sqft",
      "developer",
      "applicant",
      "planned_completion",
      "completion_date",
    ];
    return preferred.flatMap((field) => {
      const match = detail.assertions.find((assertion) => assertion.field === field);
      return match ? [match] : [];
    }).slice(0, 4);
  }, [detail]);

  function rememberFreeExplore() {
    setExploreMode("free");
    if (typeof window !== "undefined") window.localStorage.setItem(ORIENTATION_SEEN_KEY, "1");
  }

  useEffect(() => {
    if (typeof window !== "undefined" && window.localStorage.getItem(ORIENTATION_SEEN_KEY) === "1") {
      setExploreMode("free");
    }
    const id = initialProjectId ?? routeProjectId();
    if (id) setSelectedProjectId(id);
  }, [initialProjectId]);

  useEffect(() => {
    function onPopState() {
      const id = routeProjectId();
      setSelectedProjectId(id);
      if (!id) {
        setSelected(null);
        setDetail(null);
        setEvents([]);
        setDetailExpanded(false);
      }
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
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
        if (!detailResponse.ok || !eventsResponse.ok) throw new Error("Project unavailable");
        const nextDetail = (await detailResponse.json()) as ProjectDetail;
        const nextEvents = (await eventsResponse.json()) as ProjectEvent[];
        setDetail(nextDetail);
        setEvents(nextEvents);
        setSelected({
          id: nextDetail.id,
          name: nextDetail.name,
          projectType: nextDetail.project_type,
          deliveryStage: nextDetail.statuses.delivery_stage ?? nextDetail.statuses.official_tracker_stage ?? null,
          geometry: nextDetail.geometry,
          lastActivityAt: nextDetail.last_activity_at,
          locationAccuracy: nextDetail.location?.accuracy ?? null,
          locationConfidence: nextDetail.location?.confidence ?? null,
          locationUncertain: locationUncertain(nextDetail, null),
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
    const query = searchQuery.trim();
    if (query.length < 2) {
      setSearchResults([]);
      setSearchState("idle");
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setSearchState("loading");
      fetch(`${API_BASE}/search/projects?${new URLSearchParams({ q: query, limit: "20" })}`, { signal: controller.signal })
        .then((response) => {
          if (!response.ok) throw new Error("Search failed");
          return response.json() as Promise<SearchResult[]>;
        })
        .then((results) => {
          setSearchResults(results);
          setSearchState("done");
        })
        .catch((error) => {
          if (error instanceof DOMException && error.name === "AbortError") return;
          setSearchState("error");
        });
    }, 180);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [searchOpen, searchQuery]);

  useEffect(() => {
    const controller = new AbortController();
    const updateWindow = timeWindow === "all" ? "week" : timeWindow;
    const params = new URLSearchParams({ window: updateWindow, limit: "80" });
    if (projectType) params.set("project_type", projectType);
    setChangesState("loading");
    fetch(`${API_BASE}/changes?${params}`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("Updates failed");
        return response.json() as Promise<ChangeEvent[]>;
      })
      .then((items) => {
        setChanges(items);
        setChangesState("done");
      })
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setChangesState("error");
      });
    return () => controller.abort();
  }, [projectType, timeWindow]);

  function handleCoverage(nextCoverage: MapCoverage) {
    setCoverage(nextCoverage);
    if (!firstCoverageSeen.current) {
      firstCoverageSeen.current = true;
      return;
    }
    if (suppressCoverageCollapse.current) {
      suppressCoverageCollapse.current = false;
      return;
    }
    if (view === "explore" && exploreMode === "orientation" && !selected) rememberFreeExplore();
  }

  function selectProject(project: MapProject) {
    setView("explore");
    setSelected(project);
    setSelectedProjectId(project.id);
    setDetail(null);
    setEvents([]);
    setDetailExpanded(false);
    window.history.pushState({}, "", `/projects/${project.id}`);
  }

  function clearSelection() {
    setSelected(null);
    setSelectedProjectId(null);
    setDetail(null);
    setEvents([]);
    setDetailExpanded(false);
    window.history.replaceState({}, "", "/");
  }

  function applyCategory(value: string | null) {
    suppressCoverageCollapse.current = true;
    setProjectType(value);
    rememberFreeExplore();
    clearSelection();
  }

  function clearAllFilters() {
    suppressCoverageCollapse.current = true;
    setProjectType(null);
    setTimeWindow("all");
    setFilterOpen(false);
    clearSelection();
  }

  function chooseSearchResult(result: SearchResult) {
    setSearchOpen(false);
    rememberFreeExplore();
    selectProject({
      id: result.id,
      name: result.name,
      projectType: result.project_type,
      deliveryStage: result.statuses.delivery_stage ?? result.statuses.official_tracker_stage ?? null,
      geometry: result.geometry,
    });
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
  }

  async function shareProject() {
    if (!selectedProjectId) return;
    const url = `${window.location.origin}/projects/${selectedProjectId}`;
    const title = detail?.name ?? selected?.name ?? "Trackstar project";
    if (navigator.share) {
      try {
        await navigator.share({ title, text: `${title} on Trackstar`, url });
        return;
      } catch {
        return;
      }
    }
    await navigator.clipboard.writeText(url);
    setShareState("copied");
    window.setTimeout(() => setShareState("idle"), 1400);
  }

  return (
    <section className={`trackstarApp ${styles.root}`} aria-label="Trackstar Napa Solano project map">
      <MapCanvas
        briefingActive={false}
        displayMode="projects"
        locateNonce={locateNonce}
        onCoverageChange={handleCoverage}
        onSelectProject={selectProject}
        projectType={projectType}
        resetNonce={resetNonce}
        selectedProject={selected}
        timeWindow={timeWindow}
      />
      <div className={`mapAtmosphere ${selected ? "selected" : ""}`} />

      <header className={styles.topBar}>
        <button
          aria-label="Reset to Napa and Solano"
          className={styles.brand}
          onClick={() => {
            clearSelection();
            setProjectType(null);
            setTimeWindow("all");
            setResetNonce((value) => value + 1);
            setExploreMode("orientation");
          }}
          type="button"
        >
          <span className={styles.brandMark}>⌁</span>
          <span><strong>Trackstar</strong><small>Napa · Solano</small></span>
        </button>
        <button className={styles.searchButton} onClick={() => setSearchOpen(true)} type="button">
          <SearchIcon />
          <span>Search address, road or project</span>
        </button>
      </header>

      {view === "explore" && !selected ? (
        <div className={styles.mapActions}>
          <button onClick={() => setLocationPromptOpen(true)} type="button"><LocationIcon /><span>Near me</span></button>
          <button className={activeFilterCount ? styles.activeAction : ""} onClick={() => setFilterOpen(true)} type="button"><FilterIcon /><span>Filters</span>{activeFilterCount ? <b>{activeFilterCount}</b> : null}</button>
        </div>
      ) : null}

      {view === "explore" && !selected && exploreMode === "orientation" ? (
        <section className={styles.orientationPanel} aria-label="Browse this area">
          <button className={styles.panelHandleButton} onClick={rememberFreeExplore} type="button" aria-label="Collapse browse panel"><span /></button>
          <div className={styles.areaHeading}>
            <div><p>EXPLORE</p><h2>Napa + Solano</h2><span>{coverage ? `${coverage.visibleMapped.toLocaleString()} mapped projects visible` : "Loading project coverage…"}</span></div>
            <button className={styles.collapseButton} onClick={rememberFreeExplore} type="button"><span>Map</span><ChevronIcon /></button>
          </div>
          <div className={styles.categoryGrid}>
            {CATEGORIES.filter((category) => category.key !== "all").map((category) => (
              <button
                className={projectType === category.value ? styles.categorySelected : ""}
                key={category.key}
                onClick={() => applyCategory(category.value)}
                type="button"
              >
                <i>{category.icon}</i>
                <span>{category.label}</span>
              </button>
            ))}
          </div>
          <div className={styles.panelFooter}>
            <button onClick={rememberFreeExplore} type="button">Explore map</button>
            <button onClick={() => setFilterOpen(true)} type="button"><FilterIcon /> More filters</button>
          </div>
        </section>
      ) : null}

      {view === "explore" && !selected && exploreMode === "free" ? (
        <section className={styles.freeExploreBar} aria-label="Map categories">
          <button className={styles.areaPill} onClick={() => setExploreMode("orientation")} type="button">
            <span><strong>This area</strong><small>{coverage ? `${visibleCount.toLocaleString()} showing` : "Loading"}</small></span>
            <ChevronIcon up />
          </button>
          <div className={styles.pillScroller}>
            {CATEGORIES.map((category) => (
              <button
                className={projectType === category.value ? styles.pillSelected : ""}
                key={category.key}
                onClick={() => applyCategory(category.value)}
                type="button"
              >
                {category.label}
              </button>
            ))}
            <button className={styles.filterPill} onClick={() => setFilterOpen(true)} type="button"><FilterIcon />{activeFilterCount ? activeFilterCount : ""}</button>
          </div>
        </section>
      ) : null}

      {view === "updates" ? (
        <section className={styles.updatesPanel}>
          <div className={styles.updatesHeader}>
            <div><p>UPDATES</p><h2>What changed</h2><span>{currentCategory.key === "all" ? "Recent official activity" : `${currentCategory.longLabel} · recent activity`}</span></div>
          </div>
          {changesState === "loading" ? <p className={styles.stateMessage}>Checking recent changes…</p> : null}
          {changesState === "error" ? <p className={styles.stateMessage}>Updates are temporarily unavailable.</p> : null}
          {changesState === "done" && changes.length === 0 ? (
            <div className={styles.emptyUpdates}><strong>No meaningful updates match this view.</strong><span>You can still explore current projects on the map.</span><button onClick={() => setView("explore")} type="button">View current projects</button></div>
          ) : null}
          <ol className={styles.updateList}>
            {changes.map((change) => (
              <li key={change.id}>
                <button onClick={() => selectProject({ id: change.project_id, name: change.project_name, projectType: change.project_type, deliveryStage: null, geometry: null })} type="button">
                  <small>{eventDate(change.occurred_at ?? change.observed_at)} · {consumerType(change.project_type)}</small>
                  <strong>{eventHeadline(change)}</strong>
                  <span>{change.project_name}</span>
                </button>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      <nav className={styles.bottomNav} aria-label="Trackstar sections">
        <button className={view === "explore" ? styles.navSelected : ""} onClick={() => setView("explore")} type="button">Explore</button>
        <button className={view === "updates" ? styles.navSelected : ""} onClick={() => { clearSelection(); setView("updates"); }} type="button">Updates</button>
      </nav>

      {view === "explore" && selected ? (
        <article className={`${styles.projectCard} ${detailExpanded ? styles.projectCardExpanded : ""}`}>
          <div className={styles.projectCardHandle}><span /></div>
          <div className={styles.projectTopLine}>
            <button className={styles.breadcrumb} onClick={clearSelection} type="button">‹ {consumerType(selected.projectType)}</button>
            <div className={styles.projectActions}>
              <button aria-label="Share project" onClick={() => void shareProject()} type="button"><ShareIcon /></button>
              <button aria-label="Close project" onClick={clearSelection} type="button">×</button>
            </div>
          </div>
          <div className={styles.projectScroll}>
            <div className={styles.projectTitleBlock}>
              <small>{consumerType(selected.projectType)}{stage ? ` · ${stage}` : ""}</small>
              <h2>{detail?.name ?? selected.name}</h2>
              {uncertain ? <span className={styles.approximateBadge}>Approximate location</span> : null}
            </div>
            {detailState === "loading" ? <p className={styles.projectLead}>Loading the official project details…</p> : null}
            {detailState === "error" ? <p className={styles.projectLead}>Trackstar could not load this project’s details right now.</p> : null}
            {detailState === "idle" ? <p className={styles.projectLead}>{summary}</p> : null}

            {latestMeaningfulEvent ? (
              <div className={styles.latestBlock}><small>LATEST</small><strong>{eventHeadline(latestMeaningfulEvent)}</strong><span>{eventDate(latestMeaningfulEvent.occurred_at ?? latestMeaningfulEvent.observed_at)}</span></div>
            ) : null}

            {!detail?.geometry && detailState === "idle" ? (
              <p className={styles.locationNotice}><strong>Location not mapped yet.</strong> Trackstar has records for this project but not enough reliable location information to place it precisely.</p>
            ) : uncertain ? (
              <p className={styles.locationNotice}>The map shows the best defensible project area from public records, not an exact footprint.</p>
            ) : null}

            {shareState === "copied" ? <p className={styles.copyNotice}>Link copied</p> : null}

            <button className={styles.detailsButton} onClick={() => setDetailExpanded((value) => !value)} type="button">{detailExpanded ? "Hide details" : "Details & official sources"}<ChevronIcon up={!detailExpanded} /></button>

            {detailExpanded ? (
              <div className={styles.detailLayer}>
                {projectFacts.length ? <section><h3>Key facts</h3><dl>{projectFacts.map((fact) => <div key={fact.field}><dt>{fact.field.replaceAll("_", " ")}</dt><dd>{readableValue(fact.value)}</dd></div>)}</dl></section> : null}
                {events.length ? <section><h3>Recent activity</h3><ol>{events.slice(0, 8).map((event) => <li key={event.id}><time>{eventDate(event.occurred_at ?? event.observed_at)}</time><strong>{eventHeadline(event)}</strong></li>)}</ol></section> : null}
                {detail?.sources.length ? <section><h3>Official sources</h3><div className={styles.sourceList}>{detail.sources.map((source, index) => <article key={`${source.source_key}-${index}`}><span><strong>{source.source_name}</strong><small>{readableValue(source.relationship_type)}</small></span>{source.url ? <a href={source.url} rel="noreferrer" target="_blank">Open ↗</a> : null}</article>)}</div></section> : null}
              </div>
            ) : null}
          </div>
        </article>
      ) : null}

      {filterOpen ? (
        <aside className={styles.scrim} onMouseDown={(event) => { if (event.currentTarget === event.target) setFilterOpen(false); }}>
          <section className={styles.modalSheet}>
            <header><div><p>FILTER MAP</p><h2>Show me…</h2></div><button aria-label="Close filters" onClick={() => setFilterOpen(false)} type="button">×</button></header>
            <section><h3>Category</h3><div className={styles.filterChoices}>{CATEGORIES.map((category) => <button className={projectType === category.value ? styles.filterChoiceSelected : ""} key={category.key} onClick={() => { suppressCoverageCollapse.current = true; setProjectType(category.value); }} type="button"><span>{category.longLabel}</span><i>{projectType === category.value ? "✓" : ""}</i></button>)}</div></section>
            <section><h3>Activity</h3><div className={styles.filterChoices}>{ACTIVITY_OPTIONS.map((option) => <button className={timeWindow === option.value ? styles.filterChoiceSelected : ""} key={option.value} onClick={() => { suppressCoverageCollapse.current = true; setTimeWindow(option.value); }} type="button"><span>{option.label}</span><i>{timeWindow === option.value ? "✓" : ""}</i></button>)}</div></section>
            <footer><button onClick={clearAllFilters} type="button">Clear all</button><button className={styles.doneButton} onClick={() => { setFilterOpen(false); rememberFreeExplore(); }} type="button">Show map</button></footer>
          </section>
        </aside>
      ) : null}

      {locationPromptOpen ? (
        <aside className={styles.scrim} onMouseDown={(event) => { if (event.currentTarget === event.target) setLocationPromptOpen(false); }}>
          <section className={`${styles.modalSheet} ${styles.locationSheet}`}>
            <header><div><p>NEAR ME</p><h2>See projects around you?</h2></div><button aria-label="Close" onClick={() => setLocationPromptOpen(false)} type="button">×</button></header>
            <p>Trackstar can use your location to center the map on nearby projects. If you say no, search and map browsing still work normally.</p>
            <button className={styles.locationConfirm} onClick={() => { setLocationPromptOpen(false); rememberFreeExplore(); setLocateNonce((value) => value + 1); }} type="button">Use my location</button>
          </section>
        </aside>
      ) : null}

      {searchOpen ? (
        <aside className={styles.searchOverlay} aria-label="Search Trackstar">
          <header><button aria-label="Close search" onClick={() => setSearchOpen(false)} type="button">‹</button><form onSubmit={submitSearch}><SearchIcon /><input autoFocus onChange={(event) => setSearchQuery(event.target.value)} placeholder="Search project, address, road or place" type="search" value={searchQuery} /></form></header>
          <div className={styles.searchBody}>
            {!searchQuery.trim() ? <div className={styles.searchHint}><strong>Find something you saw or heard about.</strong><span>Try a project name, road, address, business name, or place.</span></div> : null}
            {searchState === "loading" ? <p className={styles.stateMessage}>Searching…</p> : null}
            {searchState === "error" ? <p className={styles.stateMessage}>Search is temporarily unavailable.</p> : null}
            {searchState === "done" && searchResults.length === 0 ? <div className={styles.searchHint}><strong>No Trackstar match found.</strong><span>Try another name or address. This does not mean no project exists.</span></div> : null}
            <div className={styles.searchResults}>
              {searchResults.map((result) => <button key={result.id} onClick={() => chooseSearchResult(result)} type="button"><span><small>{consumerType(result.project_type)}</small><strong>{result.name}</strong>{result.summary ? <em>{result.summary}</em> : null}</span><b>›</b></button>)}
            </div>
          </div>
        </aside>
      ) : null}
    </section>
  );
}
