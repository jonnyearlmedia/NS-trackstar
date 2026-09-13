"use client";

import { useEffect, useMemo, useState } from "react";
import styles from "./coverage-scorecard.module.css";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type CoverageState = "strong" | "partial" | "blocked" | "missing";

type CategoryRow = {
  category: string;
  category_title: string;
  state: CoverageState;
  production_sources: string[];
  unpromoted_sources: string[];
  limitation: string | null;
  blocker: { reason?: string; smoke_source?: string } | null;
};

type Scorecard = {
  service_area: string;
  categories: Array<{ key: string; title: string; description: string }>;
  jurisdictions: Array<{
    key: string;
    name: string;
    county: string;
    score: number;
    categories: CategoryRow[];
  }>;
  totals: Record<CoverageState, number>;
};

const STATE_LABEL: Record<CoverageState, string> = {
  strong: "Strong",
  partial: "Partial",
  blocked: "Blocked",
  missing: "Missing",
};

function cellTitle(row: CategoryRow) {
  const parts = [`${row.category_title}: ${STATE_LABEL[row.state]}`];
  if (row.production_sources.length) parts.push(`Sources: ${row.production_sources.join(", ")}`);
  if (row.unpromoted_sources.length) parts.push(`Not promoted: ${row.unpromoted_sources.join(", ")}`);
  if (row.limitation) parts.push(row.limitation);
  if (row.blocker?.reason) parts.push(`Blocked: ${row.blocker.reason}`);
  return parts.join("\n");
}

export function CoverageScorecard() {
  const [scorecard, setScorecard] = useState<Scorecard | null>(null);
  const [state, setState] = useState<"loading" | "done" | "error">("loading");

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_BASE}/admin/coverage`, { signal: controller.signal, cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error(`coverage returned ${response.status}`);
        return response.json() as Promise<Scorecard>;
      })
      .then((payload) => {
        setScorecard(payload);
        setState("done");
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState("error");
      });
    return () => controller.abort();
  }, []);

  // Gaps are the point of this page: a jurisdiction with parcels and CEQA records
  // is not covered, and this list is what says so out loud.
  const gaps = useMemo(() => {
    if (!scorecard) return [];
    return scorecard.jurisdictions.flatMap((jurisdiction) =>
      jurisdiction.categories
        .filter((row) => row.state === "blocked" || row.state === "missing")
        .map((row) => ({ jurisdiction: jurisdiction.name, row })),
    );
  }, [scorecard]);

  if (state === "loading") return <main className={styles.page}><p>Loading the coverage scorecard…</p></main>;
  if (state === "error" || !scorecard) {
    return <main className={styles.page}><p>The coverage scorecard is unavailable right now.</p></main>;
  }

  return (
    <main className={styles.page}>
      <h1>Coverage scorecard</h1>
      <p className={styles.lede}>
        Coverage is tracked per jurisdiction per source category, never by counting map dots.
        A jurisdiction is only <strong>strong</strong> in a category when a recurring production
        source actually inventories it. Statewide CEQA filings and county parcels are real
        evidence, but they never count as local development or permit coverage.
      </p>

      <div className={styles.totals}>
        {(["strong", "partial", "blocked", "missing"] as CoverageState[]).map((key) => (
          <div key={key}>
            <small>{STATE_LABEL[key]}</small>
            <strong>{scorecard.totals[key]}</strong>
          </div>
        ))}
      </div>

      <div className={styles.grid}>
        <table>
          <thead>
            <tr>
              <th scope="col">Jurisdiction</th>
              {scorecard.categories.map((category) => (
                <th key={category.key} scope="col" title={category.description}>{category.title}</th>
              ))}
              <th scope="col">Score</th>
            </tr>
          </thead>
          <tbody>
            {scorecard.jurisdictions.map((jurisdiction) => (
              <tr key={jurisdiction.key}>
                <th scope="row">{jurisdiction.name}</th>
                {jurisdiction.categories.map((row) => (
                  <td key={row.category}>
                    <span className={`${styles.cell} ${styles[row.state]}`} title={cellTitle(row)}>
                      {STATE_LABEL[row.state]}
                    </span>
                  </td>
                ))}
                <td>{Math.round(jurisdiction.score * 100)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <section className={styles.gaps}>
        <h2>Incomplete source categories · {gaps.length}</h2>
        <p className={styles.state}>Every row here is work that has not been done, or a documented upstream blocker.</p>
        <ul>
          {gaps.map(({ jurisdiction, row }) => (
            <li key={`${jurisdiction}-${row.category}`}>
              <strong>{jurisdiction} · {row.category_title} · {STATE_LABEL[row.state]}</strong>
              <span>
                {row.blocker?.reason ??
                  "No production source has been implemented for this jurisdiction and category yet."}
                {row.unpromoted_sources.length ? ` Not promoted: ${row.unpromoted_sources.join(", ")}.` : ""}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
