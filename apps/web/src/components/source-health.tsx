"use client";

import { useEffect, useMemo, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type SourceHealth = {
  source_key: string;
  name: string;
  source_family: string;
  jurisdiction: string | null;
  health_state: string | null;
  health_reason: string | null;
  last_attempt_at: string | null;
  last_success_at: string | null;
  records_returned: number | null;
  parser_yield: number | null;
  consecutive_failures: number | null;
};

type SourceCadence = {
  source_key: string;
  stability_state: "stable" | "watch" | "unstable" | "insufficient_history";
  success_rate: number | null;
  change_run_rate: number | null;
  missed_expected_check: boolean;
  overdue_minutes: number | null;
  latest_run: {
    outcome: "changed" | "checked_no_change" | "failed" | null;
  };
};

type CadenceResponse = {
  items: SourceCadence[];
};

function timestamp(value: string | null) {
  if (!value) return "Never";
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function percent(value: number | null | undefined) {
  return value === null || value === undefined ? "—" : `${Math.round(value * 100)}%`;
}

function readable(value: string | null | undefined) {
  return value?.replaceAll("_", " ") ?? "—";
}

function operationallyUnhealthy(state: string | null) {
  return state !== null && !["healthy"].includes(state);
}

export function SourceHealthDashboard() {
  const [sources, setSources] = useState<SourceHealth[]>([]);
  const [cadence, setCadence] = useState<SourceCadence[]>([]);
  const [state, setState] = useState<"loading" | "done" | "error">("loading");

  const cadenceByKey = useMemo(
    () => new Map(cadence.map((item) => [item.source_key, item])),
    [cadence],
  );

  const alertSummary = useMemo(() => {
    const unhealthy = sources.filter((source) => operationallyUnhealthy(source.health_state));
    const missed = cadence.filter((item) => item.missed_expected_check);
    const unstable = cadence.filter((item) => item.stability_state === "unstable");
    const watch = cadence.filter((item) => item.stability_state === "watch");
    return {
      unhealthy,
      missed,
      unstable,
      watch,
      total: new Set([
        ...unhealthy.map((item) => item.source_key),
        ...missed.map((item) => item.source_key),
        ...unstable.map((item) => item.source_key),
        ...watch.map((item) => item.source_key),
      ]).size,
    };
  }, [cadence, sources]);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      fetch(`${API_BASE}/admin/sources/health`, { signal: controller.signal }),
      fetch(`${API_BASE}/admin/sources/cadence?days=7`, { signal: controller.signal }),
    ])
      .then(async ([healthResponse, cadenceResponse]) => {
        if (!healthResponse.ok) throw new Error(`Source health API returned ${healthResponse.status}`);
        const healthData = await healthResponse.json() as SourceHealth[];
        let cadenceData: SourceCadence[] = [];
        if (cadenceResponse.ok) {
          const payload = await cadenceResponse.json() as CadenceResponse;
          cadenceData = payload.items;
        }
        return { healthData, cadenceData };
      })
      .then(({ healthData, cadenceData }) => {
        setSources(healthData);
        setCadence(cadenceData);
        setState("done");
      })
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState("error");
      });
    return () => controller.abort();
  }, []);

  return (
    <main className="adminShell">
      <header className="adminHeader">
        <div>
          <p className="eyebrow">OPERATIONS</p>
          <h1>Source health</h1>
        </div>
        <a href="/">Back to map</a>
      </header>
      {state === "loading" ? <p className="emptyMessage">Loading collector health…</p> : null}
      {state === "error" ? <p className="errorMessage">Collector health is unavailable.</p> : null}

      {state === "done" ? (
        <section className="healthGrid" aria-label="Source alerts">
          <article className="healthCard">
            <header><div><p className="cardMeta">OPERATOR ALERTS</p><h2>{alertSummary.total ? `${alertSummary.total} sources need attention` : "No active source alerts"}</h2></div></header>
            <dl className="healthFacts">
              <div><dt>Unhealthy now</dt><dd>{alertSummary.unhealthy.length}</dd></div>
              <div><dt>Missed checks</dt><dd>{alertSummary.missed.length}</dd></div>
              <div><dt>Unstable 7-day history</dt><dd>{alertSummary.unstable.length}</dd></div>
              <div><dt>Watch</dt><dd>{alertSummary.watch.length}</dd></div>
            </dl>
            {alertSummary.total ? <p className="healthReason">Review the source cards below before trusting freshness-sensitive public updates from flagged sources.</p> : null}
          </article>
        </section>
      ) : null}

      <section className="healthGrid" aria-live="polite">
        {sources.map((source) => {
          const sourceCadence = cadenceByKey.get(source.source_key);
          return (
            <article className="healthCard" key={source.source_key}>
              <header>
                <div>
                  <p className="cardMeta">{source.jurisdiction ?? source.source_family}</p>
                  <h2>{source.name}</h2>
                </div>
                <span className="healthState" data-state={source.health_state ?? "unknown"}>
                  {source.health_state?.replaceAll("_", " ") ?? "not run"}
                </span>
              </header>
              <dl className="healthFacts">
                <div><dt>Last success</dt><dd>{timestamp(source.last_success_at)}</dd></div>
                <div><dt>Last attempt</dt><dd>{timestamp(source.last_attempt_at)}</dd></div>
                <div><dt>Records</dt><dd>{source.records_returned ?? "—"}</dd></div>
                <div><dt>Parser yield</dt><dd>{source.parser_yield === null ? "—" : `${Math.round(source.parser_yield * 100)}%`}</dd></div>
                <div><dt>7-day stability</dt><dd>{sourceCadence ? `${readable(sourceCadence.stability_state)} · ${percent(sourceCadence.success_rate)}` : "—"}</dd></div>
                <div><dt>Latest outcome</dt><dd>{readable(sourceCadence?.latest_run.outcome)}</dd></div>
                <div><dt>Change-run rate</dt><dd>{percent(sourceCadence?.change_run_rate)}</dd></div>
                <div><dt>Missed check</dt><dd>{sourceCadence?.missed_expected_check ? `Yes${sourceCadence.overdue_minutes ? ` · ${sourceCadence.overdue_minutes}m` : ""}` : "No"}</dd></div>
              </dl>
              {source.health_reason ? <p className="healthReason">{source.health_reason}</p> : null}
              {sourceCadence?.stability_state === "unstable" ? <p className="healthReason">Repeated failures in the 7-day audit window; latest health alone is not sufficient.</p> : null}
            </article>
          );
        })}
      </section>
    </main>
  );
}
