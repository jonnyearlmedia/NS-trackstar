const filters = ["Today", "This Week", "Upcoming", "All"];

export default function HomePage() {
  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">NAPA · SOLANO</p>
          <h1>NS Trackstar</h1>
        </div>
        <button className="searchButton" type="button">Search</button>
      </header>

      <nav className="filters" aria-label="Time filters">
        {filters.map((filter, index) => (
          <button className={index === 1 ? "filter active" : "filter"} key={filter} type="button">
            {filter}
          </button>
        ))}
      </nav>

      <section className="mapStage" aria-label="Map placeholder">
        <div className="mapGrid" />
        <div className="regionLabel">Napa + Solano</div>
        <div className="project projectA"><span /></div>
        <div className="project projectB"><span /></div>
        <div className="project projectC"><span /></div>

        <article className="projectCard">
          <p className="cardMeta">PROJECT INTELLIGENCE</p>
          <h2>Phase 0 foundation</h2>
          <p>The map shell is live. Structured project data, provenance, source health, and real geometry plug into this surface next.</p>
          <div className="cardFooter">
            <span>Exact geometry when known</span>
            <span>Source-backed</span>
          </div>
        </article>
      </section>
    </main>
  );
}
