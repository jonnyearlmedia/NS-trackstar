import { MapExplorer } from "@/components/map-explorer";

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

      <MapExplorer />
    </main>
  );
}
