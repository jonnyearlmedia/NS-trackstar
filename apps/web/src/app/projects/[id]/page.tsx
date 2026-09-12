import { MapExplorerV4 } from "@/components/map-explorer-v4";

export default async function ProjectPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <main className="shell">
      <MapExplorerV4 initialProjectId={id} />
    </main>
  );
}
