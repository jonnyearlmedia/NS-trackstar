"use client";

import { useEffect, useMemo, useState } from "react";

import styles from "./project-freshness.module.css";

const API_BASE = "/api/backend";

type FreshnessState = "current" | "stale" | "unknown";

type SourceFreshness = {
  source_key: string;
  source_name: string;
  freshness_state: FreshnessState;
  last_success_at: string | null;
  checked_minutes_ago: number | null;
};

type ProjectFreshness = {
  project_id: string;
  freshness_state: FreshnessState;
  checked_minutes_ago: number | null;
  sources: SourceFreshness[];
  metadata: {
    source_count: number;
    stale_source_count: number;
    unknown_source_count: number;
  };
};

function ageLabel(minutes: number | null) {
  if (minutes === null) return null;
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 24 * 60) {
    const hours = Math.floor(minutes / 60);
    return `${hours} hr${hours === 1 ? "" : "s"} ago`;
  }
  const days = Math.floor(minutes / (24 * 60));
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

function sourceStatus(source: SourceFreshness) {
  const age = ageLabel(source.checked_minutes_ago);
  if (source.freshness_state === "stale") return age ? `May be stale · checked ${age}` : "Freshness unknown";
  if (source.freshness_state === "unknown") return "Check time unavailable";
  return age ? `Checked ${age}` : "Current";
}

export function ProjectFreshnessStatus({ projectId, expanded }: { projectId: string | null; expanded: boolean }) {
  const [freshness, setFreshness] = useState<ProjectFreshness | null>(null);

  useEffect(() => {
    if (!projectId) { setFreshness(null); return; }
    const controller = new AbortController();
    setFreshness(null);
    fetch(`${API_BASE}/projects/${projectId}/freshness`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Freshness API returned ${response.status}`);
        return response.json() as Promise<ProjectFreshness>;
      })
      .then(setFreshness)
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setFreshness(null);
      });
    return () => controller.abort();
  }, [projectId]);

  const sortedSources = useMemo(() => {
    if (!freshness) return [];
    const priority: Record<FreshnessState, number> = { stale: 0, unknown: 1, current: 2 };
    return [...freshness.sources].sort((a, b) => priority[a.freshness_state] - priority[b.freshness_state] || a.source_name.localeCompare(b.source_name));
  }, [freshness]);

  if (!freshness || freshness.metadata.source_count === 0) return null;

  const age = ageLabel(freshness.checked_minutes_ago);
  return (
    <>
      {freshness.freshness_state === "stale" ? (
        <p className={styles.freshnessWarning}><strong>Some official records may be stale.</strong>{age ? ` Oldest successful check was ${age}.` : " A recent successful check is not available."}</p>
      ) : freshness.freshness_state === "current" && age ? (
        <p className={styles.freshnessLine}>Official source checks current · oldest {age}</p>
      ) : null}
      {expanded ? (
        <section className={styles.freshnessDetail}><h3>Source freshness</h3><div>{sortedSources.map((source) => <article key={source.source_key}><strong>{source.source_name}</strong><span data-state={source.freshness_state}>{sourceStatus(source)}</span></article>)}</div></section>
      ) : null}
    </>
  );
}
