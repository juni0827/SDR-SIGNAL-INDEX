"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { api, type Envelope } from "@/lib/api";
import { DataState, Layer } from "./data-state";

type Row = Record<string, unknown>;

function useApi<T>(key: readonly unknown[], path: string, init?: RequestInit) {
  return useQuery({
    queryKey: key,
    queryFn: () => api<Envelope<T>>(path, init),
  });
}

function formatFrequency(value: unknown) {
  const frequency = Number(value);
  if (frequency >= 1_000_000) return `${(frequency / 1_000_000).toFixed(3)} MHz`;
  if (frequency >= 1_000) return `${(frequency / 1_000).toFixed(3)} kHz`;
  return `${frequency} Hz`;
}

export function SessionTable({ rows }: { rows: Row[] }) {
  return (
    <div className="table-scroll">
      <table data-testid="session-table">
        <thead><tr><th>Session</th><th>Frequency</th><th>Started UTC</th><th>Entities</th><th>Confidence</th><th>Status</th></tr></thead>
        <tbody>{rows.map(row => <tr key={String(row.id)}>
          <td><Link href={`/sessions/${String(row.id)}`}>{String(row.title || row.id)}</Link></td>
          <td>{formatFrequency(row.primary_frequency_hz)}</td>
          <td>{String(row.start_at_utc || "").replace("T", " ").slice(0, 19)}</td>
          <td><b>{Array.isArray(row.callsigns) ? row.callsigns.join(", ") || "—" : "—"}</b><small>{Array.isArray(row.number_groups) ? row.number_groups.join(" · ") || "—" : "—"}</small></td>
          <td>{Math.round(Number(row.confidence || 0) * 100)}%</td>
          <td>{String(row.status)}</td>
        </tr>)}</tbody>
      </table>
    </div>
  );
}

export function DashboardView() {
  const analytics = useApi<Row>(["analytics-summary"], "/analytics/summary");
  const sessions = useApi<Row[]>(["dashboard-sessions"], "/search/sessions", { method: "POST", body: JSON.stringify({ limit: 8 }) });
  const receivers = useApi<Row[]>(["dashboard-receivers"], "/receivers?limit=100");
  const hypotheses = useApi<Row[]>(["dashboard-hypotheses"], "/hypotheses?limit=5");
  const error = analytics.error || sessions.error || receivers.error || hypotheses.error;
  const summary = analytics.data?.data ?? {};
  const sessionRows = sessions.data?.data ?? [];
  const receiverRows = receivers.data?.data ?? [];
  const hypothesisRows = hypotheses.data?.data ?? [];
  return (
    <DataState loading={analytics.isLoading || sessions.isLoading} error={error} empty={false}>
      <div className="dashboard" data-testid="dashboard-live">
        <section className="stats">
          {[
            ["Sessions", summary.session_count ?? sessionRows.length],
            ["Active duration", `${Math.round(Number(summary.active_duration_sec ?? 0))} s`],
            ["Receiver coverage", summary.receiver_coverage ?? receiverRows.length],
            ["Unreviewed", sessionRows.filter(row => row.status === "UNREVIEWED").length],
          ].map(([label, value]) => <article key={String(label)}><span>{String(label)}</span><b>{String(value)}</b><small>Live indexed value</small></article>)}
        </section>
        <section className="panel recent"><header><div><span className="kicker">RECENT SESSIONS</span><h2>Indexed transmissions</h2></div><Link href="/sessions">View all</Link></header>{sessionRows.length ? <SessionTable rows={sessionRows}/> : <p className="notice">No sessions have been processed.</p>}</section>
        <aside className="panel watch"><span className="kicker">RECEIVERS</span><h2>Status</h2>{receiverRows.length ? receiverRows.map(row => <Link href={`/receivers/${String(row.id)}`} key={String(row.id)}><div><b>{String(row.name)}</b><small>{String(row.receiver_type)} · {String(row.status)}</small></div></Link>) : <p>No receivers registered.</p>}</aside>
        <aside className="panel entities"><span className="kicker">REPEATED ENTITIES</span><h2>Current index</h2><p><Layer kind="machine"/><b>{String((summary.top_callsigns as Row[] | undefined)?.[0]?.value ?? "None")}</b></p><p><Layer kind="machine"/><b>{String((summary.top_number_groups as Row[] | undefined)?.[0]?.value ?? "None")}</b></p></aside>
        <aside className="panel failures"><span className="kicker">HYPOTHESES</span><h2>Recent</h2>{hypothesisRows.length ? hypothesisRows.map(row => <p key={String(row.id)}><Link href={`/hypotheses/${String(row.id)}`}>{String(row.title)}</Link></p>) : <p>No hypotheses.</p>}</aside>
      </div>
    </DataState>
  );
}

