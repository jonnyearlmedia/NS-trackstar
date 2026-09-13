"use client";

import { useMemo } from "react";
import { ProjectFreshnessStatus } from "./project-freshness";
import type { MapProject } from "./map-final-model";
import { categoryLabel, eventDate, eventHeadline, lifecycleLabel, locationUncertain, projectSummary, readableValue, type ProjectDetail, type ProjectEvent } from "./trackstar-final-ui";
import { CategoryIcon, ShareIcon } from "./trackstar-final-icons";
import styles from "./map-explorer-v2.module.css";
import extra from "./trackstar-final-extras.module.css";

export function ProjectSheet({ selected, detail, events, state, expanded, onExpanded, onClose, onShare, shareCopied }: {
  selected: MapProject;
  detail: ProjectDetail | null;
  events: ProjectEvent[];
  state: "idle" | "loading" | "error";
  expanded: boolean;
  onExpanded: (value: boolean) => void;
  onClose: () => void;
  onShare: () => void;
  shareCopied: boolean;
}) {
  const latest = events.find((event) => event.event_type !== "project_discovered") ?? null;
  const summary = projectSummary(detail, selected);
  const approximate = locationUncertain(detail, selected);
  const facts = useMemo(() => {
    if (!detail) return [];
    const preferred = ["address", "location_description", "residential_units", "units", "project_units", "site_acres", "location_acres", "building_area_sqft", "developer", "applicant"];
    return preferred.flatMap((field) => {
      const match = detail.assertions.find((assertion) => assertion.field === field);
      return match ? [match] : [];
    }).slice(0, 6);
  }, [detail]);
  const next = detail?.assertions.find((assertion) => ["planned_completion", "completion_date", "planned_start", "construction_start"].includes(assertion.field));
  const statuses = Object.entries(detail?.statuses ?? {}).slice(0, 6);
  const backOneLayer = () => expanded ? onExpanded(false) : onClose();

  return <article className={`${styles.projectCard} ${expanded ? styles.projectCardExpanded : ""}`} aria-label={selected.name}>
    <div className={styles.projectCardHandle}><span /></div>
    <div className={styles.projectTopLine}>
      <button className={styles.breadcrumb} onClick={backOneLayer} type="button">‹ {expanded ? "Project" : categoryLabel(selected.consumerCategory)}</button>
      <div className={styles.projectActions}><button aria-label="Share project" onClick={onShare} type="button"><ShareIcon /></button><button aria-label={expanded ? "Collapse project details" : "Close project"} onClick={backOneLayer} type="button">×</button></div>
    </div>
    <div className={styles.projectScroll}>
      <div className="projectIdentity"><span className="projectIdentityIcon"><CategoryIcon category={selected.consumerCategory} /></span><span><small>{categoryLabel(selected.consumerCategory)}</small><strong>{lifecycleLabel(selected.lifecycleStage)}</strong></span></div>
      <div className={styles.projectTitleBlock}><h2>{detail?.name ?? selected.name}</h2>{approximate ? <span className={styles.approximateBadge}>Approximate location</span> : null}</div>
      {state === "loading" ? <p className={styles.projectLead}>Loading the official project details…</p> : null}
      {state === "error" ? <p className={styles.projectLead}>Trackstar could not load this project’s details right now.</p> : null}
      {state === "idle" ? <><p className={extra.sectionLabel}>What is this?</p><p className={styles.projectLead}>{summary}</p></> : null}
      {latest ? <div className={styles.latestBlock}><small>WHAT'S HAPPENING NOW</small><strong>{eventHeadline(latest)}</strong><span>{eventDate(latest.occurred_at ?? latest.observed_at)}</span></div> : null}
      {!detail?.geometry && state === "idle" ? <p className={styles.locationNotice}><strong>Location not mapped yet.</strong> Trackstar has official records for this project but not enough reliable location information to place it precisely.</p> : approximate ? <p className={styles.locationNotice}>The map shows the best defensible project area from public records, not an exact footprint.</p> : null}
      <ProjectFreshnessStatus projectId={selected.id} expanded={expanded} />
      {shareCopied ? <p className={styles.copyNotice}>Link copied</p> : null}
      <button className={styles.detailsButton} onClick={() => onExpanded(!expanded)} type="button">{expanded ? "Hide details" : "Details & official sources"}<span>{expanded ? "⌃" : "⌄"}</span></button>
      {expanded ? <div className={extra.detailGrid}>
        {facts.length ? <section><h3>Key facts</h3><div className={extra.detailFacts}>{facts.map((fact) => <div className={extra.detailFact} key={fact.field}><small>{fact.field.replaceAll("_", " ")}</small><strong>{readableValue(fact.value)}</strong></div>)}</div></section> : null}
        {next ? <section><h3>What's next?</h3><div className={extra.detailFact}><small>{next.field.replaceAll("_", " ")}</small><strong>{readableValue(next.value)}</strong></div></section> : null}
        {events.length ? <section><h3>Recent activity</h3>{events.slice(0, 8).map((event) => <div className={extra.activityItem} key={event.id}><time>{eventDate(event.occurred_at ?? event.observed_at)}</time><strong>{eventHeadline(event)}</strong></div>)}</section> : null}
        {statuses.length ? <section><h3>Status & history</h3><div className={extra.detailFacts}>{statuses.map(([dimension, value]) => <div className={extra.detailFact} key={dimension}><small>{dimension.replaceAll("_", " ")}</small><strong>{readableValue(value)}</strong></div>)}</div></section> : null}
        {detail?.sources.length ? <section><h3>Official sources</h3><div className={styles.sourceList}>{detail.sources.map((source, index) => <article key={`${source.source_key}-${index}`}><span><strong>{source.source_name}</strong><small>{readableValue(source.relationship_type)}</small></span>{source.url ? <a href={source.url} rel="noreferrer" target="_blank">Open ↗</a> : null}</article>)}</div></section> : null}
      </div> : null}
    </div>
  </article>;
}
