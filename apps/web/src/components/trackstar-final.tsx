"use client";

import { useEffect, useState } from "react";

import { MapCanvasFinal } from "./map-canvas-final";
import type { ConsumerCategory, LifecycleFilter, MapProject, MapViewportState, TimeWindow, UserLocation, ViewportBounds } from "./map-final-model";
import { isInsideServiceArea } from "./service-area";
import { BriefingCard } from "./trackstar-final-briefing";
import { BottomNav, CoverageNotice, TopChrome } from "./trackstar-final-chrome";
import { BrowsePanel, ExplorePanel, ExploreUtilities } from "./trackstar-final-explore";
import { loadAreaChanges, loadProjectBundle, searchProjects } from "./trackstar-final-loaders";
import { FilterSheet, NearMeSheet, OverlapChooser } from "./trackstar-final-modals";
import { ProjectSheet } from "./trackstar-final-project";
import { SearchOverlay } from "./trackstar-final-search";
import { UpdatesPanel } from "./trackstar-final-updates";
import {
  isViewportOutside,
  projectFromSearch,
  routeProjectId,
  type AppView,
  type ChangeEvent,
  type ExploreMode,
  type LocationState,
  type ProjectDetail,
  type ProjectEvent,
  type SearchResult,
  type SelectionOrigin,
} from "./trackstar-final-ui";

const ORIENTATION_KEY = "trackstar:orientation-seen:v3";

function curateBriefing(projects: MapProject[], changes: ChangeEvent[]) {
  const changed = new Set(changes.map((change) => change.project_id));
  return [...projects]
    .sort((a, b) => Number(changed.has(b.id)) - Number(changed.has(a.id)) || String(b.lastActivityAt ?? "").localeCompare(String(a.lastActivityAt ?? "")) || (b.priority ?? 0) - (a.priority ?? 0))
    .slice(0, 5);
}

