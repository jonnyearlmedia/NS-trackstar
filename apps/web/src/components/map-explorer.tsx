"use client";

import type { Geometry } from "geojson";
import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, FormEvent, PointerEvent as ReactPointerEvent } from "react";

import {
  MapCanvas,
  type MapCoverage,
  type MapDisplayMode,
  type MapProject,
  type TimeWindow,
} from "@/components/map-canvas";

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
const SNAP_ORDER = ["peek", "half", "full"] as const;

type SheetSnap = (typeof SNAP_ORDER)[number];
type DetailTab = "overview" | "activity" | "evidence";
type AppView = "map" | "list" | "changes";

type Assertion = {
  field: string;
  value: unknown;
  authority_type: string;
  confidence: number;
  source_url?: string | null;
  observed_at?: string | null;
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
  summary?: string | null;
  event_type?: string;
  significance?: number;
};

type ChangeEvent = ProjectEvent & {
  project_id: string;
  project_name: string;
  project_type: string;
  event_type: string;
  summary: string | null;
};

type CatalogProject = {
  id: string;
  name: string;
  project_type: string;
  last_activity_at: string | null;
  has_geometry: boolean;
  delivery_stage: string | null;
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

type ProjectContext = {
  id: string;
  name: string;
  importance_score: number;
  summary: string | null;
  aliases: Array<{ alias: string; alias_type: string | null }>;
  relationships: Array<{
    relationship_type: string;
    confidence: number;
    evidence: Record<string, unknown>;
    direction: "incoming" | "outgoing";
    project_id: string;
    project_name: string;
    project_type: string;
    mapped: boolean;
  }>;
  matches: Array<{
    proposed_relationship: string;
    state: string;
    score: number;
    signals: Record<string, unknown>;
    project_id: string;
    project_name: string;
  }>;
};

type BriefingItem = {
  id: string;
  name: string;
  project_type: string;
  last_activity_at: string | null;
  importance_score: number;
  briefing_score: number;
  geometry: Geometry;
  statuses: Record<string, string>;
  summary: string | null;
  source_count: number;
  event: {
    id: string;
    title: string;
    summary: string | null;
    event_type: string;
    occurred_at: string | null;
    observed_at: string | null;
    significance: number;
  } | null;
};

function readableField(field: string) {
  return field.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function readableValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return new Intl.NumberFormat("en-US").format(value);
  if (typeof value === "string") return value.replaceAll("_", " ");
  if (Array.isArray(value)) return value.map(readableValue).join(", ");
  return JSON.stringify(value);
}

function eventDate(value: string | null | undefined) {
  if (!value) return "Date not published";
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" })
    .format(new Date(value));
}

function locationLabel(detail: ProjectDetail | null) {
  if (!detail?.location) return detail?.geometry ? "Mapped from source geometry" : "Location pending";
  const accuracy = detail.location.accuracy;
  if (accuracy === "exact_source_geometry") return "Exact source geometry";
  if (accuracy === "exact_parcel") return "Exact parcel footprint";
  if (accuracy === "exact_address") return "Exact address";
  if (accuracy === "street_segment") return "Published corridor";
  if (accuracy === "intersection") return "Intersection-level location";
  if (accuracy === "approximate_area") return "Approximate published area";
  return readableValue(accuracy);
}

function SearchIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m21 21-4.35-4.35m2.35-5.65a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z" /></svg>;
}
function PulseIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M3 12h4l2.2-6 4.1 12 2.1-6H21" /></svg>;
}
function LayersIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m12 3 9 5-9 5-9-5 9-5Zm-9 10 9 5 9-5M3 18l9 5 9-5" /></svg>;
}
function ShareIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 16V3m0 0L7 8m5-5 5 5M5 13v7h14v-7" /></svg>;
}
function PlayIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m8 5 11 7-11 7V5Z" /></svg>;
}
function PauseIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M8 5v14M16 5v14" /></svg>;
}
function routeProjectId() {
  if (typeof window === "undefined") return null;
  const match = window.location.pathname.match(/^\/projects\/([^/]+)$/);
  return match?.[1] ?? new URLSearchParams(window.location.search).get("project");
}

