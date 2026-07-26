"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Envelope } from "@/lib/api";
import { DataState, Layer } from "./data-state";

type Row = Record<string, unknown>;
type GraphPayload = { nodes: Row[]; edges: Row[] };
type GraphLayoutState = {
  positions: Record<string, { x: number; y: number }>;
  viewport: { x: number; y: number; zoom: number };
};

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
  const [compare, setCompare] = useState(false);
  const [compareStart, setCompareStart] = useState(isoInput(new Date(now.getTime() - 14 * 86_400_000)));
  const [compareEnd, setCompareEnd] = useState(isoInput(new Date(now.getTime() - 7 * 86_400_000)));
  const [selectedTimes, setSelectedTimes] = useState<string[]>([]);
  const query = useQuery({
    queryKey: ["timeline", start, end],
    queryFn: () => api<Envelope<Record<string, Row[]>>>(
      `/timeline?start_at_utc=${encodeURIComponent(new Date(start).toISOString())}&end_at_utc=${encodeURIComponent(new Date(end).toISOString())}`,
    ),
    enabled: Boolean(start && end),
  });
  const comparison = useQuery({
    queryKey: ["timeline-comparison", compareStart, compareEnd],
    queryFn: () => api<Envelope<Record<string, Row[]>>>(
      `/timeline?start_at_utc=${encodeURIComponent(new Date(compareStart).toISOString())}&end_at_utc=${encodeURIComponent(new Date(compareEnd).toISOString())}`,
    ),
    enabled: compare && Boolean(compareStart && compareEnd),
  });
  const layers = query.data?.data ?? {};
  const queryJson = { start_at_utc: new Date(start).toISOString(), end_at_utc: new Date(end).toISOString() };
  return (
    <section className="panel full">
      <div className="toolbar">
        <label>Start UTC<input type="datetime-local" value={start} onChange={event => setStart(event.target.value)}/></label>
        <label>End UTC<input type="datetime-local" value={end} onChange={event => setEnd(event.target.value)}/></label>
        <label><input type="checkbox" checked={compare} onChange={event => setCompare(event.target.checked)}/>Overlay comparison</label>
        {compare ? <><label>Comparison start<input type="datetime-local" value={compareStart} onChange={event => setCompareStart(event.target.value)}/></label><label>Comparison end<input type="datetime-local" value={compareEnd} onChange={event => setCompareEnd(event.target.value)}/></label></> : null}
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
                  return <button key={String(row.id || index)} style={{ left: `${offset}%`, width: "2%" }} title={JSON.stringify(row)} aria-label={`${name} ${String(row.id || index)}`} onClick={() => setSelectedTimes(current => [...current.slice(-1), value])}/>;
                })}
                {compare ? (comparison.data?.data[name] ?? []).slice(0, 100).map((row, index) => {
                  const value = String(row.start_at_utc || row.observed_at_utc || row.created_at || compareStart);
                  const offset = Math.max(0, Math.min(98, ((Date.parse(value) - Date.parse(compareStart)) / Math.max(1, Date.parse(compareEnd) - Date.parse(compareStart))) * 100));
                  return <button className="comparison" key={`compare-${String(row.id || index)}`} style={{ left: `${offset}%`, width: "2%" }} title={`Comparison: ${JSON.stringify(row)}`} aria-label={`comparison ${name} ${String(row.id || index)}`}/>;
                }) : null}
              </section>
            </div>
          ))}
        </div>
      </DataState>
      {selectedTimes.length === 2 ? <p className="notice" data-testid="timeline-delta">Selected delta: {Math.abs(Date.parse(selectedTimes[1]) - Date.parse(selectedTimes[0])) / 1000} seconds</p> : null}
      <footer className="timeline-foot">UTC primary display · local time {new Date(start).toLocaleString()}–{new Date(end).toLocaleString()}</footer>
    </section>
  );
}

