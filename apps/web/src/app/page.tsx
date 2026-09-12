import { MapExplorer } from "@/components/map-explorer";

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

      <MapExplorer />
    </main>
  );
}
