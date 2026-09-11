import { MapCanvas } from "@/components/map-canvas";

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

      <section className="mapStage" aria-label="Napa and Solano intelligence map">
        <MapCanvas />
        <div className="mapShade" />

        <article className="projectCard">
          <p className="cardMeta">PROJECT INTELLIGENCE</p>
          <h2>NS Trackstar is live</h2>
          <p>The real Napa–Solano basemap is wired. Government-backed project geometry and the first data layers plug into this surface next.</p>
          <div className="cardFooter">
            <span>Exact geometry when known</span>
            <span>Source-backed</span>
          </div>
        </article>
      </section>
    </main>
  );
}
