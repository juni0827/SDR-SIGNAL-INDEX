import { FrequenciesView } from "@/components/catalog-views";

export default async function Page({ params }: { params: Promise<{ frequency: string }> }) {
  const { frequency } = await params;
  return <FrequenciesView frequency={Number(frequency)}/>;
}
