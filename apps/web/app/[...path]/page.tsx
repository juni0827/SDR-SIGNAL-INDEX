import { SignalIndexApp } from "../signal-index-app";

export default async function RoutedPage({ params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return <SignalIndexApp initialPath={`/${path.join("/")}`} />;
}

