"use client";

import type { MapProject } from "./map-final-model";
import { categoryLabel, eventDate, eventHeadline, lifecycleLabel, type ChangeEvent } from "./trackstar-final-ui";
import { ArrowRightIcon, CategoryIcon, NextIcon, PauseIcon, PlayIcon } from "./trackstar-final-icons";
import styles from "./map-explorer-v2.module.css";

function eventTimestamp(change: ChangeEvent | null) {
  const value = change?.occurred_at ?? change?.observed_at;
  if (!value) return null;
  const timestamp = new Date(value).getTime();
  return Number.isFinite(timestamp) ? timestamp : null;
}

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
  const progress = Math.max(0, Math.min(100, ((index + 1) / Math.max(total, 1)) * 100));
  const timestamp = eventTimestamp(change);
  const upcoming = timestamp !== null && timestamp > Date.now() + 60 * 60 * 1000;
  const storyLabel = upcoming ? "UPCOMING" : "WHAT CHANGED";
  return <article className={`${styles.projectCard} briefingCard`} aria-label="Area briefing">
    <div className="briefingProgress" aria-hidden="true"><span style={{ width: `${progress}%` }} /></div>
    <div className="briefingTopline">
      <div className="briefingIdentity"><span className="briefingIcon"><CategoryIcon category={project.consumerCategory} /></span><span><small>AREA BRIEFING</small><strong>{index + 1} of {total}</strong></span></div>
      <button className="briefingClose" aria-label="Exit briefing" onClick={onExit} type="button">×</button>
    </div>
    <div className={styles.projectScroll}>
      <div className="briefingKicker">{categoryLabel(project.consumerCategory)} <span>•</span> {lifecycleLabel(project.lifecycleStage)}</div>
      <h2 className="briefingHeadline">{project.name}</h2>
      {project.locationUncertain ? <span className={styles.approximateBadge}>Approximate location</span> : null}
      {change ? <div className="briefingStory"><small>{storyLabel}</small><strong>{eventHeadline(change)}</strong><span>{eventDate(change.occurred_at ?? change.observed_at)}</span></div> : <div className="briefingStory"><small>CURRENT CONTEXT</small><strong>No recent official change was found for this stop.</strong><span>It is a current project inside the exact map area you chose.</span></div>}
      <div className="briefingControls">
        <button onClick={onPause} type="button">{paused ? <PlayIcon /> : <PauseIcon />}<span>{paused ? "Resume" : "Pause"}</span></button>
        <button disabled={index >= total - 1} onClick={onNext} type="button"><NextIcon /><span>Next</span></button>
      </div>
      <button className="briefingOpen" onClick={onOpen} type="button"><span>Open full project</span><ArrowRightIcon /></button>
    </div>
  </article>;
}
