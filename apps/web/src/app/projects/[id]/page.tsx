import { MapExplorerV2 } from "@/components/map-explorer-v2";

export default async function ProjectPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <main className="shell">
      <MapExplorerV2 initialProjectId={id} />
    </main>
  );
}
