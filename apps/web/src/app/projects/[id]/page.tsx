import { MapExplorerV5 } from "@/components/map-explorer-v5";

export default async function ProjectPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <main className="shell">
      <MapExplorerV5 initialProjectId={id} />
    </main>
  );
}
