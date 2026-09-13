"use client";

import { ProjectFreshnessStatus } from "./project-freshness";
import type { MapProject } from "./map-final-model";
import { categoryLabel, eventDate, eventHeadline, lifecycleLabel, locationUncertain, projectSummary, readableValue, type EvidenceSection, type ProjectDetail, type ProjectEvent } from "./trackstar-final-ui";
import { CategoryIcon, ChevronIcon, ShareIcon } from "./trackstar-final-icons";
import styles from "./map-explorer-v2.module.css";
import extra from "./trackstar-final-extras.module.css";

// Sections a normal person reads first stay above the identifier sections. Nothing is
// dropped: the backend groups every assertion, and anything it has no opinion about
// still arrives in "Other details".
const SECTION_ORDER = ["scale", "location", "people", "schedule", "money", "approvals", "environmental", "identifiers", "other"];

function orderedSections(detail: ProjectDetail | null): EvidenceSection[] {
  const sections = detail?.evidence_sections ?? [];
  return [...sections].sort((left, right) => {
    const leftRank = SECTION_ORDER.indexOf(left.key);
    const rightRank = SECTION_ORDER.indexOf(right.key);
    return (leftRank < 0 ? SECTION_ORDER.length : leftRank) - (rightRank < 0 ? SECTION_ORDER.length : rightRank);
  });
}

function currentActivityFallback(selected: MapProject) {
  if (selected.lifecycleStage === "unknown") return "The official records do not give Trackstar a clear current project stage yet.";
  return `Official records currently place this project at: ${lifecycleLabel(selected.lifecycleStage)}.`;
}

function EvidenceRows({ section }: { section: EvidenceSection }) {
  return <div className={extra.detailFacts}>
    {section.items.map((item) => <div className={extra.detailFact} key={item.field}>
      <small>{item.label}</small>
      {item.source_url ? <strong><a href={item.source_url} rel="noreferrer" target="_blank">{item.value}</a></strong> : <strong>{item.value}</strong>}
    </div>)}
  </div>;
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
  const explainer = detail?.explainer ?? null;
  const latest = events.find((event) => event.event_type !== "project_discovered") ?? null;
  const summary = projectSummary(detail, selected);
  const approximate = locationUncertain(detail, selected);
  const whyCare = explainer?.why_care ?? [];
  const happening = explainer?.whats_happening ?? (latest ? eventHeadline(latest) : currentActivityFallback(selected));
  const happeningDate = explainer?.whats_happening ? null : latest ? eventDate(latest.occurred_at ?? latest.observed_at) : null;
  const sections = orderedSections(detail);
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
      {state === "idle" ? <div className={styles.latestBlock}><small>WHAT&apos;S HAPPENING</small><strong>{happening}</strong>{happeningDate ? <span>{happeningDate}</span> : null}</div> : null}
      {state === "idle" && whyCare.length ? <section className="projectOverview"><p className={extra.sectionLabel}>Why you&apos;d care</p><div className={extra.detailFacts}>{whyCare.map((fact) => <div className={extra.detailFact} key={fact.field}><small>{fact.label}</small><strong>{fact.value}</strong></div>)}</div></section> : null}
      {state === "idle" && explainer?.whats_next ? <section className="projectOverview"><p className={extra.sectionLabel}>What happens next?</p><p className={styles.projectLead}>{explainer.whats_next}</p></section> : null}
      {!detail?.geometry && state === "idle" ? <p className={styles.locationNotice}><strong>Location not mapped yet.</strong> Trackstar has official records for this project but not enough reliable location information to place it precisely.</p> : approximate ? <p className={styles.locationNotice}>The map shows the best defensible project area from public records, not an exact footprint.</p> : null}
      <ProjectFreshnessStatus projectId={selected.id} expanded={expanded} />
      {shareCopied ? <p className={styles.copyNotice}>Link copied</p> : null}
      <button className={styles.detailsButton} onClick={() => onExpanded(!expanded)} type="button"><span>{expanded ? "Hide details" : "Details & official sources"}</span><ChevronIcon up={expanded} /></button>
      {expanded ? <div className={extra.detailGrid}>
        {events.length ? <section><h3>Timeline</h3>{events.slice(0, 12).map((event) => <div className={extra.activityItem} key={event.id}><time>{eventDate(event.occurred_at ?? event.observed_at)}</time><strong>{eventHeadline(event)}</strong></div>)}</section> : null}
        {sections.map((section) => <section key={section.key}><h3>{section.title}</h3><EvidenceRows section={section} /></section>)}
        {statuses.length ? <section><h3>Official status dimensions</h3><div className={extra.detailFacts}>{statuses.map(([dimension, value]) => <div className={extra.detailFact} key={dimension}><small>{dimension.replaceAll("_", " ")}</small><strong>{readableValue(value)}</strong></div>)}</div></section> : null}
        {detail?.sources.length ? <section><h3>Official sources · {detail.sources.length}</h3><div className={styles.sourceList}>{detail.sources.map((source, index) => <article key={`${source.source_key}-${index}`}><span><strong>{source.source_name}</strong><small>{readableValue(source.relationship_type)}</small></span>{source.url ? <a href={source.url} rel="noreferrer" target="_blank">Open ↗</a> : null}</article>)}</div></section> : null}
        <section className="projectTrust"><p>Trackstar summarizes public records and may lag an upstream agency. It is not an official permit, approval or legal notice.</p><div><a href="/about">How Trackstar works</a><a href={reportHref}>Report wrong info</a></div></section>
      </div> : null}
    </div>
  </article>;
}
