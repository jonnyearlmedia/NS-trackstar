"use client";

import type { AppView } from "./trackstar-final-ui";
import { SearchIcon } from "./trackstar-final-icons";
import styles from "./map-explorer-v2.module.css";
import extra from "./trackstar-final-extras.module.css";

export function TopChrome({ onReset, onSearch }: { onReset: () => void; onSearch: () => void }) {
  return <header className={styles.topBar}>
    <button aria-label="Reset to Napa and Solano" className={styles.brand} onClick={onReset} type="button">
      <img alt="" src="/trackstar-icon.svg" style={{ width: 42, height: 42, borderRadius: 13 }} />
      <span><strong>Trackstar</strong><small>Napa · Solano</small></span>
    </button>
    <button className={styles.searchButton} onClick={onSearch} type="button"><SearchIcon /><span>Search address, road or project</span></button>
  </header>;
}

export function BottomNav({ view, onView }: { view: AppView; onView: (view: AppView) => void }) {
  return <nav className={styles.bottomNav} aria-label="Trackstar sections"><button className={view === "explore" ? styles.navSelected : ""} onClick={() => onView("explore")} type="button">Explore</button><button className={view === "updates" ? styles.navSelected : ""} onClick={() => onView("updates")} type="button">Updates</button></nav>;
}

export function CoverageNotice({ outside, onReturn }: { outside: boolean; onReturn: () => void }) {
  if (!outside) return null;
  return <div className={extra.coverageNotice} role="status"><span><strong>Outside Trackstar coverage</strong><small>Trackstar currently covers Napa + Solano.</small></span><button onClick={onReturn} type="button">View coverage</button></div>;
}
