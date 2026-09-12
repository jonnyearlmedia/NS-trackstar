import { MapExplorerV6 } from "@/components/map-explorer-v6";

export default async function ProjectPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <main className="shell">
      <MapExplorerV6 initialProjectId={id} />
    </main>
  );
}
