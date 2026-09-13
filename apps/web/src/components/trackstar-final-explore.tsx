"use client";

import type { ConsumerCategory, LifecycleFilter, MapProject, MapViewportState, TimeWindow } from "./map-final-model";
import { CATEGORIES, areaLabel, categoryLabel, lifecycleLabel } from "./trackstar-final-ui";
import { FilterIcon, LocationIcon } from "./trackstar-final-icons";
import styles from "./map-explorer-v2.module.css";
import extra from "./trackstar-final-extras.module.css";

type Props = {
  orientation: boolean;
  viewport: MapViewportState | null;
  category: ConsumerCategory;
  lifecycle: LifecycleFilter;
  timeWindow: TimeWindow;
  browseOpen: boolean;
  canBrief: boolean;
  onCollapse: () => void;
  onExpand: () => void;
  onCategory: (category: ConsumerCategory) => void;
  onLifecycleClear: () => void;
  onTimeClear: () => void;
  onBrowse: () => void;
  onFilters: () => void;
  onNearMe: () => void;
  onBrief: () => void;
};

export function ExploreUtilities({ onNearMe, onFilters, activeFilterCount }: { onNearMe: () => void; onFilters: () => void; activeFilterCount: number }) {
  return (
    <div className={styles.mapActions}>
      <button onClick={onNearMe} type="button"><LocationIcon /><span>Near me</span></button>
      <button className={activeFilterCount ? styles.activeAction : ""} onClick={onFilters} type="button">
        <FilterIcon /><span>Filters</span>{activeFilterCount ? <b>{activeFilterCount}</b> : null}
      </button>
    </div>
  );
}

export function ExplorePanel(props: Props) {
  if (props.browseOpen) return null;
  const label = areaLabel(props.viewport);
  const count = props.viewport?.projects.length ?? 0;

  if (props.orientation) {
    return (
      <section className={styles.orientationPanel} aria-label="Browse this area">
        <button className={styles.panelHandleButton} onClick={props.onCollapse} type="button" aria-label="Collapse browse panel"><span /></button>
        <div className={styles.areaHeading}>
          <div><p>EXPLORE</p><h2>{label}</h2><span>{props.viewport ? `${count.toLocaleString()} current mapped projects in view` : "Loading project coverage…"}</span></div>
          <button className={styles.collapseButton} onClick={props.onCollapse} type="button">Map ↓</button>
        </div>
        <div className={styles.categoryGrid}>
          {CATEGORIES.filter((item) => item.key !== "all").map((item) => (
            <button className={props.category === item.key ? styles.categorySelected : ""} key={item.key} onClick={() => props.onCategory(item.key)} type="button">
              <i>{item.icon}</i><span>{item.label}</span><small className={extra.categoryCount}>{props.viewport?.categoryCounts[item.key]?.toLocaleString() ?? "—"}</small>
            </button>
          ))}
        </div>
        <div className={styles.panelFooter}>
          <button onClick={props.onBrowse} type="button">Browse projects</button>
          <button onClick={props.onFilters} type="button"><FilterIcon /> More filters</button>
        </div>
      </section>
    );
  }

  return (
    <section className={styles.freeExploreBar} aria-label="Free Explore controls">
      <button className={styles.areaPill} onClick={props.onExpand} type="button">
        <span><strong>{label}</strong><small>{props.viewport ? `${count.toLocaleString()} showing` : "Loading"}</small></span><b>↑</b>
      </button>
      <div className={styles.pillScroller}>
        {CATEGORIES.map((item) => (
          <button className={props.category === item.key ? styles.pillSelected : ""} key={item.key} onClick={() => props.onCategory(item.key)} type="button">{item.label}</button>
        ))}
        <button onClick={props.onBrowse} type="button">Browse projects</button>
        {props.canBrief ? <button onClick={props.onBrief} type="button">▶ Brief</button> : null}
        <button className={styles.filterPill} onClick={props.onFilters} aria-label="Open filters" type="button"><FilterIcon /></button>
      </div>
      {(props.lifecycle !== "current" || props.timeWindow !== "all") ? (
        <div className={extra.activeChips} aria-label="Active filters">
          {props.lifecycle !== "current" ? <button onClick={props.onLifecycleClear} type="button">{lifecycleLabel(props.lifecycle)} ×</button> : null}
          {props.timeWindow !== "all" ? <button onClick={props.onTimeClear} type="button">{props.timeWindow === "today" ? "Changed today" : props.timeWindow === "week" ? "Changed recently" : "Coming up"} ×</button> : null}
        </div>
      ) : null}
    </section>
  );
}

export function BrowsePanel({ viewport, category, lifecycle, onClose, onSelect, onCategory, onClear }: {
  viewport: MapViewportState | null;
  category: ConsumerCategory;
  lifecycle: LifecycleFilter;
  onClose: () => void;
  onSelect: (project: MapProject) => void;
  onCategory: (category: ConsumerCategory) => void;
  onClear: () => void;
}) {
  const projects = [...(viewport?.projects ?? [])].sort((a, b) => a.consumerCategory.localeCompare(b.consumerCategory) || a.name.localeCompare(b.name));
  const tooBroad = category === "all" && lifecycle === "current" && projects.length > 150;
  return (
    <section className={styles.updatesPanel} aria-label="Browse projects">
      <div className={styles.updatesHeader}>
        <div><p>BROWSE PROJECTS</p><h2>{category === "all" ? areaLabel(viewport) : categoryLabel(category as Exclude<ConsumerCategory,"all">)}</h2><span>{projects.length.toLocaleString()} mapped projects in the current view{lifecycle !== "current" ? ` · ${lifecycleLabel(lifecycle)}` : ""}</span></div>
        <div className={styles.projectActions}><button aria-label="Close project list" onClick={onClose} type="button">×</button></div>
      </div>
      {tooBroad ? (
        <><p className={styles.stateMessage}>Choose a category or zoom in for a useful local list.</p><div className={styles.categoryGrid}>{CATEGORIES.filter((item) => item.key !== "all").map((item) => <button key={item.key} onClick={() => onCategory(item.key)} type="button"><i>{item.icon}</i><span>{item.label}</span></button>)}</div></>
      ) : (
        <ol className={styles.updateList}>{projects.map((project) => <li key={project.id}><button onClick={() => onSelect(project)} type="button"><small>{categoryLabel(project.consumerCategory)} · {lifecycleLabel(project.lifecycleStage)}</small><strong>{project.name}</strong><span>{project.locationUncertain ? "Approximate location" : "View project"}</span></button></li>)}</ol>
      )}
      {viewport && projects.length === 0 ? <div className={styles.emptyUpdates}><strong>No mapped projects match this view.</strong><span>Clear filters or zoom out.</span><button onClick={onClear} type="button">Clear filters</button></div> : null}
    </section>
  );
}