export function GraphView() {
  const client = useQueryClient();
  const [confidence, setConfidence] = useState(0.5);
  const [predicate, setPredicate] = useState("");
  const [selected, setSelected] = useState<Row | null>(null);
  const [data, setData] = useState<GraphPayload>({ nodes: [], edges: [] });
  const [layout, setLayout] = useState<GraphLayoutState>({
    positions: {},
    viewport: { x: 0, y: 0, zoom: 1 },
  });
  const [layoutName, setLayoutName] = useState("Investigation layout");
  const layouts = useQuery({
    queryKey: ["graph-layouts"],
    queryFn: () => api<Envelope<Row[]>>("/graph-layouts?limit=100"),
  });
  const saveLayout = useMutation({
    mutationFn: () => api<Envelope<Row>>("/graph-layouts", {
      method: "POST",
      body: JSON.stringify({
        name: layoutName,
        query_json: { minimum_confidence: confidence, predicate: predicate || null },
        positions: layout.positions,
        viewport: layout.viewport,
      }),
    }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["graph-layouts"] }),
  });
  const exportJson = () => {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "signal-index-graph.json";
    link.click();
    URL.revokeObjectURL(link.href);
  };
  const graphSvg = () => {
    const width = 1400;
    const height = 900;
    const escape = (value: unknown) => String(value)
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
    const centers = Object.fromEntries(data.nodes.map((node, index) => {
      const position = layout.positions[String(node.id)] ?? {
        x: 70 + (index % 5) * 250,
        y: 70 + Math.floor(index / 5) * 150,
      };
      return [String(node.id), { x: position.x + 90, y: position.y + 28 }];
    }));
    const edges = data.edges.map(edge => {
      const source = centers[String(edge.source)];
      const target = centers[String(edge.target)];
      return source && target
        ? `<g><line x1="${source.x}" y1="${source.y}" x2="${target.x}" y2="${target.y}" stroke="#67e6a0" stroke-opacity=".55"/><text x="${(source.x + target.x) / 2}" y="${(source.y + target.y) / 2}" fill="#d5a94a" font-size="10">${escape(edge.predicate)}</text></g>`
        : "";
    }).join("");
    const nodes = data.nodes.map((node, index) => {
      const position = layout.positions[String(node.id)] ?? {
        x: 70 + (index % 5) * 250,
        y: 70 + Math.floor(index / 5) * 150,
      };
      return `<g transform="translate(${position.x},${position.y})"><rect width="180" height="56" rx="7" fill="#0d1916" stroke="#67e6a0"/><text x="12" y="23" fill="#dceae5" font-size="12">${escape(node.label)}</text><text x="12" y="41" fill="#718780" font-size="9">${escape(node.node_type)}</text></g>`;
    }).join("");
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}"><rect width="100%" height="100%" fill="#07100e"/>${edges}${nodes}</svg>`;
  };
  const download = (body: BlobPart, type: string, filename: string) => {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([body], { type }));
    link.download = filename;
    link.click();
    URL.revokeObjectURL(link.href);
  };
  const exportSvg = () => download(graphSvg(), "image/svg+xml", "signal-index-graph.svg");
  const exportPng = () => {
    const source = graphSvg();
    const image = new Image();
    const url = URL.createObjectURL(new Blob([source], { type: "image/svg+xml" }));
    image.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = 1400;
      canvas.height = 900;
      const context = canvas.getContext("2d");
      if (!context) {
        URL.revokeObjectURL(url);
        return;
      }
      context.drawImage(image, 0, 0);
      URL.revokeObjectURL(url);
      canvas.toBlob(blob => {
        if (blob) download(blob, "image/png", "signal-index-graph.png");
      }, "image/png");
    };
    image.onerror = () => URL.revokeObjectURL(url);
    image.src = url;
  };
  return (
    <div className="graph">
      <section className="panel toolbar">
        <label>Min confidence <input aria-label="Minimum confidence" type="range" min="0" max="1" step=".05" value={confidence} onChange={event => setConfidence(Number(event.target.value))}/>{confidence.toFixed(2)}</label>
        <label>Predicate<input value={predicate} onChange={event => setPredicate(event.target.value.toUpperCase())} placeholder="e.g. SIMILAR_TO"/></label>
        <button onClick={exportJson}>Export graph JSON</button>
        <button onClick={exportSvg}>Export SVG</button>
        <button onClick={exportPng}>Export PNG</button>
        <label>Layout name<input value={layoutName} onChange={event => setLayoutName(event.target.value)}/></label>
        <button disabled={saveLayout.isPending || !Object.keys(layout.positions).length} onClick={() => saveLayout.mutate()}>Save layout</button>
        <select aria-label="Load graph layout" defaultValue="" onChange={event => {
          const row = layouts.data?.data.find(item => String(item.id) === event.target.value);
          if (row) {
            setLayout({
              positions: row.positions as GraphLayoutState["positions"],
              viewport: row.viewport as GraphLayoutState["viewport"],
            });
            setLayoutName(String(row.name));
          }
        }}><option value="">Load layout…</option>{(layouts.data?.data ?? []).map(row => <option value={String(row.id)} key={String(row.id)}>{String(row.name)}</option>)}</select>
      </section>
      <section className="panel graph-canvas" data-testid="relation-graph">
        <GraphCanvas minimumConfidence={confidence} predicate={predicate} onData={setData} onEdge={setSelected} initialPositions={layout.positions} onLayoutChange={setLayout}/>
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
  const [supporting, setSupporting] = useState<string | null>(null);
  const [contradicting, setContradicting] = useState<string | null>(null);
  const [unresolved, setUnresolved] = useState<string | null>(null);
  const [sessions, setSessions] = useState<string | null>(null);
  const [events, setEvents] = useState<string | null>(null);
  const [notes, setNotes] = useState<string | null>(null);
  const ids = (value: string) => value.split(",").map(item => item.trim()).filter(Boolean);
  const mutation = useMutation({
    mutationFn: () => api<Envelope<Row>>(create ? "/hypotheses" : `/hypotheses/${encodeURIComponent(id!)}`, {
      method: create ? "POST" : "PATCH",
      body: JSON.stringify(create
        ? { title: title ?? "", statement: statement ?? "", created_by: "USER" }
        : {
            title: title ?? existing?.title,
            statement: statement ?? existing?.statement,
            status: status ?? existing?.status,
            supporting_evidence_ids: ids(supporting ?? String((existing?.supporting_evidence_ids as string[] | undefined)?.join(",") ?? "")),
            contradicting_evidence_ids: ids(contradicting ?? String((existing?.contradicting_evidence_ids as string[] | undefined)?.join(",") ?? "")),
            unresolved_evidence_ids: ids(unresolved ?? String((existing?.unresolved_evidence_ids as string[] | undefined)?.join(",") ?? "")),
            related_session_ids: ids(sessions ?? String((existing?.related_session_ids as string[] | undefined)?.join(",") ?? "")),
            related_event_ids: ids(events ?? String((existing?.related_event_ids as string[] | undefined)?.join(",") ?? "")),
            evaluation_notes: notes ?? existing?.evaluation_notes ?? null,
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
        {!create ? <div className="evidence-editor"><label>Supporting evidence IDs<input value={supporting ?? String((existing?.supporting_evidence_ids as string[] | undefined)?.join(", ") ?? "")} onChange={event => setSupporting(event.target.value)}/></label><label>Contradicting evidence IDs<input value={contradicting ?? String((existing?.contradicting_evidence_ids as string[] | undefined)?.join(", ") ?? "")} onChange={event => setContradicting(event.target.value)}/></label><label>Unresolved evidence IDs<input value={unresolved ?? String((existing?.unresolved_evidence_ids as string[] | undefined)?.join(", ") ?? "")} onChange={event => setUnresolved(event.target.value)}/></label><label>Related session IDs<input value={sessions ?? String((existing?.related_session_ids as string[] | undefined)?.join(", ") ?? "")} onChange={event => setSessions(event.target.value)}/></label><label>Related event IDs<input value={events ?? String((existing?.related_event_ids as string[] | undefined)?.join(", ") ?? "")} onChange={event => setEvents(event.target.value)}/></label><label>Evaluation notes<textarea value={notes ?? String(existing?.evaluation_notes ?? "")} onChange={event => setNotes(event.target.value)}/></label></div> : null}
        <button className="primary" disabled={mutation.isPending || (create && (!title?.trim() || !statement?.trim()))} onClick={() => mutation.mutate()}>{create ? "Create hypothesis" : "Save evaluation revision"}</button>
        {mutation.error ? <p role="alert">{mutation.error.message}</p> : null}
      </section>
      <aside className="panel"><h2>Evidence links</h2><pre>{JSON.stringify({ supporting: existing?.supporting_evidence_ids ?? [], contradicting: existing?.contradicting_evidence_ids ?? [], unresolved: existing?.unresolved_evidence_ids ?? [], sessions: existing?.related_session_ids ?? [], events: existing?.related_event_ids ?? [] }, null, 2)}</pre>{!create ? <><button disabled={!Array.isArray(existing?.related_session_ids) || existing.related_session_ids.length === 0} onClick={() => bundle.mutate()}>Create bounded context bundle</button><a className="primary" href={`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1"}/export/hypotheses/${encodeURIComponent(id!)}/report`}>Export report</a><h3>Evaluation history</h3>{(existing?.history as Row[] | undefined)?.map(row => <p key={String(row.id)}>{String(row.previous_status ?? "NEW")} → {String(row.new_status)}<br/><small>{String(row.created_at)}</small></p>)}</> : null}{bundle.data ? <pre>{JSON.stringify(bundle.data.data, null, 2)}</pre> : null}</aside>
    </div>
  );
}