export function MapExplorer({ initialProjectId }: { initialProjectId?: string }) {
  const [timeWindow, setTimeWindow] = useState<TimeWindow>("all");
  const [projectType, setProjectType] = useState<string | null>(null);
  const [view, setView] = useState<AppView>("map");
  const [mapDisplay, setMapDisplay] = useState<MapDisplayMode>("projects");
  const [resetNonce, setResetNonce] = useState(0);
  const [coverage, setCoverage] = useState<MapCoverage | null>(null);
  const [catalog, setCatalog] = useState<CatalogProject[]>([]);
  const [catalogState, setCatalogState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [changes, setChanges] = useState<ChangeEvent[]>([]);
  const [changesState, setChangesState] = useState<"loading" | "done" | "error">("loading");
  const [selected, setSelected] = useState<MapProject | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [events, setEvents] = useState<ProjectEvent[]>([]);
  const [context, setContext] = useState<ProjectContext | null>(null);
  const [detailState, setDetailState] = useState<"idle" | "loading" | "error">("idle");
  const [detailTab, setDetailTab] = useState<DetailTab>("overview");
  const [sheetSnap, setSheetSnap] = useState<SheetSnap>("half");
  const [sheetDrag, setSheetDrag] = useState(0);
  const dragStartY = useRef<number | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchState, setSearchState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [briefingItems, setBriefingItems] = useState<BriefingItem[]>([]);
  const [briefingIndex, setBriefingIndex] = useState(0);
  const [briefingActive, setBriefingActive] = useState(false);
  const [briefingPaused, setBriefingPaused] = useState(false);
  const [briefingLoading, setBriefingLoading] = useState(false);
  const [briefingWindow, setBriefingWindow] = useState<"today" | "week">("today");
  const [shareState, setShareState] = useState<"idle" | "copied">("idle");

  useEffect(() => {
    const projectId = initialProjectId ?? routeProjectId();
    if (projectId) setSelectedProjectId(projectId);
  }, [initialProjectId]);

  useEffect(() => {
    function syncRouteSelection() {
      const projectId = routeProjectId();
      setSelectedProjectId(projectId);
      if (!projectId) {
        setSelected(null);
        setDetail(null);
        setEvents([]);
        setContext(null);
      }
    }
    window.addEventListener("popstate", syncRouteSelection);
    return () => window.removeEventListener("popstate", syncRouteSelection);
  }, []);

  useEffect(() => {
    function handleShortcut(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen(true);
      }
      if (event.key === "Escape") {
        if (searchOpen) setSearchOpen(false);
        else if (briefingActive) setBriefingActive(false);
      }
    }
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [briefingActive, searchOpen]);

  useEffect(() => {
    if (!selectedProjectId) return;
    const controller = new AbortController();
    async function loadProject() {
      setDetailState("loading");
      try {
        const [detailResponse, eventsResponse, contextResponse] = await Promise.all([
          fetch(`${API_BASE}/projects/${selectedProjectId}`, { signal: controller.signal }),
          fetch(`${API_BASE}/projects/${selectedProjectId}/events`, { signal: controller.signal }),
          fetch(`${API_BASE}/projects/${selectedProjectId}/context`, { signal: controller.signal }),
        ]);
        if (!detailResponse.ok || !eventsResponse.ok) throw new Error("Project evidence could not be loaded");
        const nextDetail = (await detailResponse.json()) as ProjectDetail;
        setDetail(nextDetail);
        setEvents(await eventsResponse.json());
        setContext(contextResponse.ok ? await contextResponse.json() : null);
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

  useEffect(() => {
    if (view !== "list") return;
    const controller = new AbortController();
    const params = new URLSearchParams({ window: timeWindow });
    if (projectType) params.set("project_type", projectType);
    setCatalogState("loading");
    fetch(`${API_BASE}/projects?${params}`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Project catalog returned ${response.status}`);
        return response.json() as Promise<CatalogProject[]>;
      })
      .then((projects) => {
        setCatalog(projects);
        setCatalogState("done");
      })
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setCatalogState("error");
      });
    return () => controller.abort();
  }, [projectType, timeWindow, view]);

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
      fetch(`${API_BASE}/search/projects?${new URLSearchParams({ q: query, limit: "20" })}`, {
        signal: controller.signal,
      })
        .then((response) => {
          if (!response.ok) throw new Error(`Search API returned ${response.status}`);
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
    }, 220);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [searchOpen, searchQuery]);

  useEffect(() => {
    if (!briefingActive || briefingPaused || briefingItems.length < 2) return;
    if (briefingIndex >= briefingItems.length - 1) return;
    const timer = window.setTimeout(() => setBriefingIndex((index) => index + 1), 6500);
    return () => window.clearTimeout(timer);
  }, [briefingActive, briefingIndex, briefingItems.length, briefingPaused]);

  useEffect(() => {
    if (!briefingActive) return;
    const item = briefingItems[briefingIndex];
    if (!item) return;
    setSelectedProjectId(item.id);
    setSelected({
      id: item.id,
      name: item.name,
      projectType: item.project_type,
      deliveryStage: item.statuses.delivery_stage ?? item.statuses.official_tracker_stage ?? null,
      geometry: item.geometry,
    });
    setDetailTab("overview");
    setSheetSnap("peek");
    window.history.replaceState({}, "", `/projects/${item.id}`);
  }, [briefingActive, briefingIndex, briefingItems]);

  function selectProject(project: MapProject, history: "push" | "replace" = "push") {
    if (briefingActive) setBriefingActive(false);
    setSelected(project);
    setSelectedProjectId(project.id);
    setDetail(null);
    setEvents([]);
    setContext(null);
    setDetailTab("overview");
    setSheetSnap("half");
    if (history === "push") window.history.pushState({}, "", `/projects/${project.id}`);
    else window.history.replaceState({}, "", `/projects/${project.id}`);
  }

  function selectProjectById(projectId: string) {
    if (briefingActive) setBriefingActive(false);
    setSelected(null);
    setSelectedProjectId(projectId);
    setDetail(null);
    setEvents([]);
    setContext(null);
    setDetailTab("overview");
    setSheetSnap("half");
    window.history.pushState({}, "", `/projects/${projectId}`);
    setView("map");
  }

  function clearSelection() {
    setSelected(null);
    setSelectedProjectId(null);
    setDetail(null);
    setEvents([]);
    setContext(null);
    setBriefingActive(false);
    window.history.replaceState({}, "", "/");
  }

  async function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = searchQuery.trim();
    if (query.length < 2) return;
    setSearchState("loading");
    try {
      const response = await fetch(`${API_BASE}/search/projects?${new URLSearchParams({ q: query, limit: "20" })}`);
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
    setView("map");
    setSearchOpen(false);
  }

  function changeWindow(next: TimeWindow) {
    setTimeWindow(next);
    setCoverage(null);
    setBriefingActive(false);
    clearSelection();
  }

  function changeProjectType(next: string | null) {
    setProjectType(next);
    setCoverage(null);
    setBriefingActive(false);
    clearSelection();
  }

  async function shareProject() {
    if (!selectedProjectId) return;
    const url = `${window.location.origin}/projects/${selectedProjectId}`;
    const title = detail?.name ?? selected?.name ?? "NS Trackstar project";
    if (navigator.share) {
      try {
        await navigator.share({ title, text: `Track this project on NS Trackstar: ${title}`, url });
        return;
      } catch {
        return;
      }
    }
    await navigator.clipboard.writeText(url);
    setShareState("copied");
    window.setTimeout(() => setShareState("idle"), 1600);
  }

  async function startBriefing() {
    setBriefingLoading(true);
    setSearchOpen(false);
    setView("map");
    try {
      let windowName: "today" | "week" = "today";
      let response = await fetch(`${API_BASE}/briefing?window=today&limit=8`);
      let items = response.ok ? (await response.json()) as BriefingItem[] : [];
      if (items.length < 2) {
        windowName = "week";
        response = await fetch(`${API_BASE}/briefing?window=week&limit=8`);
        if (!response.ok) throw new Error("Briefing unavailable");
        items = await response.json();
      }
      if (!items.length) throw new Error("No briefing items");
      setBriefingItems(items);
      setBriefingIndex(0);
      setBriefingWindow(windowName);
      setBriefingPaused(false);
      setBriefingActive(true);
      setTimeWindow(windowName === "today" ? "today" : "week");
    } finally {
      setBriefingLoading(false);
    }
  }

  function moveBriefing(delta: number) {
    setBriefingIndex((index) => Math.max(0, Math.min(briefingItems.length - 1, index + delta)));
  }

  function stopBriefing() {
    setBriefingActive(false);
    setBriefingPaused(false);
    setSheetSnap("half");
  }

  function onSheetPointerDown(event: ReactPointerEvent<HTMLButtonElement>) {
    dragStartY.current = event.clientY;
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function onSheetPointerMove(event: ReactPointerEvent<HTMLButtonElement>) {
    if (dragStartY.current === null) return;
    setSheetDrag(Math.max(-120, Math.min(180, event.clientY - dragStartY.current)));
  }

  function onSheetPointerUp(event: ReactPointerEvent<HTMLButtonElement>) {
    if (dragStartY.current === null) return;
    const delta = event.clientY - dragStartY.current;
    const current = SNAP_ORDER.indexOf(sheetSnap);
    if (delta < -55) setSheetSnap(SNAP_ORDER[Math.min(SNAP_ORDER.length - 1, current + 1)]);
    if (delta > 55) setSheetSnap(SNAP_ORDER[Math.max(0, current - 1)]);
    dragStartY.current = null;
    setSheetDrag(0);
  }

  const facts = useMemo(() => {
    const seen = new Set<string>();
    return (detail?.assertions ?? [])
      .filter((assertion) => !assertion.field.startsWith("status.") && assertion.field !== "description")
      .filter((assertion) => {
        if (seen.has(assertion.field)) return false;
        seen.add(assertion.field);
        return true;
      })
      .slice(0, 8);
  }, [detail]);
  const summary = context?.summary ?? detail?.assertions.find((assertion) => assertion.field === "description")?.value ?? null;
  const activeFilter = FILTERS.find((filter) => filter.value === timeWindow)?.label ?? "All";
  const currentBriefing = briefingItems[briefingIndex];
  const sheetStyle = { "--sheet-drag": `${sheetDrag}px` } as CSSProperties;

  return (
    <section className="trackstarApp" aria-label="NS Trackstar Napa and Solano intelligence map">
      <MapCanvas
        briefingActive={briefingActive}
        displayMode={mapDisplay}
        onCoverageChange={setCoverage}
        onSelectProject={(project) => selectProject(project)}
        projectType={projectType}
        resetNonce={resetNonce}
        selectedProject={selected}
        timeWindow={timeWindow}
      />
      <div className={selected ? "mapAtmosphere selected" : "mapAtmosphere"} />

      <header className="floatingHeader">
        <button className="brandLockup" onClick={() => { clearSelection(); setResetNonce((value) => value + 1); }} type="button">
          <span className="brandMark"><PulseIcon /></span>
          <span className="brandText"><strong>Trackstar</strong><small>Napa · Solano</small></span>
        </button>
        <a className="liveStatus" href="/admin/sources"><i /> Live intelligence</a>
      </header>

      {!briefingActive ? (
        <>
          <button className="heroSearch" onClick={() => setSearchOpen(true)} type="button">
            <SearchIcon /><span>Search projects, roads, permits, APNs…</span><kbd>⌘ K</kbd>
          </button>

          <nav className="timeRail" aria-label="Time filters">
            {FILTERS.map((filter) => (
              <button aria-pressed={filter.value === timeWindow} className={filter.value === timeWindow ? "timeChip active" : "timeChip"} key={filter.value} onClick={() => changeWindow(filter.value)} type="button">
                {filter.label}
              </button>
            ))}
            <button className="briefingChip" disabled={briefingLoading} onClick={() => void startBriefing()} type="button">
              <PlayIcon /> {briefingLoading ? "Loading…" : "Play briefing"}
            </button>
          </nav>

          <div className="categoryRail" aria-label="Project categories">
            <span className="categoryLead"><LayersIcon /></span>
            {CATEGORIES.map((category) => (
              <button aria-pressed={category.value === projectType} className={category.value === projectType ? "categoryChip active" : "categoryChip"} key={category.label} onClick={() => changeProjectType(category.value)} type="button">
                {category.label}
              </button>
            ))}
          </div>

          <div className="mapUtilityDock" role="group" aria-label="Map visualization">
            <button className={mapDisplay === "projects" ? "active" : ""} onClick={() => setMapDisplay("projects")} type="button">Map</button>
            <button className={mapDisplay === "density" ? "active" : ""} onClick={() => setMapDisplay("density")} type="button">Heat</button>
            <button className={mapDisplay === "perspective" ? "active" : ""} onClick={() => setMapDisplay("perspective")} type="button">Tilt</button>
            <button aria-label="Reset regional view" onClick={() => setResetNonce((value) => value + 1)} type="button">↗</button>
          </div>
        </>
      ) : null}

      <div className="modeDock" role="group" aria-label="Application view">
        <button className={view === "map" ? "active" : ""} onClick={() => setView("map")} type="button"><span>Map</span></button>
        <button className={view === "list" ? "active" : ""} onClick={() => { stopBriefing(); setView("list"); }} type="button"><span>List</span></button>
        <button className={view === "changes" ? "active" : ""} onClick={() => { stopBriefing(); setView("changes"); }} type="button"><span>Updates</span>{changes.length ? <b>{Math.min(changes.length, 99)}</b> : null}</button>
      </div>

      {briefingActive && currentBriefing ? (
        <section className="briefingHud" aria-live="polite">
          <div className="briefingProgress"><i style={{ width: `${((briefingIndex + 1) / briefingItems.length) * 100}%` }} /></div>
          <div className="briefingMeta"><span>{briefingWindow === "today" ? "TODAY" : "THIS WEEK"} · {briefingIndex + 1}/{briefingItems.length}</span><strong>{currentBriefing.event?.title ?? currentBriefing.name}</strong></div>
          <div className="briefingControls">
            <button disabled={briefingIndex === 0} onClick={() => moveBriefing(-1)} type="button">‹</button>
            <button aria-label={briefingPaused ? "Resume briefing" : "Pause briefing"} onClick={() => setBriefingPaused((value) => !value)} type="button">{briefingPaused ? <PlayIcon /> : <PauseIcon />}</button>
            <button disabled={briefingIndex === briefingItems.length - 1} onClick={() => moveBriefing(1)} type="button">›</button>
            <button className="briefingDone" onClick={stopBriefing} type="button">Done</button>
          </div>
        </section>
      ) : null}

      {view === "list" ? (
        <section className="browseSheet" aria-label="Project catalog">
          <div className="sheetHandle static" />
          <header className="browseHeader"><div><p className="cardMeta">{activeFilter.toUpperCase()} · {catalog.length.toLocaleString()} PROJECTS</p><h2>Project catalog</h2></div><button className="roundClose" aria-label="Return to map" onClick={() => setView("map")} type="button">×</button></header>
          {catalogState === "loading" ? <p className="emptyMessage">Loading the canonical project catalog…</p> : null}
          {catalogState === "error" ? <p className="errorMessage">The project catalog is temporarily unavailable.</p> : null}
          <ol className="browseList">
            {catalog.map((project) => (
              <li key={project.id}><button onClick={() => selectProjectById(project.id)} type="button"><span className="browseMeta"><time>{eventDate(project.last_activity_at)}</time><em className={project.has_geometry ? "mapped" : "pending"}>{project.has_geometry ? "Mapped" : "Location pending"}</em></span><strong>{project.name}</strong><span>{readableValue(project.project_type)}</span>{project.delivery_stage ? <small>{readableValue(project.delivery_stage)}</small> : null}</button></li>
            ))}
          </ol>
        </section>
      ) : null}

      {view === "changes" ? (
        <section className="browseSheet" aria-label="Recent project changes">
          <div className="sheetHandle static" />
          <header className="browseHeader"><div><p className="cardMeta">{activeFilter.toUpperCase()}</p><h2>What changed</h2></div><button className="roundClose" aria-label="Return to map" onClick={() => setView("map")} type="button">×</button></header>
          {changesState === "loading" ? <p className="emptyMessage">Loading source-backed updates…</p> : null}
          {changesState === "error" ? <p className="errorMessage">Updates are temporarily unavailable.</p> : null}
          {changesState === "done" && changes.length === 0 ? <p className="emptyMessage">No changes match these filters yet.</p> : null}
          <ol className="browseList">
            {changes.map((change) => (
              <li key={change.id}><button onClick={() => selectProjectById(change.project_id)} type="button"><span className="browseMeta"><time>{eventDate(change.occurred_at ?? change.observed_at)}</time><em>{readableValue(change.event_type)}</em></span><strong>{change.project_name}</strong><span>{change.title}</span>{change.summary ? <small>{change.summary}</small> : null}</button></li>
            ))}
          </ol>
        </section>
      ) : null}

      {searchOpen ? (
        <aside className="searchOverlay" aria-label="Project search">
          <div className="searchOverlayInner">
            <header className="searchOverlayHeader"><div><p className="cardMeta">SEARCH THE REGION</p><h2>Find anything changing</h2></div><button aria-label="Close search" className="roundClose" onClick={() => setSearchOpen(false)} type="button">×</button></header>
            <form className="spotlightSearch" onSubmit={submitSearch} role="search"><SearchIcon /><input autoFocus minLength={2} onChange={(event) => setSearchQuery(event.target.value)} placeholder="Project, business, address, permit, APN, road…" type="search" value={searchQuery} /><button disabled={searchQuery.trim().length < 2 || searchState === "loading"} type="submit">{searchState === "loading" ? "…" : "Go"}</button></form>
            <p className="searchHint">Live source-backed search across project names, aliases, addresses, APNs, permits and evidence.</p>
            <div className="searchResults" aria-live="polite">
              {searchState === "done" && searchResults.length === 0 ? <p className="emptyMessage">No source-backed projects matched that search.</p> : null}
              {searchState === "error" ? <p className="errorMessage">Search is temporarily unavailable.</p> : null}
              {searchResults.map((result) => {
                const stage = result.statuses.delivery_stage ?? result.statuses.official_tracker_stage;
                return <button className="searchResult" key={result.id} onClick={() => chooseSearchResult(result)} type="button"><span className="searchResultTopline"><strong>{result.name}</strong>{stage ? <em>{readableValue(stage)}</em> : null}</span>{result.summary ? <span>{result.summary}</span> : null}<small>{readableValue(result.matched_on)} · {result.geometry ? "mapped" : "location pending"}</small></button>;
              })}
            </div>
          </div>
        </aside>
      ) : null}

      {view === "map" && selected ? (
        <article className={`projectSheet snap-${sheetSnap} ${briefingActive ? "briefingProject" : ""}`} style={sheetStyle} aria-live="polite">
          <button className="sheetGrabber" aria-label="Drag project details" onPointerDown={onSheetPointerDown} onPointerMove={onSheetPointerMove} onPointerUp={onSheetPointerUp} type="button"><span /></button>
          <div className="projectSheetTopline"><p className="cardMeta">{readableValue(selected.projectType).toUpperCase()}</p><div className="sheetActions"><button className="iconButton" aria-label="Share project" onClick={() => void shareProject()} type="button"><ShareIcon /></button><button className="roundClose small" aria-label="Close project" onClick={clearSelection} type="button">×</button></div></div>
          <div className="projectTitleRow"><div><h2>{detail?.name ?? selected.name}</h2>{context?.aliases.length ? <p className="aliasLine">also known as {context.aliases.map((item) => item.alias).join(" · ")}</p> : null}</div>{selected.deliveryStage ? <span className="stagePill">{readableValue(selected.deliveryStage)}</span> : null}</div>
          <div className="trustRow"><span className={detail?.geometry ? "trustBadge mapped" : "trustBadge pending"}>{detail?.geometry ? "●" : "○"} {locationLabel(detail)}</span>{detail?.location?.confidence !== null && detail?.location?.confidence !== undefined ? <span>{Math.round(detail.location.confidence * 100)}% location confidence</span> : null}{shareState === "copied" ? <span className="copiedNotice">Link copied</span> : null}</div>

          <nav className="detailTabs" aria-label="Project detail sections">{(["overview", "activity", "evidence"] as DetailTab[]).map((tab) => <button className={detailTab === tab ? "active" : ""} key={tab} onClick={() => { setDetailTab(tab); if (sheetSnap === "peek") setSheetSnap("half"); }} type="button">{readableField(tab)}</button>)}</nav>

          <div className="projectSheetBody">
            {detailState === "loading" ? <p className="detailLoading">Loading official project intelligence…</p> : null}
            {detailState === "error" ? <p className="errorMessage">Project evidence could not be loaded.</p> : null}

            {detailTab === "overview" ? (
              <>
                {summary ? <p className="projectSummary">{readableValue(summary)}</p> : null}
                {!selected.geometry ? <p className="locationNotice">Trackstar knows this project exists, but no defensible map geometry is available yet. It stays in the catalog without a fake pin.</p> : null}
                {detail && Object.keys(detail.statuses).length ? <section className="statusSection"><h3>Status</h3><div className="statusGrid">{Object.entries(detail.statuses).map(([dimension, value]) => <div key={dimension}><span>{readableField(dimension)}</span><strong>{readableValue(value)}</strong></div>)}</div></section> : null}
                {facts.length ? <dl className="facts">{facts.map((assertion) => <div key={`${assertion.field}-${JSON.stringify(assertion.value)}`}><dt>{readableField(assertion.field)}</dt><dd>{readableValue(assertion.value)}</dd></div>)}</dl> : null}
                {context?.relationships.length ? <section className="relationshipSection"><div className="sectionHeading"><h3>Connected projects</h3><span>{context.relationships.length}</span></div><div className="relationshipList">{context.relationships.map((relationship) => <button key={`${relationship.direction}-${relationship.project_id}-${relationship.relationship_type}`} onClick={() => selectProjectById(relationship.project_id)} type="button"><span><small>{readableValue(relationship.relationship_type)}</small><strong>{relationship.project_name}</strong></span><em>{relationship.mapped ? "Mapped" : "Location pending"} →</em></button>)}</div></section> : null}
              </>
            ) : null}

            {detailTab === "activity" ? <section className="activitySection"><div className="sectionHeading"><h3>Project timeline</h3><span>{events.length}</span></div>{events.length ? <ol className="timeline expanded">{events.map((projectEvent) => <li key={projectEvent.id}><time dateTime={projectEvent.occurred_at ?? projectEvent.observed_at}>{eventDate(projectEvent.occurred_at ?? projectEvent.observed_at)}</time><div><strong>{projectEvent.title}</strong>{projectEvent.summary ? <p>{projectEvent.summary}</p> : null}</div></li>)}</ol> : <p className="emptyMessage">No dated project events have been published yet.</p>}</section> : null}

            {detailTab === "evidence" ? <section className="evidenceSection"><div className="sectionHeading"><h3>Official evidence</h3><span>{detail?.sources.length ?? 0}</span></div><div className="sourceCards">{detail?.sources.map((source) => <article key={`${source.source_key}-${source.relationship_type}-${source.url}`}><div><strong>{source.source_name}</strong><small>{readableValue(source.relationship_type)} · {Math.round(source.confidence * 100)}% link confidence</small></div>{source.url ? <a href={source.url} rel="noreferrer" target="_blank">Open source ↗</a> : null}</article>)}</div>{detail?.assertions.length ? <details className="assertionDrawer"><summary>All extracted facts <span>{detail.assertions.length}</span></summary><dl className="facts compact">{detail.assertions.map((assertion, index) => <div key={`${assertion.field}-${index}`}><dt>{readableField(assertion.field)}</dt><dd>{readableValue(assertion.value)}</dd></div>)}</dl></details> : null}</section> : null}
          </div>
        </article>
      ) : null}

      {view === "map" && !selected && !briefingActive ? (
        <>
          <details className="mapLegend"><summary>Legend</summary><div><span><i data-kind="development" />Development</span><span><i data-kind="environmental" />Environmental</span><span><i data-kind="transportation" />Transportation</span><span><i data-kind="public" />Public works</span><span><i data-kind="water" />Water</span></div></details>
          <div className="discoveryHint"><i /><span>{coverage ? <><strong>{coverage.visibleMapped.toLocaleString()} visible</strong> · {coverage.mappedMatching.toLocaleString()} mapped · {coverage.locationPending.toLocaleString()} location pending</> : <><strong>{activeFilter}</strong> · loading project coverage…</>}</span></div>
        </>
      ) : null}
    </section>
  );
}
