import { MapExplorerV3 } from "@/components/map-explorer-v3";

export default async function ProjectPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <main className="shell">
      <MapExplorerV3 initialProjectId={id} />
    </main>
  );
}
