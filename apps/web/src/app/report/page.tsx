import type { Metadata } from "next";
import Link from "next/link";

import styles from "../public-info.module.css";

export const metadata: Metadata = {
  title: "Report wrong information · Trackstar",
  description: "Report a Trackstar project that looks wrong, outdated or misplaced.",
};

type SearchParams = Promise<{ project?: string; name?: string }>;

export default async function ReportPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const project = typeof params.project === "string" ? params.project : "";
  const name = typeof params.name === "string" ? params.name : "";
  const projectPath = project ? `/projects/${encodeURIComponent(project)}` : "";
  const issueParams = new URLSearchParams({
    title: `Trackstar data report${name ? `: ${name}` : ""}`,
    body: [
      "## What looks wrong or outdated?",
      "",
      "Describe the issue here.",
      "",
      "## Project",
      name || "Not specified",
      project ? `Project ID: ${project}` : "Project ID: not specified",
      projectPath ? `Trackstar path: ${projectPath}` : "",
      "",
      "## Helpful evidence",
      "If possible, paste the official public-record link or describe what the official source currently says.",
    ].filter(Boolean).join("\n"),
  });
  const issueUrl = `https://github.com/jonnyearlmedia/NS-trackstar/issues/new?${issueParams.toString()}`;

  return <main className={styles.page}>
    <div className={styles.shell}>
      <Link className={styles.back} href={projectPath || "/"}>‹ Back</Link>
      <section className={styles.hero}>
        <p className={styles.eyebrow}>REPORT WRONG INFORMATION</p>
        <h1>Help Trackstar correct the record.</h1>
        <p className={styles.lead}>Report information that appears wrong, outdated, duplicated or mapped to the wrong place. Trackstar keeps the official-source trail so corrections can be checked against public records.</p>
      </section>
      {project ? <section className={styles.section}><h2>Project attached</h2><p>{name || "Trackstar project"}</p><div className={styles.code}>{project}</div></section> : null}
      <section className={styles.section}>
        <h2>What to include</h2>
        <ul>
          <li>What Trackstar currently says that looks wrong.</li>
          <li>What the official record says instead, if you have it.</li>
          <li>A source link, agenda, permit page or other public evidence when possible.</li>
        </ul>
        <div className={styles.actions}><a className={styles.primary} href={issueUrl} rel="noreferrer" target="_blank">Open report form ↗</a><Link className={styles.secondary} href="/about">How Trackstar handles public records</Link></div>
      </section>
    </div>
  </main>;
}
