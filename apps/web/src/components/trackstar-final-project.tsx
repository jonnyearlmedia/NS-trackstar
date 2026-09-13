"use client";

import { useMemo } from "react";
import { ProjectFreshnessStatus } from "./project-freshness";
import type { MapProject } from "./map-final-model";
import { categoryLabel, eventDate, eventHeadline, lifecycleLabel, locationUncertain, projectSummary, readableValue, type ProjectDetail, type ProjectEvent } from "./trackstar-final-ui";
import { CategoryIcon, ChevronIcon, ShareIcon } from "./trackstar-final-icons";
import styles from "./map-explorer-v2.module.css";
import extra from "./trackstar-final-extras.module.css";

const FACT_LABELS: Record<string, string> = {
  address: "Address",
  location_description: "Location",
  residential_units: "Homes",
  units: "Units",
  project_units: "Units",
  site_acres: "Site size",
  location_acres: "Site size",
  building_area_sqft: "Building area",
  developer: "Developer",
  applicant: "Applicant",
};

function clippedDescription(value: unknown) {
  if (typeof value !== "string") return null;
  const clean = value.trim();
  if (!clean) return null;
  return clean.length > 320 ? `${clean.slice(0, 317).trimEnd()}…` : clean;
}

function numericValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value.replaceAll(",", "")))) return Number(value.replaceAll(",", ""));
  return null;
}

