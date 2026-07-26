"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Envelope } from "@/lib/api";
import { DataState, Layer } from "./data-state";

type Row = Record<string, unknown>;
type GraphPayload = { nodes: Row[]; edges: Row[] };

const GraphCanvas = dynamic(
  () => import("@/app/graph-canvas").then(module => module.GraphCanvas),
  { ssr: false },
);

function isoInput(date: Date) {
  return date.toISOString().slice(0, 16);
}

export function TimelineView() {
  const now = useMemo(() => new Date(), []);
  const [start, setStart] = useState(isoInput(new Date(now.getTime() - 7 * 86_400_000)));
  const [end, setEnd] = useState(isoInput(now));
  const query = useQuery({
    queryKey: ["timeline", start, end],
    queryFn: () => api<Envelope<Record<string, Row[]>>>(
      `/timeline?start_at_utc=${encodeURIComponent(new Date(start).toISOString())}&end_at_utc=${encodeURIComponent(new Date(end).toISOString())}`,
    ),
    enabled: Boolean(start && end),
  });
  const layers = query.data?.data ?? {};
  const queryJson = { start_at_utc: new Date(start).toISOString(), end_at_utc: new Date(end).toISOString() };
  return (
    <section className="panel full">
      <div className="toolbar">
        <label>Start UTC<input type="datetime-local" value={start} onChange={event => setStart(event.target.value)}/></label>
        <label>End UTC<input type="datetime-local" value={end} onChange={event => setEnd(event.target.value)}/></label>
        <button onClick={() => void navigator.clipboard.writeText(JSON.stringify(queryJson, null, 2))}>Copy selection query</button>
      </div>
      <DataState loading={query.isLoading} error={query.error} empty={Object.values(layers).every(rows => rows.length === 0)}>
        <div className="timeline" data-testid="timeline">
          {Object.entries(layers).map(([name, rows]) => (
            <div key={name}>
              <span>{name.replaceAll("_", " ")}</span>
              <section>
                {rows.slice(0, 100).map((row, index) => {
                  const value = String(row.start_at_utc || row.observed_at_utc || row.created_at || start);
                  const offset = Math.max(0, Math.min(98, ((Date.parse(value) - Date.parse(start)) / Math.max(1, Date.parse(end) - Date.parse(start))) * 100));
                  return <button key={String(row.id || index)} style={{ left: `${offset}%`, width: "2%" }} title={JSON.stringify(row)} aria-label={`${name} ${String(row.id || index)}`}/>;
                })}
              </section>
            </div>
          ))}
        </div>
      </DataState>
      <footer className="timeline-foot">UTC primary display · local time {new Date(start).toLocaleString()}–{new Date(end).toLocaleString()}</footer>
    </section>
  );
}

export function GraphView() {
  const [confidence, setConfidence] = useState(0.5);
  const [predicate, setPredicate] = useState("");
  const [selected, setSelected] = useState<Row | null>(null);
  const [data, setData] = useState<GraphPayload>({ nodes: [], edges: [] });
  const exportJson = () => {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "signal-index-graph.json";
    link.click();
    URL.revokeObjectURL(link.href);
  };
  return (
    <div className="graph">
      <section className="panel toolbar">
        <label>Min confidence <input aria-label="Minimum confidence" type="range" min="0" max="1" step=".05" value={confidence} onChange={event => setConfidence(Number(event.target.value))}/>{confidence.toFixed(2)}</label>
        <label>Predicate<input value={predicate} onChange={event => setPredicate(event.target.value.toUpperCase())} placeholder="e.g. SIMILAR_TO"/></label>
        <button onClick={exportJson}>Export graph JSON</button>
      </section>
      <section className="panel graph-canvas" data-testid="relation-graph">
        <GraphCanvas minimumConfidence={confidence} predicate={predicate} onData={setData} onEdge={setSelected}/>
      </section>
      <aside className="panel inspector">
        <span className="kicker">EDGE EVIDENCE</span>
        {selected ? <><h2>{String(selected.predicate)}</h2><Layer kind={selected.relation_status === "LLM_HYPOTHESIS" ? "llm" : "machine"}/><dl><dt>Confidence</dt><dd>{String(selected.confidence)}</dd><dt>Delta seconds</dt><dd>{String(selected.delta_seconds ?? "—")}</dd><dt>Causal claim</dt><dd>{selected.causal_claim ? "Yes" : "No"}</dd><dt>Evidence</dt><dd>{String(selected.evidence_count ?? 0)}</dd></dl></> : <p>Select an edge to inspect its evidence.</p>}
        <p>Temporal order is not treated as causation.</p>
      </aside>
    </div>
  );
}

