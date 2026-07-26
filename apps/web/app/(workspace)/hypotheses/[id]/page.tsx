import { HypothesisEditor } from "@/components/analysis-views";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <HypothesisEditor id={id}/>;
}
