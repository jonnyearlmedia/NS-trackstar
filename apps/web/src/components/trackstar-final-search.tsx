"use client";

import type { FormEvent } from "react";
import { categoryLabel, lifecycleLabel, type SearchResult } from "./trackstar-final-ui";
import { ArrowRightIcon, CategoryIcon, SearchIcon } from "./trackstar-final-icons";
import styles from "./map-explorer-v2.module.css";

export function SearchOverlay({ query, results, state, onQuery, onClose, onSelect }: {
  query: string;
  results: SearchResult[];
  state: "idle" | "loading" | "done" | "error";
  onQuery: (value: string) => void;
  onClose: () => void;
  onSelect: (result: SearchResult) => void;
}) {
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); }
  return <aside className={styles.searchOverlay} aria-label="Search Trackstar">
    <header><button aria-label="Close search" onClick={onClose} type="button">‹</button><form onSubmit={submit}><SearchIcon /><input autoFocus onChange={(event) => onQuery(event.target.value)} placeholder="Search project, address, road or place" type="search" value={query} /></form></header>
    <div className={styles.searchBody}>
      {!query.trim() ? <div className={styles.searchHint}><strong>Find something you saw or heard about.</strong><span>Try a project name, road, address, business name, or place.</span></div> : null}
      {state === "loading" ? <p className={styles.stateMessage}>Searching…</p> : null}
      {state === "error" ? <p className={styles.stateMessage}>Search is temporarily unavailable.</p> : null}
      {state === "done" && results.length === 0 ? <div className={styles.searchHint}><strong>No Trackstar match found for “{query.trim()}.”</strong><span>Try another name or address. This does not mean no project exists.</span></div> : null}
      <div className={styles.searchResults}>{results.map((result) => <button className="contentResultRow" key={result.id} onClick={() => onSelect(result)} type="button"><span className="contentResultIcon"><CategoryIcon category={result.consumer_category} /></span><span className="contentResultCopy"><small>{categoryLabel(result.consumer_category)} · {lifecycleLabel(result.lifecycle_stage)}</small><strong>{result.name}</strong>{result.summary ? <em>{result.summary}</em> : null}</span><span className="contentResultArrow"><ArrowRightIcon /></span></button>)}</div>
    </div>
  </aside>;
}
