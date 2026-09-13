import type { Metadata } from "next";
import Link from "next/link";

import styles from "../public-info.module.css";

export const metadata: Metadata = {
  title: "About Trackstar",
  description: "How Trackstar uses public records for Napa and Solano project intelligence.",
};

export default function AboutTrackstarPage() {
  return <main className={styles.page}>
    <div className={styles.shell}>
      <Link className={styles.back} href="/">‹ Back to map</Link>
      <section className={styles.hero}>
        <p className={styles.eyebrow}>ABOUT TRACKSTAR</p>
        <h1>Public records, organized around real places.</h1>
        <p className={styles.lead}>Trackstar helps people understand development, roads, utilities and public-place projects across Napa and Solano counties without needing to know planning systems, permit portals or GIS tools.</p>
      </section>
      <section className={styles.section}>
        <h2>What Trackstar does</h2>
        <ul>
          <li>Combines information from official city, county, regional, state and federal public-record sources.</li>
          <li>Connects records that appear to describe the same real-world project while preserving their original sources.</li>
          <li>Shows mapped locations only when the available public evidence supports a defensible location.</li>
          <li>Links back to official records so you can inspect the source yourself.</li>
        </ul>
      </section>
      <section className={styles.section}>
        <h2>What Trackstar does not do</h2>
        <p>Trackstar is not an official government record, permit approval, legal notice or guarantee that a project will happen exactly as summarized. Public systems can change, disagree, publish incomplete information or update after Trackstar last checked them.</p>
      </section>
      <section className={styles.section}>
        <h2>Location and status honesty</h2>
        <p>Exact parcels, corridors and points are used when the source supports them. Approximate locations are labeled. Projects with no defensible geometry remain searchable instead of being given a fake pin. Status language is intentionally conservative when official records are ambiguous.</p>
      </section>
      <section className={styles.section}>
        <h2>See something wrong?</h2>
        <p>Use the report link on a project card. Include the project and the official source that looks wrong or outdated when possible.</p>
        <div className={styles.actions}><Link className={styles.primary} href="/report">Report wrong information</Link><Link className={styles.secondary} href="/">Explore the map</Link></div>
      </section>
    </div>
  </main>;
}
