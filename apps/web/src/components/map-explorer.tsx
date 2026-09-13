"use client";

import type { Geometry } from "geojson";
import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, PointerEvent as ReactPointerEvent } from "react";

import {
  MapCanvas,
  type MapCoverage,
  type MapDisplayMode,
  type MapProject,
  type TimeWindow,
} from "@/components/map-canvas";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const SNAP_ORDER = ["peek", "half", "full"] as const;

type SheetSnap = (typeof SNAP_ORDER)[number];
type AppView = "explore" | "updates";
type HistoryMode = "recent" | "all";

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
  summary?: string | null;
  last_activity_at?: string | null;
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
  location_label?: string | null;
  lead_agency?: string | null;
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
  matches?: Array<{
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
  geometry: Geometry;
  statuses: Record<string, string>;
  summary: string | null;
  source_count: number;
  briefing_kind?: "change" | "current_context";
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

const CATEGORY_OPTIONS = [
  { label: "Everything", value: null, description: "Let Trackstar decide what is worth showing." },
  { label: "Construction & development", value: "municipal_development", description: "Buildings, neighborhoods and development sites." },
  { label: "Roads & transportation", value: "transportation_project", description: "Road work, corridors and transportation projects." },
  { label: "Public projects", value: "public_works", description: "City and county infrastructure projects." },
  { label: "Water", value: "water_infrastructure", description: "Water-system construction and upgrades." },
  { label: "Reviews & approvals", value: "environmental_review", description: "Projects moving through public review and approvals." },
] as const;

const TIME_OPTIONS: Array<{ label: string; value: TimeWindow; description: string }> = [
  { label: "Any time", value: "all", description: "Everything Trackstar knows about." },
  { label: "Changed today", value: "today", description: "Projects with new activity today." },
  { label: "Recently changed", value: "week", description: "Activity from the last seven days." },
  { label: "Coming up", value: "upcoming", description: "Published future hearings, milestones and events." },
];

const HUMAN_VALUES: Record<string, string> = {
  under_review_or_in_process: "Under review / in process",
  document_type_eir: "Environmental impact report on file",
  document_type_nod: "Decision notice filed",
  document_type_noe: "Exemption notice filed",
  document_type_mnd: "Mitigated negative declaration on file",
  document_type_nd: "Negative declaration on file",
  document_type_fon: "Environmental review document filed",
  trust_acquisition_approved: "Federal trust acquisition approved",
  restored_lands_exception_approved: "Federal gaming eligibility approved",
  restored_lands_exception_disapproved: "Federal gaming eligibility disapproved",
  temporarily_rescinded_for_reconsideration: "Federal gaming eligibility under reconsideration",
  in_progress: "In progress",
  complete: "Complete",
  completed: "Completed",
};

const STATUS_ORDER = [
  ["construction", "Construction"],
  ["operations", "Operations"],
  ["delivery_stage", "Current stage"],
  ["official_tracker_stage", "Current stage"],
  ["official_program_status", "Current status"],
  ["building_permit", "Building permit"],
  ["planning", "Planning"],
  ["entitlement", "Approval"],
  ["environmental", "Public review"],
  ["litigation", "Legal"],
  ["land_status", "Land status"],
  ["federal_authorization", "Federal authorization"],
  ["state_authorization", "State authorization"],
  ["gaming_eligibility", "Federal gaming eligibility"],
  ["gaming_ordinance", "Gaming ordinance"],
  ["compact", "Compact"],
  ["funding", "Funding"],
  ["procurement", "Procurement"],
] as const;

function readableField(field: string) {
  return field.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function readableValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return new Intl.NumberFormat("en-US").format(value);
  if (typeof value === "string") return HUMAN_VALUES[value.toLowerCase()] ?? value.replaceAll("_", " ");
  if (Array.isArray(value)) return value.map(readableValue).join(", ");
  return JSON.stringify(value);
}

function eventDate(value: string | null | undefined) {
  if (!value) return "date not published";
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(new Date(value));
}

function consumerType(projectType: string) {
  if (projectType === "municipal_development") return "Construction & development";
  if (projectType === "transportation_project") return "Roads & transportation";
  if (projectType === "public_works") return "Public project";
  if (projectType === "water_infrastructure") return "Water project";
  if (projectType === "environmental_review") return "Development & public review";
  return "Local project";
}

function humanEventHeadline(event: Pick<ProjectEvent, "event_type" | "title" | "summary">) {
  if (event.event_type === "ceqa_document_received") return "A new environmental review document was filed.";
  if (event.event_type?.endsWith("_changed")) return event.title.replaceAll("_", " ");
  if (event.summary && event.summary !== event.title) return event.summary;
  return event.title;
}

function statusList(statuses: Record<string, string>) {
  const used = new Set<string>();
  const result: Array<{ key: string; label: string; value: string }> = [];
  for (const [key, label] of STATUS_ORDER) {
    const value = statuses[key];
    if (!value || used.has(`${label}:${value}`)) continue;
    used.add(`${label}:${value}`);
    result.push({ key, label, value: readableValue(value) });
  }
  for (const [key, value] of Object.entries(statuses)) {
    if (STATUS_ORDER.some(([known]) => known === key)) continue;
    result.push({ key, label: readableField(key), value: readableValue(value) });
  }
  return result;
}

function humanStatus(statuses: Record<string, string>) {
  return statusList(statuses)[0] ?? null;
}

function firstAssertion(assertions: Assertion[], fields: string[]) {
  return assertions.find((item) => fields.includes(item.field));
}

function locationIsUncertain(location: ProjectDetail["location"]) {
  if (!location) return false;
  if (location.confidence !== null && location.confidence < 0.75) return true;
  return !["exact_source_geometry", "exact_parcel", "exact_address"].includes(location.accuracy);
}

function locationTruthCopy(location: ProjectDetail["location"]) {
  if (!location) return null;
  const labels: Record<string, string> = {
    exact_source_geometry: "Exact official project geometry",
    exact_parcel: "Exact parcel boundary",
    exact_address: "Exact address location",
    intersection: "Approximate intersection",
    street_segment: "Approximate road segment",
    approximate_area: "Approximate project area",
    city_only: "City-level location only",
  };
  const label = labels[location.accuracy] ?? "Approximate location";
  const distance = location.accuracy_meters ? ` · about ${Math.round(location.accuracy_meters).toLocaleString()} m accuracy` : "";
  return `${label}${distance}`;
}

function plainSummary(detail: ProjectDetail | null, context: ProjectContext | null) {
  const description = context?.summary ?? detail?.summary ?? detail?.assertions.find((item) => item.field === "description")?.value;
  if (typeof description === "string" && description.trim()) {
    const cleaned = description.replace(/\s+/g, " ").trim();
    return cleaned.length > 340 ? `${cleaned.slice(0, 337).trimEnd()}…` : cleaned;
  }
  if (!detail) return "Loading what this project is and what is happening here…";

  const kind = detail.project_type === "municipal_development"
    ? "a local construction or development project"
    : detail.project_type === "transportation_project"
      ? "a road or transportation project"
      : detail.project_type === "public_works"
        ? "a public infrastructure project"
        : detail.project_type === "water_infrastructure"
          ? "a water-system project"
          : detail.project_type === "environmental_review"
            ? "a development or infrastructure project moving through public review"
            : "a local project";
  const locationFact = context?.location_label ?? firstAssertion(detail.assertions, ["location_description", "address"])?.value;
  const status = humanStatus(detail.statuses);
  const relationship = context?.relationships[0];
  const parts = [`This is ${kind}${locationFact ? ` at ${readableValue(locationFact)}` : ""}.`];
  if (status) parts.push(`The latest official status Trackstar has is ${status.value}.`);
  if (relationship) parts.push(`It is connected to ${relationship.project_name}.`);
  return parts.join(" ");
}

function humanFacts(assertions: Assertion[]) {
  const priorities = [
    "location_description",
    "address",
    "residential_units",
    "units",
    "project_units",
    "planned_completion",
    "completion_date",
    "planned_construction_start",
    "construction_start",
    "location_acres",
    "site_acres",
    "building_area_sqft",
    "developer",
    "applicant",
  ];
  const byField = new Map<string, Assertion>();
  for (const assertion of assertions) if (!byField.has(assertion.field)) byField.set(assertion.field, assertion);
  return priorities.flatMap((field) => byField.has(field) ? [byField.get(field)!] : []).slice(0, 3);
}

function routeProjectId() {
  if (typeof window === "undefined") return null;
  return window.location.pathname.match(/^\/projects\/([^/]+)$/)?.[1] ?? null;
}

function SearchIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m21 21-4.35-4.35m2.35-5.65a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z" /></svg>;
}
function PulseIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M3 12h4l2.2-6 4.1 12 2.1-6H21" /></svg>;
}
function FilterIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 7h16M7 12h10M10 17h4" /></svg>;
}
function LocationIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 21s6-5.2 6-11a6 6 0 1 0-12 0c0 5.8 6 11 6 11Z" /><circle cx="12" cy="10" r="2" /></svg>;
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

