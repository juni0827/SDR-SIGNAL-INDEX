import { RecordingDetailView } from "@/components/catalog-views";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <RecordingDetailView id={id}/>;
}
