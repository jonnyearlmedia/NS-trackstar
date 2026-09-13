"use client";

import type { ConsumerCategory, LifecycleFilter, MapProject, MapViewportState, TimeWindow } from "./map-final-model";
import { ACTIVITY_OPTIONS, CATEGORIES, LIFECYCLE_OPTIONS, categoryLabel, lifecycleLabel, type LocationState } from "./trackstar-final-ui";
import styles from "./map-explorer-v2.module.css";
import extra from "./trackstar-final-extras.module.css";

export function FilterSheet({ category, lifecycle, timeWindow, viewport, onCategory, onLifecycle, onTime, onClear, onDone, onClose }: {
  category: ConsumerCategory;
  lifecycle: LifecycleFilter;
  timeWindow: TimeWindow;
  viewport: MapViewportState | null;
  onCategory: (value: ConsumerCategory) => void;
  onLifecycle: (value: LifecycleFilter) => void;
  onTime: (value: TimeWindow) => void;
  onClear: () => void;
  onDone: () => void;
  onClose: () => void;
}) {
  return <aside className={styles.scrim} onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}>
    <section className={styles.modalSheet} aria-label="Filter Trackstar">
      <header><div><p>FILTER MAP</p><h2>Show me…</h2></div><button aria-label="Close filters" onClick={onClose} type="button">×</button></header>
      <section><h3>Category</h3><div className={styles.filterChoices}>{CATEGORIES.map((item) => <button className={category === item.key ? styles.filterChoiceSelected : ""} key={item.key} onClick={() => onCategory(item.key)} type="button"><span>{item.longLabel}</span><i>{category === item.key ? "✓" : ""}</i></button>)}</div></section>
      <section><h3>Stage</h3><div className={styles.filterChoices}>{LIFECYCLE_OPTIONS.map((item) => <button className={lifecycle === item.value ? styles.filterChoiceSelected : ""} key={item.value} onClick={() => onLifecycle(item.value)} type="button"><span>{item.label}{viewport && item.value !== "all" ? ` · ${viewport.lifecycleCounts[item.value] ?? 0}` : ""}</span><i>{lifecycle === item.value ? "✓" : ""}</i></button>)}</div></section>
      <section><h3>Activity</h3><div className={styles.filterChoices}>{ACTIVITY_OPTIONS.map((item) => <button className={timeWindow === item.value ? styles.filterChoiceSelected : ""} key={item.value} onClick={() => onTime(item.value)} type="button"><span>{item.label}</span><i>{timeWindow === item.value ? "✓" : ""}</i></button>)}</div></section>
      <footer><button onClick={onClear} type="button">Clear all</button><button className={styles.doneButton} onClick={onDone} type="button">Show map</button></footer>
    </section>
  </aside>;
}

export function NearMeSheet({ state, onClose, onRequest, onReturn }: { state: LocationState; onClose: () => void; onRequest: () => void; onReturn: () => void }) {
  const title = state === "outside" ? "You're outside Trackstar coverage" : state === "denied" ? "Location access is off" : state === "error" ? "Location isn't available" : "See projects around you?";
  const copy = state === "outside" ? "Trackstar currently covers Napa and Solano counties. You can still browse the coverage area or search for a place, road, address, or project." : state === "denied" ? "Your browser did not allow location access. Search and manual map browsing still work normally." : state === "error" ? "Trackstar couldn't get your location right now. Search and manual map browsing still work normally." : "Trackstar can use your location once to center the map on nearby projects. If you say no, search and map browsing still work normally.";
  return <aside className={styles.scrim} onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}><section className={`${styles.modalSheet} ${styles.locationSheet}`}><header><div><p>NEAR ME</p><h2>{title}</h2></div><button aria-label="Close" onClick={onClose} type="button">×</button></header><p>{copy}</p>{state === "outside" ? <button className={styles.locationConfirm} onClick={onReturn} type="button">View Napa + Solano</button> : state === "denied" || state === "error" ? <button className={styles.locationConfirm} onClick={onClose} type="button">Browse the map</button> : <button className={styles.locationConfirm} disabled={state === "checking"} onClick={onRequest} type="button">{state === "checking" ? "Getting location…" : "Use my location"}</button>}</section></aside>;
}

export function OverlapChooser({ projects, onClose, onSelect }: { projects: MapProject[]; onClose: () => void; onSelect: (project: MapProject) => void }) {
  return <aside className={styles.scrim} onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}><section className={styles.modalSheet}><header><div><p>MULTIPLE PROJECTS</p><h2>What's here?</h2></div><button aria-label="Close chooser" onClick={onClose} type="button">×</button></header><div className={extra.overlapList}>{projects.map((project) => <button key={project.id} onClick={() => onSelect(project)} type="button"><small>{categoryLabel(project.consumerCategory)} · {lifecycleLabel(project.lifecycleStage)}</small><strong>{project.name}</strong></button>)}</div></section></aside>;
}
