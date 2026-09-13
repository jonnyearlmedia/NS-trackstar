"use client";

import { useMemo } from "react";
import type { MapProject, MapViewportState } from "./map-final-model";
import { areaLabel, categoryLabel, eventDate, eventHeadline, type ChangeEvent } from "./trackstar-final-ui";
import styles from "./map-explorer-v2.module.css";

export function UpdatesPanel({ viewport, changes, loading, error, truncated, onSelect, onExplore }: {
  viewport: MapViewportState | null;
  changes: ChangeEvent[];
  loading: boolean;
  error: boolean;
  truncated: boolean;
  onSelect: (project: MapProject) => void;
  onExplore: () => void;
}) {
  const projectById = useMemo(() => new Map((viewport?.projects ?? []).map((project) => [project.id, project])), [viewport]);
  const grouped = useMemo(() => {
    const groups = new Map<string, { project: MapProject; events: ChangeEvent[] }>();
    for (const change of changes) {
      const project = projectById.get(change.project_id);
      if (!project) continue;
      const existing = groups.get(project.id);
      if (existing) existing.events.push(change);
      else groups.set(project.id, { project, events: [change] });
    }
    return [...groups.values()].sort((a, b) => {
      const aDate = a.events[0]?.occurred_at ?? a.events[0]?.observed_at ?? "";
      const bDate = b.events[0]?.occurred_at ?? b.events[0]?.observed_at ?? "";
      return bDate.localeCompare(aDate);
    });
  }, [changes, projectById]);

  return <section className={styles.updatesPanel} aria-label="Updates in current map area">
    <div className={styles.updatesHeader}><div><p>UPDATES · CURRENT MAP AREA</p><h2>What changed</h2><span>{areaLabel(viewport)} · recent official activity</span></div></div>
    {loading || !viewport ? <p className={styles.stateMessage}>Checking recent changes in this map area…</p> : null}
    {error ? <p className={styles.stateMessage}>Updates are temporarily unavailable.</p> : null}
    {truncated ? <p className={styles.stateMessage}>This area has more updates than can fit here. Zoom in for a complete local list.</p> : null}
    {!loading && !error && viewport && grouped.length === 0 ? <div className={styles.emptyUpdates}><strong>No meaningful updates here recently.</strong><span>There are still current projects you can explore on the map.</span><button onClick={onExplore} type="button">View current projects</button></div> : null}
    <ol className={styles.updateList}>{grouped.map(({ project, events }) => {
      const latest = events[0];
      return <li key={project.id}><button onClick={() => onSelect(project)} type="button"><small>{eventDate(latest.occurred_at ?? latest.observed_at)} · {categoryLabel(project.consumerCategory)}</small><strong>{eventHeadline(latest)}{events.length > 1 ? ` · ${events.length} changes` : ""}</strong><span>{project.name}</span></button></li>;
    })}</ol>
  </section>;
}
