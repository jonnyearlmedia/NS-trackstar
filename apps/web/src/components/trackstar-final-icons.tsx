import type { ConsumerCategory } from "./map-final-model";

function IconFrame({ children }: { children: React.ReactNode }) {
  return <svg aria-hidden="true" viewBox="0 0 24 24">{children}</svg>;
}

export function SearchIcon() {
  return <IconFrame><path d="m21 21-4.3-4.3m2.3-5.7a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z" /></IconFrame>;
}
export function LocationIcon() {
  return <IconFrame><path d="M12 21s6-5.2 6-11a6 6 0 1 0-12 0c0 5.8 6 11 6 11Z" /><circle cx="12" cy="10" r="2" /></IconFrame>;
}
export function FilterIcon() {
  return <IconFrame><path d="M4 7h16M7 12h10M10 17h4" /></IconFrame>;
}
export function ShareIcon() {
  return <IconFrame><path d="M12 16V3m0 0L7 8m5-5 5 5M5 13v7h14v-7" /></IconFrame>;
}
export function ChevronIcon({ up = false }: { up?: boolean }) {
  return <svg aria-hidden="true" viewBox="0 0 24 24" style={up ? { transform: "rotate(180deg)" } : undefined}><path d="m7 10 5 5 5-5" /></svg>;
}
export function PlayIcon() {
  return <IconFrame><path d="m9 7 8 5-8 5V7Z" /></IconFrame>;
}
export function PauseIcon() {
  return <IconFrame><path d="M9 7v10M15 7v10" /></IconFrame>;
}
export function NextIcon() {
  return <IconFrame><path d="m8 7 7 5-7 5V7ZM17 7v10" /></IconFrame>;
}
export function ArrowRightIcon() {
  return <IconFrame><path d="M5 12h14m-5-5 5 5-5 5" /></IconFrame>;
}

export function CategoryIcon({ category }: { category: ConsumerCategory }) {
  if (category === "development") {
    return <IconFrame><path d="M5 20V8l7-4 7 4v12M9 20v-4h6v4M8 10h2m4 0h2M8 13h2m4 0h2" /></IconFrame>;
  }
  if (category === "roads") {
    return <IconFrame><path d="M8 21 11 3M16 21 13 3M11.7 7h1.1M11.2 11h1.6M10.7 15h2.6M10.2 19h3.6" /></IconFrame>;
  }
  if (category === "utilities") {
    return <IconFrame><path d="m13 2-7 11h5l-1 9 8-12h-5V2Z" /></IconFrame>;
  }
  if (category === "places") {
    return <IconFrame><path d="M4 20h16M6 20v-9l6-5 6 5v9M9 20v-5h6v5M8 9V5h3" /></IconFrame>;
  }
  return <IconFrame><circle cx="12" cy="12" r="7" /><circle cx="12" cy="12" r="2" /></IconFrame>;
}
