import { TrackstarFinal } from "@/components/trackstar-final";

export default async function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <main className="shell">
      <TrackstarFinal initialProjectId={id} />
    </main>
  );
}
