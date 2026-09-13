"use client";

import type { MapProject } from "./map-final-model";
import { categoryLabel, eventDate, eventHeadline, lifecycleLabel, type ChangeEvent } from "./trackstar-final-ui";
import styles from "./map-explorer-v2.module.css";

export function BriefingCard({ project, index, total, change, paused, onPause, onNext, onOpen, onExit }: {
  project: MapProject;
  index: number;
  total: number;
  change: ChangeEvent | null;
  paused: boolean;
  onPause: () => void;
  onNext: () => void;
  onOpen: () => void;
  onExit: () => void;
}) {
  return <article className={styles.projectCard} aria-label="Area briefing">
    <div className={styles.projectCardHandle}><span /></div>
    <div className={styles.projectTopLine}><span className={styles.breadcrumb}>AREA BRIEFING · {index + 1} OF {total}</span><div className={styles.projectActions}><button aria-label="Exit briefing" onClick={onExit} type="button">×</button></div></div>
    <div className={styles.projectScroll}>
      <div className={styles.projectTitleBlock}><small>{categoryLabel(project.consumerCategory)} · {lifecycleLabel(project.lifecycleStage)}</small><h2>{project.name}</h2>{project.locationUncertain ? <span className={styles.approximateBadge}>Approximate location</span> : null}</div>
      {change ? <div className={styles.latestBlock}><small>RECENT CHANGE</small><strong>{eventHeadline(change)}</strong><span>{eventDate(change.occurred_at ?? change.observed_at)}</span></div> : <p className={styles.projectLead}>A current project in the map area you chose.</p>}
      <div className={styles.panelFooter}><button onClick={onPause} type="button">{paused ? "Resume" : "Pause"}</button><button disabled={index >= total - 1} onClick={onNext} type="button">Next</button></div>
      <button className={styles.detailsButton} onClick={onOpen} type="button">Open this project <span>›</span></button>
    </div>
  </article>;
}