export function TrackstarFinal({ initialProjectId }: { initialProjectId?: string }) {
  const [view, setView] = useState<AppView>("explore");
  const [exploreMode, setExploreMode] = useState<ExploreMode>("orientation");
  const [viewport, setViewport] = useState<MapViewportState | null>(null);
  const [category, setCategory] = useState<ConsumerCategory>("all");
  const [lifecycle, setLifecycle] = useState<LifecycleFilter>("current");
  const [timeWindow, setTimeWindow] = useState<TimeWindow>("all");
  const [resetNonce, setResetNonce] = useState(0);
  const [restoreBounds, setRestoreBounds] = useState<ViewportBounds | null>(null);
  const [restoreNonce, setRestoreNonce] = useState(0);
  const [userLocation, setUserLocation] = useState<UserLocation | null>(null);
  const [browseOpen, setBrowseOpen] = useState(false);
  const [filterOpen, setFilterOpen] = useState(false);
  const [locationOpen, setLocationOpen] = useState(false);
  const [locationState, setLocationState] = useState<LocationState>("idle");
  const [overlap, setOverlap] = useState<MapProject[]>([]);

  const [selected, setSelected] = useState<MapProject | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectionOrigin, setSelectionOrigin] = useState<SelectionOrigin | null>(null);
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [events, setEvents] = useState<ProjectEvent[]>([]);
  const [detailState, setDetailState] = useState<"idle" | "loading" | "error">("idle");
  const [detailExpanded, setDetailExpanded] = useState(false);
  const [shareCopied, setShareCopied] = useState(false);

  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchState, setSearchState] = useState<"idle" | "loading" | "done" | "error">("idle");

  const [changes, setChanges] = useState<ChangeEvent[]>([]);
  const [changesState, setChangesState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [changesTruncated, setChangesTruncated] = useState(false);

  const [briefingActive, setBriefingActive] = useState(false);
  const [briefingPaused, setBriefingPaused] = useState(false);
  const [briefingItems, setBriefingItems] = useState<MapProject[]>([]);
  const [briefingIndex, setBriefingIndex] = useState(0);
  const [briefingOrigin, setBriefingOrigin] = useState<ViewportBounds | null>(null);

  const activeFilterCount = Number(category !== "all") + Number(lifecycle !== "current") + Number(timeWindow !== "all");
  const outsideCoverage = isViewportOutside(viewport);
  const canBrief = Boolean(view === "explore" && exploreMode === "free" && !selected && !browseOpen && viewport && viewport.zoom >= 10 && viewport.projects.length >= 2 && viewport.projects.length <= 120);
  const currentBriefing = briefingItems[briefingIndex] ?? null;
  const currentBriefingChange = currentBriefing ? changes.find((change) => change.project_id === currentBriefing.id) ?? null : null;

  function rememberFreeExplore() {
    setExploreMode("free");
    try { window.localStorage.setItem(ORIENTATION_KEY, "1"); } catch { /* optional */ }
  }

  useEffect(() => {
    try { if (window.localStorage.getItem(ORIENTATION_KEY) === "1") setExploreMode("free"); } catch { /* optional */ }
    const id = initialProjectId ?? routeProjectId();
    if (id) setSelectedId(id);
  }, [initialProjectId]);

  useEffect(() => {
    const onPop = () => {
      const id = routeProjectId();
      if (id) setSelectedId(id);
      else closeProject(false);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  });

  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController();
    setDetailState("loading");
    loadProjectBundle(selectedId, controller.signal).then(({ detail: nextDetail, events: nextEvents, classification }) => {
      setDetail(nextDetail);
      setEvents(nextEvents);
      setSelected({
        id: nextDetail.id,
        name: nextDetail.name,
        projectType: nextDetail.project_type,
        consumerCategory: classification.consumer_category,
        deliveryStage: nextDetail.statuses.delivery_stage ?? nextDetail.statuses.official_tracker_stage ?? null,
        lifecycleStage: classification.lifecycle_stage,
        lifecycleEvidence: classification.lifecycle_evidence,
        geometry: nextDetail.geometry,
        lastActivityAt: nextDetail.last_activity_at,
        locationAccuracy: nextDetail.location?.accuracy ?? null,
        locationConfidence: nextDetail.location?.confidence ?? null,
      });
      setDetailState("idle");
    }).catch((error) => {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setDetailState("error");
    });
    return () => controller.abort();
  }, [selectedId]);

  useEffect(() => {
    if (!searchOpen || searchQuery.trim().length < 2) {
      setSearchResults([]);
      setSearchState("idle");
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setSearchState("loading");
      searchProjects(searchQuery.trim(), controller.signal).then((results) => {
        setSearchResults(results);
        setSearchState("done");
      }).catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setSearchState("error");
      });
    }, 180);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [searchOpen, searchQuery]);

  useEffect(() => {
    if (!viewport) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setChangesState("loading");
      loadAreaChanges(viewport, timeWindow, controller.signal).then((payload) => {
        setChanges(payload.items);
        setChangesTruncated(payload.metadata.truncated);
        setChangesState("done");
      }).catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setChangesState("error");
      });
    }, 160);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [timeWindow, viewport?.bounds.east, viewport?.bounds.north, viewport?.bounds.south, viewport?.bounds.west]);

  useEffect(() => {
    if (!briefingActive || briefingPaused || briefingIndex >= briefingItems.length - 1) return;
    const timer = window.setTimeout(() => setBriefingIndex((index) => index + 1), 6500);
    return () => window.clearTimeout(timer);
  }, [briefingActive, briefingPaused, briefingIndex, briefingItems.length]);
  useEffect(() => {
    if (briefingActive && briefingItems[briefingIndex]) setSelected(briefingItems[briefingIndex]);
  }, [briefingActive, briefingIndex, briefingItems]);

  function selectProject(project: MapProject) {
    setSelectionOrigin({ view, browseOpen, exploreMode, bounds: viewport?.bounds ?? null });
    setOverlap([]);
    setBrowseOpen(false);
    setView("explore");
    setSelected(project);
    setSelectedId(project.id);
    setDetail(null);
    setEvents([]);
    setDetailExpanded(false);
    window.history.pushState({}, "", `/projects/${project.id}`);
  }

  function closeProject(updateUrl = true) {
    setSelected(null);
    setSelectedId(null);
    setDetail(null);
    setEvents([]);
    setDetailExpanded(false);
    if (updateUrl) window.history.replaceState({}, "", "/");
    if (selectionOrigin) {
      setView(selectionOrigin.view);
      setBrowseOpen(selectionOrigin.browseOpen);
      setExploreMode(selectionOrigin.exploreMode);
      if (selectionOrigin.bounds) {
        setRestoreBounds(selectionOrigin.bounds);
        setRestoreNonce((value) => value + 1);
      }
    } else {
      setView("explore");
      setExploreMode("free");
    }
    setSelectionOrigin(null);
  }

  async function shareProject() {
    if (!selectedId) return;
    const url = `${window.location.origin}/projects/${selectedId}`;
    const title = detail?.name ?? selected?.name ?? "Trackstar project";
    if (navigator.share) {
      try { await navigator.share({ title, text: `${title} on Trackstar`, url }); return; } catch { return; }
    }
    await navigator.clipboard.writeText(url);
    setShareCopied(true);
    window.setTimeout(() => setShareCopied(false), 1400);
  }

  function requestLocation() {
    if (!navigator.geolocation) { setLocationState("error"); return; }
    setLocationState("checking");
    navigator.geolocation.getCurrentPosition((position) => {
      const { latitude, longitude, accuracy } = position.coords;
      if (!isInsideServiceArea({ lng: longitude, lat: latitude })) {
        setLocationState("outside");
        setUserLocation(null);
        return;
      }
      setUserLocation({ latitude, longitude, accuracy });
      setLocationState("idle");
      setLocationOpen(false);
      rememberFreeExplore();
    }, (error) => setLocationState(error.code === error.PERMISSION_DENIED ? "denied" : "error"), { enableHighAccuracy: true, timeout: 10_000, maximumAge: 60_000 });
  }

  function returnToCoverage() {
    setLocationOpen(false);
    setResetNonce((value) => value + 1);
    setExploreMode("orientation");
  }

  function clearFilters() {
    setCategory("all");
    setLifecycle("current");
    setTimeWindow("all");
  }

  function startBriefing() {
    if (!viewport) return;
    const items = curateBriefing(viewport.projects, changes);
    if (items.length < 2) return;
    setBriefingOrigin(viewport.bounds);
    setBriefingItems(items);
    setBriefingIndex(0);
    setBriefingPaused(false);
    setBriefingActive(true);
    setSelected(items[0]);
    rememberFreeExplore();
  }
  function stopBriefing(restore = true) {
    setBriefingActive(false);
    setBriefingPaused(false);
    setBriefingItems([]);
    setBriefingIndex(0);
    setSelected(null);
    if (restore && briefingOrigin) {
      setRestoreBounds(briefingOrigin);
      setRestoreNonce((value) => value + 1);
    }
  }
  function openBriefingProject() {
    if (!currentBriefing) return;
    const project = currentBriefing;
    stopBriefing(false);
    selectProject(project);
  }

  function resetApp() {
    stopBriefing(false);
    closeProject(false);
    clearFilters();
    setBrowseOpen(false);
    setResetNonce((value) => value + 1);
    setExploreMode("orientation");
  }

  return <section className="trackstarApp" aria-label="Trackstar Napa Solano project map">
    <MapCanvasFinal
      briefingActive={briefingActive}
      category={category}
      lifecycle={lifecycle}
      onCoverageChange={() => {}}
      onSelectProject={selectProject}
      onSelectProjects={setOverlap}
      onUserInteraction={() => {
        if (briefingActive) { stopBriefing(false); return; }
        if (browseOpen) setBrowseOpen(false);
        if (exploreMode === "orientation") rememberFreeExplore();
      }}
      onViewportChange={setViewport}
      resetNonce={resetNonce}
      restoreBounds={restoreBounds}
      restoreNonce={restoreNonce}
      selectedProject={selected}
      timeWindow={timeWindow}
      userLocation={userLocation}
    />
    <div className={`mapAtmosphere ${selected ? "selected" : ""}`} />
    <TopChrome onReset={resetApp} onSearch={() => setSearchOpen(true)} />
    <CoverageNotice outside={outsideCoverage} onReturn={returnToCoverage} />

    {view === "explore" && !selected && !browseOpen && !briefingActive ? <ExploreUtilities activeFilterCount={activeFilterCount} onFilters={() => setFilterOpen(true)} onNearMe={() => { setLocationState("idle"); setLocationOpen(true); }} /> : null}
    {view === "explore" && !selected && !briefingActive ? <ExplorePanel orientation={exploreMode === "orientation"} viewport={viewport} category={category} lifecycle={lifecycle} timeWindow={timeWindow} browseOpen={browseOpen} canBrief={canBrief} onCollapse={rememberFreeExplore} onExpand={() => setExploreMode("orientation")} onCategory={(value) => { setCategory(value); rememberFreeExplore(); }} onLifecycleClear={() => setLifecycle("current")} onTimeClear={() => setTimeWindow("all")} onBrowse={() => { rememberFreeExplore(); setBrowseOpen(true); }} onFilters={() => setFilterOpen(true)} onNearMe={() => setLocationOpen(true)} onBrief={startBriefing} /> : null}
    {view === "explore" && !selected && browseOpen && !briefingActive ? <BrowsePanel viewport={viewport} category={category} lifecycle={lifecycle} onClose={() => setBrowseOpen(false)} onSelect={selectProject} onCategory={(value) => { setCategory(value); setBrowseOpen(false); }} onClear={clearFilters} /> : null}
    {view === "updates" && !selected && !briefingActive ? <UpdatesPanel viewport={viewport} changes={changes} loading={changesState === "loading"} error={changesState === "error"} truncated={changesTruncated} onSelect={selectProject} onExplore={() => setView("explore")} /> : null}
    {!selected && !briefingActive ? <BottomNav view={view} onView={(next) => { setBrowseOpen(false); setView(next); }} /> : null}

    {selected && !briefingActive ? <ProjectSheet selected={selected} detail={detail} events={events} state={detailState} expanded={detailExpanded} onExpanded={setDetailExpanded} onClose={() => closeProject()} onShare={() => void shareProject()} shareCopied={shareCopied} /> : null}
    {briefingActive && currentBriefing ? <BriefingCard project={currentBriefing} index={briefingIndex} total={briefingItems.length} change={currentBriefingChange} paused={briefingPaused} onPause={() => setBriefingPaused((value) => !value)} onNext={() => setBriefingIndex((index) => Math.min(briefingItems.length - 1, index + 1))} onOpen={openBriefingProject} onExit={() => stopBriefing(true)} /> : null}

    {filterOpen ? <FilterSheet category={category} lifecycle={lifecycle} timeWindow={timeWindow} viewport={viewport} onCategory={setCategory} onLifecycle={setLifecycle} onTime={setTimeWindow} onClear={clearFilters} onDone={() => { setFilterOpen(false); rememberFreeExplore(); }} onClose={() => setFilterOpen(false)} /> : null}
    {locationOpen ? <NearMeSheet state={locationState} onClose={() => setLocationOpen(false)} onRequest={requestLocation} onReturn={returnToCoverage} /> : null}
    {overlap.length > 1 ? <OverlapChooser projects={overlap} onClose={() => setOverlap([])} onSelect={selectProject} /> : null}
    {searchOpen ? <SearchOverlay query={searchQuery} results={searchResults} state={searchState} onQuery={setSearchQuery} onClose={() => setSearchOpen(false)} onSelect={(result) => { setSearchOpen(false); rememberFreeExplore(); selectProject(projectFromSearch(result)); }} /> : null}
  </section>;
}
