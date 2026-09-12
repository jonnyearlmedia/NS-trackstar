import { MapExplorer } from "@/components/map-explorer";

export default async function ProjectPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <main className="shell">
      <MapExplorer initialProjectId={id} />
    </main>
  );
}