export function SessionsView() {
  const [text, setText] = useState("");
  const [reviewed, setReviewed] = useState<"all" | "reviewed" | "unreviewed">("all");
  const payload = useMemo(() => ({ text: text || null, status: reviewed === "all" ? null : reviewed === "reviewed" ? "REVIEWED" : "UNREVIEWED", limit: 100 }), [text, reviewed]);
  const query = useApi<Row[]>(["sessions", payload], "/search/sessions", { method: "POST", body: JSON.stringify(payload) });
  const copy = async () => navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
  return (
    <section className="panel full">
      <div className="toolbar"><label>Search<input data-testid="session-search" aria-label="Search sessions" value={text} onChange={event => setText(event.target.value)}/></label><select aria-label="Review status" value={reviewed} onChange={event => setReviewed(event.target.value as typeof reviewed)}><option value="all">All</option><option value="reviewed">Reviewed</option><option value="unreviewed">Unreviewed</option></select><button onClick={() => void copy()}>Copy query JSON</button></div>
      <div className="query"><code>{JSON.stringify(payload)}</code></div>
      <DataState loading={query.isLoading} error={query.error} empty={(query.data?.data.length ?? 0) === 0}><SessionTable rows={query.data?.data ?? []}/></DataState>
    </section>
  );
}

export function SessionDetailView({ id }: { id: string }) {
  const query = useApi<Row>(["session", id], `/sessions/${encodeURIComponent(id)}`);
  const row = query.data?.data;
  return (
    <DataState loading={query.isLoading} error={query.error} empty={!row}>
      {row ? <div className="notebook">
        <section className="panel"><span className="kicker">SESSION · {id}</span><h2>{String(row.title || id)}</h2><Layer kind="machine"/><dl><dt>Frequency</dt><dd>{formatFrequency(row.primary_frequency_hz)}</dd><dt>UTC</dt><dd>{String(row.start_at_utc)} – {String(row.end_at_utc)}</dd><dt>Status</dt><dd>{String(row.status)}</dd><dt>Confidence</dt><dd>{Math.round(Number(row.confidence) * 100)}%</dd></dl><h3>Segments</h3>{(row.segment_ids as string[] | undefined)?.map(segmentId => <Link className="queue" href={`/segments/${segmentId}`} key={segmentId}>{segmentId}</Link>)}</section>
        <aside className="panel"><h3>Entities</h3>{(row.entities as Row[] | undefined)?.map(entity => <p key={String(entity.id)}><b>{String(entity.entity_type)}</b><br/>{String(entity.raw_value)} → {String(entity.normalized_value)}</p>)}<h3>Relations</h3>{(row.relations as Row[] | undefined)?.map(relation => <p key={String(relation.id)}>{String(relation.predicate)} · {Math.round(Number(relation.confidence) * 100)}%</p>)}</aside>
      </div> : null}
    </DataState>
  );
}

export function RecordingsView() {
  const query = useApi<Row[]>(["recordings"], "/recordings?limit=100");
  const recordings = query.data?.data ?? [];
  return (
    <DataState loading={query.isLoading} error={query.error} empty={recordings.length === 0}>
      <section className="panel full cards">{recordings.map(row => <Link href={`/recordings/${String(row.id)}`} key={String(row.id)}><Layer kind="observed"/><h2>{String(row.original_filename || row.id)}</h2><p>{formatFrequency(row.frequency_hz)} · {String(row.processing_status)} · {String(row.started_at_utc)}</p></Link>)}</section>
    </DataState>
  );
}

export function RecordingDetailView({ id }: { id: string }) {
  const query = useApi<Row>(["recording", id], `/recordings/${encodeURIComponent(id)}`);
  const row = query.data?.data;
  return (
    <DataState loading={query.isLoading} error={query.error} empty={!row}>
      {row ? <section className="panel full"><header><div><span className="kicker">IMMUTABLE ORIGINAL</span><h2>{String(row.original_filename || id)}</h2></div><Layer kind="observed"/></header><dl className="inspector"><dt>Frequency</dt><dd>{formatFrequency(row.frequency_hz)}</dd><dt>Mode</dt><dd>{String(row.mode)}</dd><dt>UTC</dt><dd>{String(row.started_at_utc)}</dd><dt>SHA-256</dt><dd>{String(row.sha256)}</dd><dt>Pipeline</dt><dd>{String(row.processing_status)} · {String(row.processing_version || "not processed")}</dd></dl><h3>Segments</h3><div className="cards">{(row.segments as Row[] | undefined)?.map(segment => <Link href={`/segments/${String(segment.id)}`} key={String(segment.id)}><h2>{String(segment.segment_type)}</h2><p>{Number(segment.start_sec).toFixed(2)}–{Number(segment.end_sec).toFixed(2)} s · SNR {String(segment.snr_db ?? "—")}</p></Link>)}</div></section> : null}
    </DataState>
  );
}

