"use client";

import { useEffect, useState } from "react";

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

function timestamp(value: string | null) {
  if (!value) return "Never";
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function SourceHealthDashboard() {
  const [sources, setSources] = useState<SourceHealth[]>([]);
  const [state, setState] = useState<"loading" | "done" | "error">("loading");

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_BASE}/admin/sources/health`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Source health API returned ${response.status}`);
        return response.json() as Promise<SourceHealth[]>;
      })
      .then((data) => {
        setSources(data);
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
      <section className="healthGrid" aria-live="polite">
        {sources.map((source) => (
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
            </dl>
            {source.health_reason ? <p className="healthReason">{source.health_reason}</p> : null}
          </article>
        ))}
      </section>
    </main>
  );
}