export function MapExplorer({ initialProjectId }: { initialProjectId?: string }) {
  const [timeWindow, setTimeWindow] = useState<TimeWindow>("all");
  const [projectType, setProjectType] = useState<string | null>(null);
  const [displayMode, setDisplayMode] = useState<MapDisplayMode>("projects");
  const [view, setView] = useState<AppView>("explore");
  const [coverage, setCoverage] = useState<MapCoverage | null>(null);
  const [highlights, setHighlights] = useState<MapProject[]>([]);
  const [resetNonce, setResetNonce] = useState(0);
  const [locateNonce, setLocateNonce] = useState(0);

  const [selected, setSelected] = useState<MapProject | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [events, setEvents] = useState<ProjectEvent[]>([]);
  const [context, setContext] = useState<ProjectContext | null>(null);
  const [detailState, setDetailState] = useState<"idle" | "loading" | "error">("idle");
  const [technicalOpen, setTechnicalOpen] = useState(false);
  const [historyMode, setHistoryMode] = useState<HistoryMode>("recent");
  const [sheetSnap, setSheetSnap] = useState<SheetSnap>("half");
  const [sheetDrag, setSheetDrag] = useState(0);
  const dragStartY = useRef<number | null>(null);

  const [filterOpen, setFilterOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchState, setSearchState] = useState<"idle" | "loading" | "done" | "error">("idle");

  const [changes, setChanges] = useState<ChangeEvent[]>([]);
  const [changesState, setChangesState] = useState<"loading" | "done" | "error">("loading");

  const [briefingItems, setBriefingItems] = useState<BriefingItem[]>([]);
  const [briefingIndex, setBriefingIndex] = useState(0);
  const [briefingActive, setBriefingActive] = useState(false);
  const [briefingPaused, setBriefingPaused] = useState(false);
  const [briefingLoading, setBriefingLoading] = useState(false);
  const [briefingWindow, setBriefingWindow] = useState<"today" | "week" | "all">("today");
  const [briefingNotice, setBriefingNotice] = useState<string | null>(null);
  const [shareState, setShareState] = useState<"idle" | "copied">("idle");

  useEffect(() => {
    const id = initialProjectId ?? routeProjectId();
    if (id) setSelectedProjectId(id);
  }, [initialProjectId]);

  useEffect(() => {
    function syncRoute() {
      const id = routeProjectId();
      setSelectedProjectId(id);
      if (!id) {
        setSelected(null);
        setDetail(null);
        setEvents([]);
        setContext(null);
      }
    }
    window.addEventListener("popstate", syncRoute);
    return () => window.removeEventListener("popstate", syncRoute);
  }, []);

  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen(true);
      }
      if (event.key === "Escape") {
        if (searchOpen) setSearchOpen(false);
        else if (filterOpen) setFilterOpen(false);
        else if (briefingActive) setBriefingActive(false);
      }
    }
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, [briefingActive, filterOpen, searchOpen]);

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
        if (!detailResponse.ok || !eventsResponse.ok) throw new Error("Project could not be loaded");
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
          lastActivityAt: nextDetail.last_activity_at,
          locationAccuracy: nextDetail.location?.accuracy ?? null,
          locationConfidence: nextDetail.location?.confidence ?? null,
          locationUncertain: locationIsUncertain(nextDetail.location),
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
    const updateWindow = timeWindow === "all" ? "week" : timeWindow;
    const params = new URLSearchParams({ window: updateWindow, limit: "80" });
    if (projectType) params.set("project_type", projectType);
    setChangesState("loading");
    fetch(`${API_BASE}/changes?${params}`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Changes API returned ${response.status}`);
        return response.json() as Promise<ChangeEvent[]>;
      })
      .then((items) => { setChanges(items); setChangesState("done"); })
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setChangesState("error");
      });
    return () => controller.abort();
  }, [projectType, timeWindow]);

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
          if (!response.ok) throw new Error(`Search returned ${response.status}`);
          return response.json() as Promise<SearchResult[]>;
        })
        .then((results) => { setSearchResults(results); setSearchState("done"); })
        .catch((error) => {
          if (error instanceof DOMException && error.name === "AbortError") return;
          setSearchState("error");
        });
    }, 180);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [searchOpen, searchQuery]);

  useEffect(() => {
    if (!briefingActive || briefingPaused || briefingItems.length < 2 || briefingIndex >= briefingItems.length - 1) return;
    const timer = window.setTimeout(() => setBriefingIndex((index) => index + 1), 7000);
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
      lastActivityAt: item.last_activity_at,
    });
    setTechnicalOpen(false);
    setHistoryMode("recent");
    setSheetSnap("peek");
    window.history.replaceState({}, "", `/projects/${item.id}`);
  }, [briefingActive, briefingIndex, briefingItems]);

  function selectProject(project: MapProject) {
    setBriefingActive(false);
    setSelected(project);
    setSelectedProjectId(project.id);
    setDetail(null);
    setEvents([]);
    setContext(null);
    setTechnicalOpen(false);
    setHistoryMode("recent");
    setSheetSnap("half");
    window.history.pushState({}, "", `/projects/${project.id}`);
  }

  function clearSelection() {
    setSelected(null);
    setSelectedProjectId(null);
    setDetail(null);
    setEvents([]);
    setContext(null);
    setTechnicalOpen(false);
    setHistoryMode("recent");
    setBriefingActive(false);
    window.history.replaceState({}, "", "/");
  }

  function applyCategory(value: string | null) {
    setProjectType(value);
    setFilterOpen(false);
    clearSelection();
  }

  function applyTime(value: TimeWindow) {
    setTimeWindow(value);
    setFilterOpen(false);
    clearSelection();
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
    setView("explore");
  }

  async function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = searchQuery.trim();
    if (query.length < 2) return;
    setSearchState("loading");
    try {
      const response = await fetch(`${API_BASE}/search/projects?${new URLSearchParams({ q: query, limit: "20" })}`);
      if (!response.ok) throw new Error("Search failed");
      setSearchResults(await response.json());
      setSearchState("done");
    } catch {
      setSearchState("error");
    }
  }

  async function shareProject() {
    if (!selectedProjectId) return;
    const url = `${window.location.origin}/projects/${selectedProjectId}`;
    const title = detail?.name ?? selected?.name ?? "NS Trackstar project";
    if (navigator.share) {
      try { await navigator.share({ title, text: `${title} on NS Trackstar`, url }); return; } catch { return; }
    }
    await navigator.clipboard.writeText(url);
    setShareState("copied");
    window.setTimeout(() => setShareState("idle"), 1400);
  }

  async function startBriefing() {
    setBriefingLoading(true);
    setBriefingNotice(null);
    setView("explore");
    setSearchOpen(false);
    setFilterOpen(false);
    try {
      let windowName: "today" | "week" | "all" = "today";
      let response = await fetch(`${API_BASE}/briefing?window=today&limit=8`);
      let items = response.ok ? await response.json() as BriefingItem[] : [];
      if (items.length < 2) {
        windowName = "week";
        response = await fetch(`${API_BASE}/briefing?window=week&limit=8`);
        if (!response.ok) throw new Error("Briefing unavailable");
        items = await response.json();
      }
      if (items.length < 2) {
        windowName = "all";
        response = await fetch(`${API_BASE}/briefing?window=all&limit=8`);
        if (!response.ok) throw new Error("Briefing unavailable");
        items = await response.json();
      }
      if (!items.length) {
        setBriefingNotice("Nothing meaningful needs a briefing right now. The map still has the full project picture.");
        return;
      }
      setBriefingItems(items);
      setBriefingIndex(0);
      setBriefingWindow(windowName);
      setBriefingPaused(false);
      setBriefingActive(true);
    } catch {
      setBriefingNotice("The briefing is temporarily unavailable. You can still explore every project on the map.");
    } finally {
      setBriefingLoading(false);
    }
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
    setSheetDrag(Math.max(-110, Math.min(170, event.clientY - dragStartY.current)));
  }
  function onSheetPointerUp(event: ReactPointerEvent<HTMLButtonElement>) {
    if (dragStartY.current === null) return;
    const delta = event.clientY - dragStartY.current;
    const current = SNAP_ORDER.indexOf(sheetSnap);
    if (delta < -50) setSheetSnap(SNAP_ORDER[Math.min(SNAP_ORDER.length - 1, current + 1)]);
    if (delta > 50) setSheetSnap(SNAP_ORDER[Math.max(0, current - 1)]);
    dragStartY.current = null;
    setSheetDrag(0);
  }

  const currentCategory = CATEGORY_OPTIONS.find((option) => option.value === projectType)?.label ?? "Everything";
  const currentTime = TIME_OPTIONS.find((option) => option.value === timeWindow)?.label ?? "Any time";
  const activeFilters = Number(projectType !== null) + Number(timeWindow !== "all") + Number(displayMode !== "projects");
  const statuses = statusList(detail?.statuses ?? {});
  const status = statuses[0] ?? null;
  const summary = plainSummary(detail, context);
  const facts = useMemo(() => humanFacts(detail?.assertions ?? []), [detail]);
  const currentBriefing = briefingItems[briefingIndex];
  const latestMeaningfulEvent = events.find((item) => item.event_type !== "project_discovered");
  const timelineEvents = historyMode === "all" ? events : events.slice(0, 8);
  const briefingLabel = briefingWindow === "today" ? "TODAY" : briefingWindow === "week" ? "THIS WEEK" : "LOCAL BRIEFING";
  const uncertainLocation = locationIsUncertain(detail?.location ?? null);
  const locationCopy = locationTruthCopy(detail?.location ?? null);

  return (
    <section className="trackstarApp" aria-label="NS Trackstar local project map">
      <MapCanvas
        briefingActive={briefingActive}
        displayMode={displayMode}
        locateNonce={locateNonce}
        onCoverageChange={setCoverage}
        onHighlightsChange={setHighlights}
        onSelectProject={selectProject}
        projectType={projectType}
        resetNonce={resetNonce}
        selectedProject={selected}
        timeWindow={timeWindow}
      />
      <div className={selected ? "mapAtmosphere selected" : "mapAtmosphere"} />

      <header className="simpleHeader">
        <button className="brandLockup" onClick={() => { clearSelection(); setResetNonce((value) => value + 1); }} type="button">
          <span className="brandMark"><PulseIcon /></span>
          <span className="brandText"><strong>Trackstar</strong><small>Napa · Solano</small></span>
        </button>
        <button className="simpleSearch" onClick={() => setSearchOpen(true)} type="button"><SearchIcon /><span>What’s being built?</span></button>
      </header>

      {!briefingActive ? (
        <div className="simpleActions">
          <button onClick={() => setLocateNonce((value) => value + 1)} type="button"><LocationIcon /><span>Near me</span></button>
          <button className={activeFilters ? "hasFilters" : ""} onClick={() => setFilterOpen(true)} type="button"><FilterIcon /><span>Filter</span>{activeFilters ? <b>{activeFilters}</b> : null}</button>
        </div>
      ) : null}

      {view === "explore" && !selected && !briefingActive ? (
        <>
          <section className="aroundCard">
            <div className="aroundHeading">
              <div><p>AROUND HERE</p><h2>{coverage ? `${coverage.visibleMapped.toLocaleString()} projects showing` : "What’s changing nearby"}</h2></div>
              <button onClick={() => void startBriefing()} type="button"><PlayIcon />{briefingLoading ? "Loading" : "Play briefing"}</button>
            </div>
            {briefingNotice ? <p className="emptyMessage">{briefingNotice}</p> : null}
            <div className="aroundList">
              {highlights.length ? highlights.map((project, index) => (
                <button key={project.id} onClick={() => selectProject(project)} type="button">
                  <span className="aroundRank">{index + 1}</span>
                  <span className="aroundCopy"><small>{consumerType(project.projectType)}</small><strong>{project.name}</strong><em>{project.deliveryStage ? readableValue(project.deliveryStage) : project.locationUncertain ? "Approximate location · tap for details" : "Tap to see what’s happening"}</em></span>
                  <span className="aroundArrow">›</span>
                </button>
              )) : <p className="emptyMessage">Move the map or zoom in to see what matters in this area.</p>}
            </div>
            <button className="filterSummary" onClick={() => setFilterOpen(true)} type="button">Showing {currentCategory.toLowerCase()} · {currentTime.toLowerCase()}</button>
          </section>
          <div className="mapLegend" aria-label="Map legend">
            <span><i className="legendDot development" />Development</span>
            <span><i className="legendDot transport" />Roads</span>
            <span><i className="legendDot public" />Public</span>
            <span><i className="legendDash" />Approximate</span>
            <span><i className="legendGlow" />Changed recently</span>
          </div>
        </>
      ) : null}

      <nav className="consumerNav" aria-label="Trackstar sections">
        <button className={view === "explore" ? "active" : ""} onClick={() => setView("explore")} type="button">Explore</button>
        <button className={view === "updates" ? "active" : ""} onClick={() => { stopBriefing(); clearSelection(); setView("updates"); }} type="button">Updates{changes.length ? <b>{Math.min(changes.length, 99)}</b> : null}</button>
      </nav>

      {view === "updates" ? (
        <section className="updatesSheet">
          <div className="sheetHandle" />
          <header><div><p>WHAT CHANGED</p><h2>The stuff worth knowing</h2><span>Recent official activity, ranked so you don’t have to dig through government records.</span></div><button onClick={() => void startBriefing()} type="button"><PlayIcon />Play</button></header>
          {changesState === "loading" ? <p className="emptyMessage">Checking what changed…</p> : null}
          {changesState === "error" ? <p className="errorMessage">Updates are temporarily unavailable.</p> : null}
          {changesState === "done" && changes.length === 0 ? <p className="emptyMessage">Nothing new matches these filters right now.</p> : null}
          <ol className="updatesList">
            {changes.map((change) => (
              <li key={change.id}><button onClick={() => { setView("explore"); selectProject({ id: change.project_id, name: change.project_name, projectType: change.project_type, deliveryStage: null, geometry: null }); }} type="button"><span><small>{consumerType(change.project_type)} · {eventDate(change.occurred_at ?? change.observed_at)}</small><strong>{change.project_name}</strong><em>{humanEventHeadline(change)}</em></span><b>›</b></button></li>
            ))}
          </ol>
        </section>
      ) : null}

      {filterOpen ? (
        <aside className="modalScrim" onMouseDown={(event) => { if (event.target === event.currentTarget) setFilterOpen(false); }}>
          <section className="filterSheet" aria-label="Filter projects">
            <div className="sheetHandle" />
            <header><div><p>SHOW ME</p><h2>What do you care about?</h2></div><button className="roundClose" onClick={() => setFilterOpen(false)} type="button">×</button></header>
            <div className="filterSection"><h3>Type of project</h3><div className="choiceList">{CATEGORY_OPTIONS.map((option) => <button className={projectType === option.value ? "selected" : ""} key={option.label} onClick={() => applyCategory(option.value)} type="button"><span><strong>{option.label}</strong><small>{option.description}</small></span><i>{projectType === option.value ? "✓" : ""}</i></button>)}</div></div>
            <div className="filterSection"><h3>When</h3><div className="choiceList compact">{TIME_OPTIONS.map((option) => <button className={timeWindow === option.value ? "selected" : ""} key={option.value} onClick={() => applyTime(option.value)} type="button"><span><strong>{option.label}</strong><small>{option.description}</small></span><i>{timeWindow === option.value ? "✓" : ""}</i></button>)}</div></div>
            <details className="moreFilters"><summary>Map options</summary><div className="mapModeChoices"><button className={displayMode === "projects" ? "selected" : ""} onClick={() => setDisplayMode("projects")} type="button">Standard</button><button className={displayMode === "density" ? "selected" : ""} onClick={() => setDisplayMode("density")} type="button">Heat</button><button className={displayMode === "perspective" ? "selected" : ""} onClick={() => setDisplayMode("perspective")} type="button">Tilt</button></div></details>
            <button className="clearFilters" onClick={() => { setProjectType(null); setTimeWindow("all"); setDisplayMode("projects"); setFilterOpen(false); clearSelection(); }} type="button">Reset to the simple view</button>
          </section>
        </aside>
      ) : null}

      {searchOpen ? (
        <aside className="searchOverlay" aria-label="Search Trackstar">
          <div className="searchOverlayInner">
            <header className="searchOverlayHeader"><div><p className="cardMeta">FIND A PLACE OR PROJECT</p><h2>What are you curious about?</h2></div><button aria-label="Close search" className="roundClose" onClick={() => setSearchOpen(false)} type="button">×</button></header>
            <form className="spotlightSearch" onSubmit={submitSearch}><SearchIcon /><input autoFocus minLength={2} onChange={(event) => setSearchQuery(event.target.value)} placeholder="Try a road, business, project or address" type="search" value={searchQuery} /><button disabled={searchQuery.trim().length < 2 || searchState === "loading"} type="submit">Go</button></form>
            <div className="searchResults">
              {searchState === "done" && searchResults.length === 0 ? <p className="emptyMessage">Nothing matched that yet.</p> : null}
              {searchState === "error" ? <p className="errorMessage">Search is temporarily unavailable.</p> : null}
              {searchResults.map((result) => {
                const statusResult = humanStatus(result.statuses);
                return <button className="searchResult" key={result.id} onClick={() => chooseSearchResult(result)} type="button"><span className="searchResultTopline"><strong>{result.name}</strong><em>{consumerType(result.project_type)}</em></span>{result.summary ? <span>{result.summary}</span> : null}<small>{statusResult ? `${statusResult.label}: ${statusResult.value}` : result.geometry ? "Mapped project" : "Location still being verified"}</small></button>;
              })}
            </div>
          </div>
        </aside>
      ) : null}

      {briefingActive && currentBriefing ? (
        <section className="briefingHud">
          <div className="briefingProgress"><i style={{ width: `${((briefingIndex + 1) / briefingItems.length) * 100}%` }} /></div>
          <p>{briefingLabel} · {briefingIndex + 1}/{briefingItems.length}</p>
          <small>{currentBriefing.name}</small>
          <strong>{currentBriefing.event ? humanEventHeadline(currentBriefing.event) : currentBriefing.summary ?? "A project worth knowing about right now."}</strong>
          <div className="briefingControls"><button aria-label="Previous project" disabled={briefingIndex === 0} onClick={() => setBriefingIndex((index) => Math.max(0, index - 1))} type="button">‹</button><button aria-label={briefingPaused ? "Resume briefing" : "Pause briefing"} onClick={() => setBriefingPaused((value) => !value)} type="button">{briefingPaused ? <PlayIcon /> : <PauseIcon />}</button><button aria-label="Next project" disabled={briefingIndex === briefingItems.length - 1} onClick={() => setBriefingIndex((index) => Math.min(briefingItems.length - 1, index + 1))} type="button">›</button><button className="briefingDone" onClick={stopBriefing} type="button">Done</button></div>
        </section>
      ) : null}

      {view === "explore" && selected ? (
        <article className={`humanProjectCard snap-${sheetSnap}`} style={{ transform: `translateY(${sheetDrag}px)` }}>
          <button aria-label="Drag project details" className="sheetGrabber" onPointerDown={onSheetPointerDown} onPointerMove={onSheetPointerMove} onPointerUp={onSheetPointerUp} type="button"><span /></button>
          <div className="humanCardTop"><div><p>{consumerType(selected.projectType).toUpperCase()}</p><h2>{detail?.name ?? selected.name}</h2>{context?.aliases.length ? <small>also known as {context.aliases.map((item) => item.alias).join(" · ")}</small> : context?.location_label ? <small>{context.location_label}</small> : null}</div><div className="sheetActions"><button aria-label="Share project" className="iconButton" onClick={() => void shareProject()} type="button"><ShareIcon /></button><button aria-label="Close project" className="roundClose small" onClick={clearSelection} type="button">×</button></div></div>
          <div className="humanCardBody">
            {detailState === "loading" ? <p className="projectLead">Figuring out what this is and what’s happening…</p> : detailState === "error" ? <p className="errorMessage">This project’s details could not load right now.</p> : <p className="projectLead">{summary}</p>}
            {latestMeaningfulEvent ? <section className="whatsHappening"><small>LATEST UPDATE</small><strong>{humanEventHeadline(latestMeaningfulEvent)}</strong><span>{eventDate(latestMeaningfulEvent.occurred_at ?? latestMeaningfulEvent.observed_at)}</span></section> : status ? <section className="whatsHappening"><small>CURRENT STATUS</small><strong>{status.value}</strong><span>{status.label}</span></section> : null}
            {statuses.length > 1 ? <div className="statusStrip" aria-label="Project status"><span className="statusStripLabel">Where it stands</span>{statuses.slice(0, 4).map((item) => <div key={item.key}><small>{item.label}</small><strong>{item.value}</strong></div>)}</div> : null}
            {facts.length ? <div className="humanFacts">{facts.map((fact) => <div key={fact.field}><small>{readableField(fact.field)}</small><strong>{readableValue(fact.value)}</strong></div>)}</div> : null}
            <div className="humanTrust"><span>{detail?.sources.length ? `Verified from ${detail.sources.length} official source${detail.sources.length === 1 ? "" : "s"}` : "Official-source details loading"}</span><span>{latestMeaningfulEvent ? `Updated ${eventDate(latestMeaningfulEvent.occurred_at ?? latestMeaningfulEvent.observed_at)}` : detail?.last_activity_at ? `Updated ${eventDate(detail.last_activity_at)}` : ""}</span>{shareState === "copied" ? <b>Link copied</b> : null}</div>
            {!detail?.geometry && detailState === "idle" ? <p className="locationNotice">Trackstar knows this project exists, but the exact map location is still being verified. No fake pin.</p> : uncertainLocation && locationCopy ? <p className="locationNotice"><strong>{locationCopy}.</strong> The dashed outline or soft halo is intentional — don’t read this as an exact footprint.</p> : detail?.location && locationCopy ? <p className="locationConfidence">{locationCopy}</p> : null}
            <button className="technicalToggle" onClick={() => { setTechnicalOpen((value) => !value); setSheetSnap("full"); }} type="button">{technicalOpen ? "Hide details" : "Details & sources"}<span>{technicalOpen ? "−" : "+"}</span></button>

            {technicalOpen ? (
              <div className="technicalLayer">
                {statuses.length ? <section><h3>Project status</h3><div className="statusGrid">{statuses.map((item) => <div key={item.key}><small>{item.label}</small><strong>{item.value}</strong></div>)}</div></section> : null}
                {context?.relationships.length ? <section><h3>Connected projects</h3><div className="relationshipList">{context.relationships.map((relationship) => <button key={`${relationship.direction}-${relationship.project_id}`} onClick={() => { setSelectedProjectId(relationship.project_id); setTechnicalOpen(false); setHistoryMode("recent"); window.history.pushState({}, "", `/projects/${relationship.project_id}`); }} type="button"><span><small>{readableValue(relationship.relationship_type)}</small><strong>{relationship.project_name}</strong></span><em>›</em></button>)}</div></section> : null}
                {context?.matches?.length ? <section><h3>Entity links</h3><div className="matchNotes">{context.matches.slice(0, 4).map((match) => <div key={match.project_id}><small>{readableValue(match.proposed_relationship)} · {Math.round(match.score * 100)}% match</small><strong>{match.project_name}</strong></div>)}</div></section> : null}
                {events.length ? <section><div className="timelineHeader"><h3>Timeline</h3><div><button className={historyMode === "recent" ? "active" : ""} onClick={() => setHistoryMode("recent")} type="button">Recent</button><button className={historyMode === "all" ? "active" : ""} onClick={() => setHistoryMode("all")} type="button">Full history</button></div></div><ol className="timeline expanded">{timelineEvents.map((item) => <li key={item.id}><time>{eventDate(item.occurred_at ?? item.observed_at)}</time><div><strong>{humanEventHeadline(item)}</strong>{item.summary && item.summary !== humanEventHeadline(item) ? <p>{item.summary}</p> : null}</div></li>)}</ol>{historyMode === "recent" && events.length > timelineEvents.length ? <button className="showHistory" onClick={() => setHistoryMode("all")} type="button">Show {events.length - timelineEvents.length} older updates</button> : null}</section> : null}
                {detail?.assertions.length ? <section><h3>Technical facts</h3><dl className="facts compact">{detail.assertions.slice(0, 18).map((item, index) => <div key={`${item.field}-${index}`}><dt>{readableField(item.field)}</dt><dd>{readableValue(item.value)}</dd></div>)}</dl></section> : null}
                {detail?.sources.length ? <section><h3>Official sources</h3><div className="sourceCards">{detail.sources.map((source, index) => <article key={`${source.source_key}-${index}`}><div><strong>{source.source_name}</strong><small>{readableValue(source.relationship_type)}</small></div>{source.url ? <a href={source.url} rel="noreferrer" target="_blank">Open ↗</a> : null}</article>)}</div></section> : null}
              </div>
            ) : null}
          </div>
        </article>
      ) : null}
    </section>
  );
}
