import { EventsView } from "@/components/management-views";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <EventsView id={id} />;
}
