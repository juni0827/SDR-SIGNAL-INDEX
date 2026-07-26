export function DataState({
  loading,
  error,
  empty,
  children,
}: {
  loading: boolean;
  error: Error | null;
  empty: boolean;
  children: React.ReactNode;
}) {
  if (loading) return <section className="panel full notice" role="status">Loading indexed data…</section>;
  if (error) return <section className="panel full notice" role="alert">API request failed: {error.message}</section>;
  if (empty) return <section className="panel full notice" role="status">No indexed records match this view.</section>;
  return children;
}

export function Layer({ kind }: { kind: "observed" | "machine" | "corrected" | "interpretation" | "llm" | "confirmed" }) {
  const labels = {
    observed: "Observed",
    machine: "Machine-generated",
    corrected: "User-corrected",
    interpretation: "User interpretation",
    llm: "Local LLM hypothesis",
    confirmed: "Confirmed",
  };
  return <span className={`layer ${kind}`}>{labels[kind]}</span>;
}