function factValue(field: string, value: unknown) {
  const numeric = numericValue(value);
  if (numeric !== null && ["residential_units", "units", "project_units"].includes(field)) return `${new Intl.NumberFormat("en-US").format(numeric)} units`;
  if (numeric !== null && ["site_acres", "location_acres"].includes(field)) return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(numeric)} acres`;
  if (numeric !== null && field === "building_area_sqft") return `${new Intl.NumberFormat("en-US").format(numeric)} sq ft`;
  return readableValue(value);
}

function currentActivityFallback(selected: MapProject) {
  if (selected.lifecycleStage === "unknown") return "The official records do not give Trackstar a clear current project stage yet.";
  return `Official records currently place this project at: ${lifecycleLabel(selected.lifecycleStage)}.`;
}

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
  const officialDescription = detail?.assertions.find((assertion) => assertion.field === "description")?.value;
  const summary = detail?.summary?.trim() || clippedDescription(officialDescription) || projectSummary(detail, selected);
  const approximate = locationUncertain(detail, selected);
  const facts = useMemo(() => {
    if (!detail) return [];
    const preferred = ["address", "location_description", "residential_units", "units", "project_units", "site_acres", "location_acres", "building_area_sqft", "developer", "applicant"];
    const seen = new Set<string>();
    return preferred.flatMap((field) => {
      if (seen.has(field)) return [];
      const match = detail.assertions.find((assertion) => assertion.field === field);
      if (!match || match.value === null || match.value === undefined || match.value === "") return [];
      seen.add(field);
      return [match];
    }).slice(0, 6);
  }, [detail]);
  const next = detail?.assertions.find((assertion) => ["planned_completion", "completion_date", "planned_start", "construction_start"].includes(assertion.field));
  const statuses = Object.entries(detail?.statuses ?? {}).slice(0, 6);
  const backOneLayer = () => expanded ? onExpanded(false) : onClose();
  const reportHref = `/report?${new URLSearchParams({ project: selected.id, name: detail?.name ?? selected.name }).toString()}`;

  return <article className={`${styles.projectCard} ${expanded ? styles.projectCardExpanded : ""}`} aria-label={selected.name}>
    <div className={styles.projectCardHandle}><span /></div>
    <div className={styles.projectTopLine}>
      <button className={styles.breadcrumb} onClick={backOneLayer} type="button">‹ {expanded ? "Project" : "Map"}</button>
      <div className={styles.projectActions}><button aria-label="Share project" onClick={onShare} type="button"><ShareIcon /></button><button aria-label={expanded ? "Collapse project details" : "Close project"} onClick={backOneLayer} type="button">×</button></div>
    </div>
    <div className={styles.projectScroll}>
      <div className="projectIdentity" data-category={selected.consumerCategory}>
        <span className="projectIdentityIcon"><CategoryIcon category={selected.consumerCategory} /></span>
        <span><small>{categoryLabel(selected.consumerCategory)}</small><strong>{lifecycleLabel(selected.lifecycleStage)}</strong></span>
      </div>
      <div className={styles.projectTitleBlock}>
        <h2>{detail?.name ?? selected.name}</h2>
        {approximate ? <span className={styles.approximateBadge}>Approximate location</span> : null}
      </div>
      <div className="projectRule" />
      {state === "loading" ? <p className={styles.projectLead}>Loading the official project details…</p> : null}
      {state === "error" ? <p className={styles.projectLead}>Trackstar could not load this project’s details right now.</p> : null}
      {state === "idle" ? <section className="projectOverview"><p className={extra.sectionLabel}>What is this?</p><p className={styles.projectLead}>{summary}</p></section> : null}
      {state === "idle" ? <div className={styles.latestBlock}><small>WHAT'S HAPPENING</small><strong>{latest ? eventHeadline(latest) : currentActivityFallback(selected)}</strong>{latest ? <span>{eventDate(latest.occurred_at ?? latest.observed_at)}</span> : null}</div> : null}
      {!detail?.geometry && state === "idle" ? <p className={styles.locationNotice}><strong>Location not mapped yet.</strong> Trackstar has official records for this project but not enough reliable location information to place it precisely.</p> : approximate ? <p className={styles.locationNotice}>The map shows the best defensible project area from public records, not an exact footprint.</p> : null}
      <ProjectFreshnessStatus projectId={selected.id} expanded={expanded} />
      {shareCopied ? <p className={styles.copyNotice}>Link copied</p> : null}
      <button className={styles.detailsButton} onClick={() => onExpanded(!expanded)} type="button"><span>{expanded ? "Hide details" : "Details & official sources"}</span><ChevronIcon up={expanded} /></button>
      {expanded ? <div className={extra.detailGrid}>
        {facts.length ? <section><h3>Key facts</h3><div className={extra.detailFacts}>{facts.map((fact) => <div className={extra.detailFact} key={fact.field}><small>{FACT_LABELS[fact.field] ?? fact.field.replaceAll("_", " ")}</small><strong>{factValue(fact.field, fact.value)}</strong></div>)}</div></section> : null}
        {next ? <section><h3>What's next?</h3><div className={extra.detailFact}><small>{next.field.replaceAll("_", " ")}</small><strong>{readableValue(next.value)}</strong></div></section> : null}
        {events.length ? <section><h3>Recent activity</h3>{events.slice(0, 8).map((event) => <div className={extra.activityItem} key={event.id}><time>{eventDate(event.occurred_at ?? event.observed_at)}</time><strong>{eventHeadline(event)}</strong></div>)}</section> : null}
        {statuses.length ? <section><h3>Status & history</h3><div className={extra.detailFacts}>{statuses.map(([dimension, value]) => <div className={extra.detailFact} key={dimension}><small>{dimension.replaceAll("_", " ")}</small><strong>{readableValue(value)}</strong></div>)}</div></section> : null}
        {detail?.sources.length ? <section><h3>Official sources · {detail.sources.length}</h3><div className={styles.sourceList}>{detail.sources.map((source, index) => <article key={`${source.source_key}-${index}`}><span><strong>{source.source_name}</strong><small>{readableValue(source.relationship_type)}</small></span>{source.url ? <a href={source.url} rel="noreferrer" target="_blank">Open ↗</a> : null}</article>)}</div></section> : null}
        <section className="projectTrust"><p>Trackstar summarizes public records and may lag an upstream agency. It is not an official permit, approval or legal notice.</p><div><a href="/about">How Trackstar works</a><a href={reportHref}>Report wrong info</a></div></section>
      </div> : null}
    </div>
  </article>;
}