export function FrequenciesView({ frequency }: { frequency?: number }) {
  const activityWindow = useMemo(() => {
    const end = new Date();
    return {
      start: new Date(end.getTime() - 30 * 86_400_000).toISOString(),
      end: end.toISOString(),
    };
  }, []);
  const catalog = useApi<Row[]>(["frequencies"], "/frequencies?limit=500");
  const activity = useApi<Row>(
    ["frequency-activity", frequency],
    frequency
      ? `/frequencies/${frequency}/activity?tolerance_hz=0`
      : `/analytics/activity?start_at_utc=${encodeURIComponent(activityWindow.start)}&end_at_utc=${encodeURIComponent(activityWindow.end)}`,
  );
  const rows = catalog.data?.data ?? [];
  return (
    <DataState loading={catalog.isLoading || activity.isLoading} error={catalog.error || activity.error} empty={!frequency && rows.length === 0}>
      <div className="split"><section className="panel full"><header><h2>{frequency ? formatFrequency(frequency) : "Known frequency index"}</h2></header><div className="cards">{rows.map(row => <Link href={`/frequencies/${String(row.frequency_hz)}`} key={String(row.id)}><Layer kind="observed"/><h2>{formatFrequency(row.frequency_hz)}</h2><p>{String(row.label)} · {String(row.category)} · {String(row.mode || "mode unknown")}</p></Link>)}</div></section><aside className="panel inspector"><span className="kicker">ACTIVITY</span><h2>{frequency ? formatFrequency(frequency) : "All bands"}</h2><pre>{JSON.stringify(activity.data?.data ?? {}, null, 2)}</pre></aside></div>
    </DataState>
  );
}

function ReceiverMap({ rows }: { rows: Row[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let map: import("maplibre-gl").Map | undefined;
    let disposed = false;
    void import("maplibre-gl").then(({ default: maplibre }) => {
      if (disposed || !ref.current) return;
      map = new maplibre.Map({ container: ref.current, center: [20, 20], zoom: 1.1, style: { version: 8, sources: {}, layers: [{ id: "background", type: "background", paint: { "background-color": "#081311" } }] } });
      for (const row of rows) {
        if (row.latitude == null || row.longitude == null) continue;
        const element = document.createElement("a");
        element.className = "receiver-dot";
        element.setAttribute("aria-label", `${String(row.name)} receiver location`);
        element.setAttribute("href", `/receivers/${String(row.id)}`);
        new maplibre.Marker({ element }).setLngLat([Number(row.longitude), Number(row.latitude)]).addTo(map);
      }
    });
    return () => { disposed = true; map?.remove(); };
  }, [rows]);
  return <div ref={ref} className="map" data-testid="receiver-map" aria-label="Receiver locations map"/>;
}

export function ReceiversView({ id }: { id?: string }) {
  const list = useApi<Row[]>(["receivers"], "/receivers?limit=500");
  const detail = useApi<Row>(["receiver", id], id ? `/receivers/${encodeURIComponent(id)}` : "/capabilities");
  const rows = list.data?.data ?? [];
  const selected = id ? detail.data?.data : undefined;
  return (
    <DataState loading={list.isLoading || (Boolean(id) && detail.isLoading)} error={list.error || (id ? detail.error : null)} empty={rows.length === 0}>
      <div className="split"><section className="panel"><p className="map-note">Receiver positions only; transmitter location is not inferred.</p><ReceiverMap rows={rows}/></section><aside className="panel receiver-list">{selected ? <><Layer kind="observed"/><h2>{String(selected.name)}</h2><p>{String(selected.receiver_type)} · {String(selected.status)}</p><p>{formatFrequency(selected.min_frequency_hz)}–{formatFrequency(selected.max_frequency_hz)}</p><a className="primary" href={String(selected.base_url)} target="_blank" rel="noreferrer">Open receiver</a></> : rows.map(row => <Link href={`/receivers/${String(row.id)}`} key={String(row.id)}><div><b>{String(row.name)}</b><span>{String(row.receiver_type)} · {String(row.status)}</span></div></Link>)}</aside></div>
    </DataState>
  );
}