export function HypothesesView() {
  const query = useQuery({ queryKey: ["hypotheses"], queryFn: () => api<Envelope<Row[]>>("/hypotheses?limit=200") });
  return (
    <section className="panel full">
      <div className="toolbar"><Link className="primary" href="/hypotheses/new">New hypothesis</Link></div>
      <DataState loading={query.isLoading} error={query.error} empty={(query.data?.data.length ?? 0) === 0}>
        <div className="cards">{(query.data?.data ?? []).map(row => <Link href={`/hypotheses/${String(row.id)}`} key={String(row.id)}><Layer kind={row.created_by_type === "LOCAL_LLM" ? "llm" : "interpretation"}/><h2>{String(row.title)}</h2><p>{String(row.status)} · confidence {String(row.confidence ?? "unscored")}</p></Link>)}</div>
      </DataState>
    </section>
  );
}

export function HypothesisEditor({ id, create = false }: { id?: string; create?: boolean }) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["hypothesis", id],
    queryFn: () => api<Envelope<Row>>(`/hypotheses/${encodeURIComponent(id!)}`),
    enabled: Boolean(id),
  });
  const existing = query.data?.data;
  const [title, setTitle] = useState<string | null>(null);
  const [statement, setStatement] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () => api<Envelope<Row>>(create ? "/hypotheses" : `/hypotheses/${encodeURIComponent(id!)}`, {
      method: create ? "POST" : "PATCH",
      body: JSON.stringify(create
        ? { title: title ?? "", statement: statement ?? "", created_by: "USER" }
        : {
            title: title ?? existing?.title,
            statement: statement ?? existing?.statement,
            status: status ?? existing?.status,
          }),
    }),
    onSuccess: result => {
      client.setQueryData(["hypothesis", id], result);
      if (create) location.assign(`/hypotheses/${String(result.data.id)}`);
    },
  });
  const bundle = useMutation({
    mutationFn: () => api<Envelope<Row>>("/export/context-bundle", {
      method: "POST",
      body: JSON.stringify({ task: "evaluate_hypothesis", subject_session_id: (existing?.related_session_ids as string[] | undefined)?.[0], include: ["metadata", "preferred_transcripts", "entities", "relations", "provenance"], exclude_raw_audio: true, token_budget: 24000 }),
    }),
  });
  if (!create && (query.isLoading || query.error || !existing)) return <DataState loading={query.isLoading} error={query.error} empty={!existing}>{null}</DataState>;
  return (
    <div className="notebook">
      <section className="panel">
        <Layer kind={existing?.created_by_type === "LOCAL_LLM" ? "llm" : "interpretation"}/>
        <label>Title<input value={title ?? String(existing?.title ?? "")} onChange={event => setTitle(event.target.value)}/></label>
        <label>Statement<textarea value={statement ?? String(existing?.statement ?? "")} onChange={event => setStatement(event.target.value)}/></label>
        {!create ? <label>Status<select value={status ?? String(existing?.status ?? "ACTIVE")} onChange={event => setStatus(event.target.value)}>{["DRAFT","ACTIVE","SUPPORTED","CONTRADICTED","INCONCLUSIVE","ARCHIVED"].map(value => <option key={value}>{value}</option>)}</select></label> : null}
        <button className="primary" disabled={mutation.isPending || (create && (!title?.trim() || !statement?.trim()))} onClick={() => mutation.mutate()}>{create ? "Create hypothesis" : "Save evaluation revision"}</button>
        {mutation.error ? <p role="alert">{mutation.error.message}</p> : null}
      </section>
      <aside className="panel"><h2>Evidence links</h2><pre>{JSON.stringify({ supporting: existing?.supporting_evidence_ids ?? [], contradicting: existing?.contradicting_evidence_ids ?? [], sessions: existing?.related_session_ids ?? [] }, null, 2)}</pre>{!create ? <button disabled={!Array.isArray(existing?.related_session_ids) || existing.related_session_ids.length === 0} onClick={() => bundle.mutate()}>Create bounded context bundle</button> : null}{bundle.data ? <pre>{JSON.stringify(bundle.data.data, null, 2)}</pre> : null}</aside>
    </div>
  );
}
