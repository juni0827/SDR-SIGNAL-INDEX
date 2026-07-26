import { SessionDetailView } from "@/components/catalog-views";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <SessionDetailView id={id}/>;
}
