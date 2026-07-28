"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
  const dashboardWindow = useMemo(() => {
    const end = new Date();
    return {
      start: new Date(end.getTime() - 7 * 86_400_000).toISOString(),
      end: end.toISOString(),
    };
  }, []);
  const analytics = useApi<Row>(["analytics-summary"], "/analytics/summary");
  const activity = useApi<Row>(
    ["dashboard-activity", dashboardWindow],
    `/analytics/activity?start_at_utc=${encodeURIComponent(dashboardWindow.start)}&end_at_utc=${encodeURIComponent(dashboardWindow.end)}`,
  );
  const sessions = useApi<Row[]>(["dashboard-sessions"], "/search/sessions", { method: "POST", body: JSON.stringify({ limit: 10 }) });
  const unreviewedSegments = useApi<Row[]>(["dashboard-unreviewed"], "/search/segments", { method: "POST", body: JSON.stringify({ reviewed: false, limit: 8 }) });
  const receivers = useApi<Row[]>(["dashboard-receivers"], "/receivers?limit=100");
  const hypotheses = useApi<Row[]>(["dashboard-hypotheses"], "/hypotheses?limit=5");
  const events = useApi<Row[]>(["dashboard-events"], "/events?limit=5");
  const frequencies = useApi<Row[]>(["dashboard-frequencies"], "/frequencies?limit=500");
  const savedQueries = useApi<Row[]>(["dashboard-saved-queries"], "/saved-queries?limit=10");
  const health = useApi<Row>(["dashboard-health"], "/health");
  const automation = useApi<Row>(["automation-status"], "/automation/status");
  const error = analytics.error || activity.error || sessions.error || unreviewedSegments.error || receivers.error || hypotheses.error || events.error || frequencies.error || savedQueries.error || health.error || automation.error;
  const summary = analytics.data?.data ?? {};
  const activityData = activity.data?.data ?? {};
  const sessionRows = sessions.data?.data ?? [];
  const reviewRows = unreviewedSegments.data?.data ?? [];
  const receiverRows = receivers.data?.data ?? [];
  const hypothesisRows = hypotheses.data?.data ?? [];
  const eventRows = events.data?.data ?? [];
  const watchlist = (frequencies.data?.data ?? []).filter(row => row.watchlisted);
  const failedJobs = (summary.failed_jobs as Row[] | undefined) ?? [];
  const storage = (summary.storage as Row | undefined) ?? {};
  const components = (health.data?.data.checks as Row | undefined) ?? {};
  const automationData = automation.data?.data ?? {};
  const automationCaptures = (automationData.captures as Row | undefined) ?? {};
  const automationSources = (automationData.sources as Row | undefined) ?? {};
  const scheduler = (automationData.scheduler as Row | undefined) ?? {};
  const dailyActivity = Object.entries((activityData.daily_activity as Record<string, number> | undefined) ?? {}).slice(-7);
  const maxDailyActivity = Math.max(1, ...dailyActivity.map(([, count]) => Number(count)));
  const topCallsigns = (summary.top_callsigns as Row[] | undefined) ?? [];
  const topNumberGroups = (summary.top_number_groups as Row[] | undefined) ?? [];
  const onlineReceivers = receiverRows.filter(row => row.status === "ONLINE").length;
  const activeHypotheses = hypothesisRows.filter(row => ["ACTIVE", "DRAFT", "INCONCLUSIVE"].includes(String(row.status))).length;
  const operatorAttention = failedJobs.length + reviewRows.length + Number(automationCaptures.failed ?? 0);
  return (
    <DataState loading={analytics.isLoading || activity.isLoading || sessions.isLoading} error={error} empty={false}>
      <div className="command-deck" data-testid="dashboard-live">
        <section className="deck-header">
          <div><span className="kicker">SIGNAL INDEX / COMMAND DECK</span><h2>Observation operations</h2><p>Autonomous collection, review backlog, and analytic leads in one operational surface.</p></div>
          <div className="deck-actions"><Link className="primary" href="/inbox">Add observation</Link><Link href="/capture">Configure capture</Link><Link href="/sessions">Search index</Link></div>
        </section>

        <section className="deck-metrics" aria-label="Operational summary">
          {[
            ["Attention", operatorAttention, operatorAttention > 0 ? "attention" : "clear", "review + failures"],
            ["Sessions", summary.session_count ?? sessionRows.length, "neutral", "indexed total"],
            ["Review queue", reviewRows.length, reviewRows.length ? "attention" : "clear", "unreviewed segments"],
            ["Receivers", `${onlineReceivers}/${receiverRows.length}`, onlineReceivers ? "clear" : "muted", "online / known"],
            ["Automation", scheduler.capture_globally_enabled ? `${String(automationCaptures.enabled ?? 0)} armed` : "off", scheduler.capture_globally_enabled ? "clear" : "attention", `${String(automationSources.enabled ?? 0)} source feeds`],
            ["Storage", storage.size_bytes != null ? `${(Number(storage.size_bytes) / 1_048_576).toFixed(1)} MiB` : String(storage.status ?? "unknown"), "neutral", "private object store"],
          ].map(([label, value, tone, detail]) => <article className={`metric ${String(tone)}`} key={String(label)}><span>{String(label)}</span><b>{String(value)}</b><small>{String(detail)}</small></article>)}
        </section>

        <section className="panel deck-priority">
          <header><div><span className="kicker">OPERATOR QUEUE</span><h2>What needs a decision</h2></div><Link href="/segments">Open review</Link></header>
          <div className="priority-grid">
            <article><span className="priority-label">UNREVIEWED SEGMENTS</span>{reviewRows.length ? reviewRows.slice(0, 4).map(row => <Link href={`/segments/${String(row.id)}`} className="priority-row" key={String(row.id)}><b>{String(row.segment_type)} · {Number(row.duration_sec ?? 0).toFixed(1)} s</b><small>Segment {String(row.id).slice(0, 8)} · {String(row.created_at ?? "UTC pending")}</small></Link>) : <p className="empty-state">No segment review is waiting.</p>}</article>
            <article><span className="priority-label">FAILED / BLOCKED</span>{failedJobs.length ? failedJobs.slice(0, 3).map(row => <Link href={`/recordings/${String(row.recording_id)}`} className="priority-row critical" key={String(row.id)}><b>{String(row.stage)}</b><small>{String(row.error_code ?? row.error_stderr ?? "Processing failed")}</small></Link>) : <p className="empty-state">No processing failures.</p>}{automation.data?.warnings?.map(warning => <Link href="/capture" className="priority-row warning" key={warning}><b>Automation warning</b><small>{warning}</small></Link>)}</article>
            <article><span className="priority-label">ACTIVE ANALYSIS</span>{hypothesisRows.length ? hypothesisRows.slice(0, 3).map(row => <Link href={`/hypotheses/${String(row.id)}`} className="priority-row" key={String(row.id)}><b>{String(row.title)}</b><small>{String(row.status)} · {Math.round(Number(row.confidence ?? 0) * 100)}%</small></Link>) : <p className="empty-state">No active hypothesis.</p>}<Link className="queue-cta" href="/hypotheses/new">Create hypothesis →</Link></article>
          </div>
        </section>

        <section className="panel deck-activity">
          <header><div><span className="kicker">ACTIVITY RADAR</span><h2>Seven-day session pulse</h2></div><Link href="/timeline">Open timeline</Link></header>
          <div className="activity-radar" aria-label="Seven-day session activity">{dailyActivity.length ? dailyActivity.map(([day, count]) => <div key={day} title={`${day}: ${count} sessions`}><i style={{ height: `${Math.max(8, Number(count) / maxDailyActivity * 100)}%` }}/><span>{day.slice(5)}</span><b>{count}</b></div>) : <p className="empty-state">No session activity in this window.</p>}</div>
          <footer><span>{String(activityData.activity_count ?? 0)} observations · {Math.round(Number(activityData.active_duration_sec ?? 0))} active seconds</span><span>UTC window ending {dashboardWindow.end.slice(0, 16).replace("T", " ")}</span></footer>
        </section>

        <section className="panel deck-sessions"><header><div><span className="kicker">LIVE INDEX</span><h2>Latest indexed sessions</h2></div><Link href="/sessions">Session explorer</Link></header>{sessionRows.length ? <SessionTable rows={sessionRows}/> : <p className="empty-state">Awaiting first indexed session.</p>}</section>

        <section className="panel deck-watchlist"><header><div><span className="kicker">WATCHLIST</span><h2>Frequency focus</h2></div><Link href="/frequencies">Spectrum</Link></header>{watchlist.length ? <div className="watchlist-grid">{watchlist.slice(0, 8).map(row => <Link href={`/frequencies/${String(row.frequency_hz)}`} key={String(row.id)}><b>{formatFrequency(row.frequency_hz)}</b><small>{String(row.label)}</small><span>{String(row.mode ?? "—")} · {String(row.category)}</span></Link>)}</div> : <p className="empty-state">No watched frequency. Add one from Spectrum.</p>}</section>

        <section className="panel deck-automation"><header><div><span className="kicker">AUTONOMOUS COLLECTION</span><h2>Worker and receiver posture</h2></div><Link href="/capture">Control plane</Link></header><div className="automation-grid"><article><span>Worker</span><b>{String((components.worker as Row | undefined)?.status ?? "UNKNOWN")}</b><small>{String(automationData.processing ? (automationData.processing as Row).active : 0)} processing jobs</small></article><article><span>Scheduler</span><b>{scheduler.capture_globally_enabled ? "ARMED" : "DISABLED"}</b><small>{String(automationCaptures.active ?? 0)} active · {String(automationCaptures.failed ?? 0)} failed</small></article><article><span>Receivers</span><b>{onlineReceivers} online</b><small>{String((automationData.receivers as Row | undefined)?.capture_configured ?? 0)} capture-configured</small></article><article><span>Feeds</span><b>{String(automationSources.enabled ?? 0)} active</b><small>{String(automationSources.active_fetches ?? 0)} fetching now</small></article></div></section>

        <section className="panel deck-entities"><header><div><span className="kicker">ENTITY PULSE</span><h2>Repeated signals</h2></div><Link href="/graph">Relations</Link></header><div className="entity-columns"><article><span>CALLSIGNS</span>{topCallsigns.length ? topCallsigns.map(row => <p key={String(row.value)}><b>{String(row.value)}</b><small>{String(row.count)} occurrences</small></p>) : <p className="empty-state">None extracted.</p>}</article><article><span>NUMBER GROUPS</span>{topNumberGroups.length ? topNumberGroups.map(row => <p key={String(row.value)}><b>{String(row.value)}</b><small>{String(row.count)} occurrences</small></p>) : <p className="empty-state">None extracted.</p>}</article></div></section>

        <section className="panel deck-notebook"><header><div><span className="kicker">INVESTIGATION NOTEBOOK</span><h2>Events and reusable queries</h2></div><span>{activeHypotheses} active hypotheses</span></header><div className="notebook-grid"><article><h3>External events</h3>{eventRows.length ? eventRows.slice(0, 4).map(row => <Link href={`/events/${String(row.id)}`} key={String(row.id)}><b>{String(row.title)}</b><small>{String(row.event_type)} · {String(row.started_at_utc ?? "time unknown")}</small></Link>) : <p className="empty-state">No external event recorded.</p>}</article><article><h3>Saved queries</h3>{(savedQueries.data?.data ?? []).slice(0, 4).map(row => <Link href={`/sessions?query=${encodeURIComponent(String(row.id))}`} key={String(row.id)}><b>{String(row.name)}</b><small>{String(row.query_type)}</small></Link>)}<Link className="queue-cta" href="/api-docs">Tool API / context bundle →</Link></article></div></section>
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

type SpectrumCell = { time_bin: number; frequency_bin: number; session_count: number; active_duration_sec: number; mean_confidence: number };
type SpectrumSession = Row & { primary_frequency_hz: number; start_at_utc: string; end_at_utc: string; callsigns: string[]; number_groups: string[] };
type SpectrumPayload = Row & {
  time_bins: number;
  frequency_bins: number;
  time_bin_sec: number;
  frequency_bin_hz: number;
  frequency_min_hz: number;
  frequency_max_hz: number;
  cells: SpectrumCell[];
  sessions: SpectrumSession[];
  markers: Row[];
};

type SpectrumSelection = { timeBin: number; frequencyBin: number };

function activityColor(value: number) {
  if (value <= 0) return "#0b0d10";
  const normalized = Math.min(1, Math.log1p(value) / Math.log(7));
  const hue = 215 - normalized * 175;
  const lightness = 18 + normalized * 53;
  return `hsl(${hue} 82% ${lightness}%)`;
}

function SpectrumWaterfall({ data, selection, onSelect }: { data: SpectrumPayload; selection: SpectrumSelection | null; onSelect: (value: SpectrumSelection) => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const node = canvas.current;
    if (!node) return;
    const context = node.getContext("2d");
    if (!context) return;
    const rect = node.getBoundingClientRect();
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(320, Math.floor(rect.width || 900));
    const height = Math.max(280, Math.floor(rect.height || 480));
    node.width = width * ratio;
    node.height = height * ratio;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.fillStyle = "#08090b";
    context.fillRect(0, 0, width, height);
    const cellWidth = width / data.time_bins;
    const cellHeight = height / data.frequency_bins;
    const counts = new Map(data.cells.map(cell => [`${cell.time_bin}:${cell.frequency_bin}`, cell.session_count]));
    for (let time = 0; time < data.time_bins; time += 1) {
      for (let freq = 0; freq < data.frequency_bins; freq += 1) {
        const drawY = height - (freq + 1) * cellHeight;
        context.fillStyle = activityColor(counts.get(`${time}:${freq}`) ?? 0);
        context.fillRect(time * cellWidth, drawY, Math.ceil(cellWidth), Math.ceil(cellHeight));
      }
    }
    context.strokeStyle = "rgba(255,255,255,.08)";
    context.lineWidth = 1;
    for (let time = 0; time <= data.time_bins; time += Math.max(1, Math.floor(data.time_bins / 8))) {
      context.beginPath(); context.moveTo(time * cellWidth, 0); context.lineTo(time * cellWidth, height); context.stroke();
    }
    for (const marker of data.markers) {
      const markerBin = Math.floor((Number(marker.frequency_hz) - data.frequency_min_hz) / data.frequency_bin_hz);
      if (markerBin < 0 || markerBin >= data.frequency_bins) continue;
      const y = height - (markerBin + 0.5) * cellHeight;
      context.strokeStyle = marker.watchlisted ? "#f3c969" : "rgba(190,200,209,.42)";
      context.setLineDash([3, 4]); context.beginPath(); context.moveTo(0, y); context.lineTo(width, y); context.stroke(); context.setLineDash([]);
    }
    if (selection) {
      context.strokeStyle = "#f8fafc";
      context.lineWidth = 2;
      context.strokeRect(selection.timeBin * cellWidth, height - (selection.frequencyBin + 1) * cellHeight, cellWidth, cellHeight);
    }
  }, [data, selection]);
  return <canvas
    ref={canvas}
    className="spectrum-canvas"
    data-testid="spectrum-waterfall"
    aria-label="Indexed activity waterfall. Click a time and frequency cell to inspect indexed sessions."
    role="img"
    onClick={event => {
      const rect = event.currentTarget.getBoundingClientRect();
      const timeBin = Math.min(data.time_bins - 1, Math.max(0, Math.floor((event.clientX - rect.left) / rect.width * data.time_bins)));
      const frequencyBin = Math.min(data.frequency_bins - 1, Math.max(0, Math.floor((rect.bottom - event.clientY) / rect.height * data.frequency_bins)));
      onSelect({ timeBin, frequencyBin });
    }}
  />;
}

function toUtcInput(value: Date) {
  return value.toISOString().slice(0, 16);
}

export function FrequenciesView({ frequency }: { frequency?: number }) {
  const client = useQueryClient();
  const initialEnd = useMemo(() => new Date(), []);
  const initialStart = useMemo(() => new Date(initialEnd.getTime() - 7 * 86_400_000), [initialEnd]);
  const [start, setStart] = useState(toUtcInput(initialStart));
  const [end, setEnd] = useState(toUtcInput(initialEnd));
  const [range, setRange] = useState(() => ({ min: frequency ? Math.max(0, frequency - 100_000) : 2_000_000, max: frequency ? frequency + 100_000 : 30_000_000 }));
  const [mode, setMode] = useState("");
  const [receiverId, setReceiverId] = useState("");
  const [selection, setSelection] = useState<SpectrumSelection | null>(null);
  const spectrumPath = useMemo(() => {
    const params = new URLSearchParams({ start_at_utc: new Date(start).toISOString(), end_at_utc: new Date(end).toISOString(), frequency_min_hz: String(range.min), frequency_max_hz: String(range.max), time_bins: "96", frequency_bins: "96" });
    if (mode) params.set("mode", mode);
    if (receiverId) params.set("receiver_id", receiverId);
    return `/spectrum?${params.toString()}`;
  }, [end, mode, range.max, range.min, receiverId, start]);
  const spectrum = useApi<SpectrumPayload>(["spectrum", spectrumPath], spectrumPath);
  const receivers = useApi<Row[]>(["spectrum-receivers"], "/receivers?limit=500");
  const update = useMutation({
    mutationFn: ({ id, watchlisted, favorite }: { id: string; watchlisted: boolean; favorite: boolean }) => api(`/frequencies/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ watchlisted, favorite }) }),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["spectrum"] }); },
  });
  const data = spectrum.data?.data;
  const selectedStart = data && selection ? new Date(new Date(String(data.start_at_utc)).getTime() + selection.timeBin * data.time_bin_sec * 1000) : null;
  const selectedEnd = selectedStart && data ? new Date(selectedStart.getTime() + data.time_bin_sec * 1000) : null;
  const selectedFrequencyMin = data && selection ? data.frequency_min_hz + selection.frequencyBin * data.frequency_bin_hz : null;
  const selectedFrequencyMax = selectedFrequencyMin != null && data ? selectedFrequencyMin + data.frequency_bin_hz : null;
  const selectedSessions = data && selection && selectedStart && selectedEnd && selectedFrequencyMin != null && selectedFrequencyMax != null
    ? data.sessions.filter(session => new Date(session.end_at_utc) >= selectedStart && new Date(session.start_at_utc) <= selectedEnd && session.primary_frequency_hz >= selectedFrequencyMin && session.primary_frequency_hz < selectedFrequencyMax)
    : [];
  const selectedCell = data && selection ? data.cells.find(cell => cell.time_bin === selection.timeBin && cell.frequency_bin === selection.frequencyBin) : undefined;
  const setPreset = (min: number, max: number) => { setRange({ min, max }); setSelection(null); };
  return <DataState loading={spectrum.isLoading || receivers.isLoading} error={spectrum.error || receivers.error} empty={false}>
    <section className="spectrum-explorer" data-testid="spectrum-explorer">
      <div className="spectrum-main">
        <header className="spectrum-header">
          <div><span className="kicker">SPECTRUM EXPLORER / INDEXED OBSERVATIONS</span><h2>{frequency ? `${formatFrequency(frequency)} focus` : "Activity waterfall"}</h2><p>Time × frequency density from indexed sessions. It is not a live receiver FFT or IQ waterfall.</p></div>
          <div className="spectrum-status"><i/> INDEXED ACTIVITY <small>{data?.raw_fft_available ? "raw FFT available" : "raw FFT unavailable"}</small></div>
        </header>
        <div className="spectrum-toolbar" aria-label="Spectrum filters">
          <div className="spectrum-presets"><button onClick={() => setPreset(10_000, 500_000)}>VLF</button><button onClick={() => setPreset(2_000_000, 30_000_000)}>HF</button><button onClick={() => setPreset(3_000_000, 30_000_000)}>Shortwave</button></div>
          <label>From UTC<input aria-label="Spectrum start UTC" type="datetime-local" value={start} onChange={event => setStart(event.target.value)}/></label>
          <label>To UTC<input aria-label="Spectrum end UTC" type="datetime-local" value={end} onChange={event => setEnd(event.target.value)}/></label>
          <label>Min Hz<input aria-label="Spectrum minimum frequency" type="number" min="0" value={range.min} onChange={event => setRange(current => ({ ...current, min: Number(event.target.value) }))}/></label>
          <label>Max Hz<input aria-label="Spectrum maximum frequency" type="number" min="1" value={range.max} onChange={event => setRange(current => ({ ...current, max: Number(event.target.value) }))}/></label>
          <select aria-label="Spectrum mode" value={mode} onChange={event => setMode(event.target.value)}><option value="">All modes</option>{["AM", "USB", "LSB", "CW"].map(value => <option value={value} key={value}>{value}</option>)}</select>
          <select aria-label="Spectrum receiver" value={receiverId} onChange={event => setReceiverId(event.target.value)}><option value="">All receivers</option>{(receivers.data?.data ?? []).map(receiver => <option value={String(receiver.id)} key={String(receiver.id)}>{String(receiver.name)}</option>)}</select>
        </div>
        <div className="waterfall-shell">
          <div className="waterfall-y-axis"><span>{formatFrequency(data?.frequency_max_hz ?? range.max)}</span><span>{formatFrequency((Number(data?.frequency_min_hz ?? range.min) + Number(data?.frequency_max_hz ?? range.max)) / 2)}</span><span>{formatFrequency(data?.frequency_min_hz ?? range.min)}</span></div>
          <div className="waterfall-stage">{data ? <SpectrumWaterfall data={data} selection={selection} onSelect={setSelection}/> : <div className="spectrum-loading">Loading indexed activity…</div>}<div className="waterfall-markers" aria-label="Known frequency markers">{(data?.markers ?? []).filter(marker => marker.watchlisted || marker.favorite).slice(0, 12).map(marker => <span key={String(marker.id)} title={`${String(marker.label)} · ${formatFrequency(marker.frequency_hz)}`}>{String(marker.label)}</span>)}</div></div>
          <div className="waterfall-x-axis"><span>{data ? new Date(String(data.start_at_utc)).toISOString().slice(0, 16).replace("T", " ") : "UTC"}</span><span>UTC</span><span>{data ? new Date(String(data.end_at_utc)).toISOString().slice(0, 16).replace("T", " ") : ""}</span></div>
        </div>
        <footer className="spectrum-legend"><span><i className="legend-idle"/> no indexed session</span><span><i className="legend-low"/> sparse</span><span><i className="legend-high"/> repeated / high density</span><span>Dashed lines = known frequency; gold = watchlist.</span></footer>
        <section className="panel spectrum-results"><header><div><span className="kicker">SELECTION RESULTS</span><h2>{selection ? `${selectedSessions.length} overlapping session${selectedSessions.length === 1 ? "" : "s"}` : "Select a waterfall cell"}</h2></div><span>{selectedCell ? `${selectedCell.session_count} indexed observations` : "Click the grid"}</span></header>{selectedSessions.length ? <SessionTable rows={selectedSessions.slice(0, 30)}/> : <p className="empty-state">Choose a colored cell to inspect its sessions, callsigns, and number groups.</p>}</section>
      </div>
      <aside className="panel spectrum-inspector">
        <span className="kicker">CELL INSPECTOR</span><h2>{selectedFrequencyMin != null ? `${formatFrequency(selectedFrequencyMin)} – ${formatFrequency(selectedFrequencyMax)}` : "No cell selected"}</h2>
        {selectedStart && selectedEnd ? <p className="inspector-time">{selectedStart.toISOString().replace("T", " ").slice(0, 19)} → {selectedEnd.toISOString().replace("T", " ").slice(0, 19)} UTC</p> : <p className="inspector-time">Click a point in the time × frequency grid.</p>}
        <dl><dt>Sessions</dt><dd>{selectedCell?.session_count ?? 0}</dd><dt>Active seconds</dt><dd>{Math.round(selectedCell?.active_duration_sec ?? 0)}</dd><dt>Mean confidence</dt><dd>{selectedCell ? `${Math.round(selectedCell.mean_confidence * 100)}%` : "—"}</dd><dt>Bin width</dt><dd>{data ? formatFrequency(data.frequency_bin_hz) : "—"}</dd></dl>
        <h3>Entities in selection</h3><div className="spectrum-entities">{Array.from(new Set(selectedSessions.flatMap(session => session.callsigns ?? []))).map(value => <span key={`c-${value}`}>CALL {value}</span>)}{Array.from(new Set(selectedSessions.flatMap(session => session.number_groups ?? []))).map(value => <span key={`n-${value}`}># {value}</span>)}{!selectedSessions.length ? <small>Nothing selected yet.</small> : null}</div>
        <h3>Known frequencies</h3><div className="spectrum-marker-list">{(data?.markers ?? []).slice(0, 18).map(marker => <article key={String(marker.id)}><Link href={`/frequencies/${String(marker.frequency_hz)}`}><b>{formatFrequency(marker.frequency_hz)}</b><small>{String(marker.label)} · {String(marker.category)}</small></Link><button aria-label={`Watch ${String(marker.label)}`} onClick={() => update.mutate({ id: String(marker.id), watchlisted: !Boolean(marker.watchlisted), favorite: Boolean(marker.favorite) })}>{marker.watchlisted ? "Watching" : "Watch"}</button></article>)}</div>
      </aside>
    </section>
  </DataState>;
}

function ReceiverMap({ rows }: { rows: Row[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let map: import("maplibre-gl").Map | undefined;
    let disposed = false;
    void import("maplibre-gl").then(({ default: maplibre }) => {
      if (disposed || !ref.current) return;
      map = new maplibre.Map({ container: ref.current, center: [20, 20], zoom: 1.1, style: { version: 8, sources: {}, layers: [{ id: "background", type: "background", paint: { "background-color": "#081311" } }] } });
      const featureCollection = {
        type: "FeatureCollection" as const,
        features: rows.filter(row => row.latitude != null && row.longitude != null).map(row => ({
          type: "Feature" as const,
          geometry: { type: "Point" as const, coordinates: [Number(row.longitude), Number(row.latitude)] },
          properties: { id: String(row.id), name: String(row.name), status: String(row.status) },
        })),
      };
      map.on("load", () => {
        if (!map) return;
        map.addSource("receivers", { type: "geojson", data: featureCollection, cluster: true, clusterMaxZoom: 8, clusterRadius: 46 });
        map.addLayer({ id: "receiver-clusters", type: "circle", source: "receivers", filter: ["has", "point_count"], paint: { "circle-color": "#173b2d", "circle-stroke-color": "#67e6a0", "circle-stroke-width": 2, "circle-radius": ["step", ["get", "point_count"], 18, 10, 24, 50, 32] } });
        map.addLayer({ id: "receiver-cluster-count", type: "symbol", source: "receivers", filter: ["has", "point_count"], layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 12 }, paint: { "text-color": "#dceae5" } });
        map.addLayer({ id: "receiver-points", type: "circle", source: "receivers", filter: ["!", ["has", "point_count"]], paint: { "circle-color": ["match", ["get", "status"], "ONLINE", "#67e6a0", "OFFLINE", "#ef6f65", "#d5a94a"], "circle-radius": 8, "circle-stroke-color": "#07100e", "circle-stroke-width": 3 } });
        map.on("click", "receiver-clusters", event => {
          const feature = map?.queryRenderedFeatures(event.point, { layers: ["receiver-clusters"] })[0];
          const clusterId = Number(feature?.properties?.cluster_id);
          const source = map?.getSource("receivers") as import("maplibre-gl").GeoJSONSource | undefined;
          if (!feature || !source || !Number.isFinite(clusterId)) return;
          void source.getClusterExpansionZoom(clusterId).then(zoom => {
            const coordinates = (feature.geometry as unknown as { coordinates: [number, number] }).coordinates;
            map?.easeTo({ center: coordinates, zoom });
          });
        });
        map.on("click", "receiver-points", event => {
          const id = event.features?.[0]?.properties?.id;
          if (id) location.assign(`/receivers/${String(id)}`);
        });
      });
    });
    return () => { disposed = true; map?.remove(); };
  }, [rows]);
  return <div ref={ref} className="map" data-testid="receiver-map" aria-label="Receiver locations map"/>;
}

function ReceiverCaptureControl({ receiver }: { receiver: Row }) {
  const client = useQueryClient();
  const metadata = (receiver.metadata_json as Row | undefined) ?? {};
  const [message, setMessage] = useState("");
  const save = useMutation({
    mutationFn: (payload: Row) => api<Envelope<Row>>(
      `/receivers/${encodeURIComponent(String(receiver.id))}/capture`,
      { method: "PATCH", body: JSON.stringify(payload) },
    ),
    onSuccess: () => {
      setMessage("Receiver capture transport saved. It can now be selected by autonomous schedules.");
      void client.invalidateQueries({ queryKey: ["receiver", receiver.id] });
      void client.invalidateQueries({ queryKey: ["receivers"] });
      void client.invalidateQueries({ queryKey: ["automation-status"] });
    },
  });
  return <section className="receiver-capture-control"><h3>Unattended capture transport</h3><p>Provide an authorised direct audio URL, not merely a browser tuning URL. The worker only accepts the registered receiver host and expands <code>{"{frequency_hz}"}</code>, <code>{"{frequency_khz}"}</code>, and <code>{"{mode}"}</code>.</p><form onSubmit={event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    save.mutate({
      capture_url_template: String(form.get("capture_url_template") || "") || null,
      capture_enabled: form.get("capture_enabled") === "on",
    });
  }}><label>Direct audio URL template<input name="capture_url_template" type="text" inputMode="url" defaultValue={String(metadata.capture_url_template ?? "")} placeholder="https://receiver.example/audio?freq={frequency_hz}&mode={mode}"/></label><label><input name="capture_enabled" type="checkbox" defaultChecked={Boolean(metadata.capture_enabled)}/> I am authorised to capture from this receiver continuously</label><button disabled={save.isPending}>Save capture transport</button>{message ? <p role="status">{message}</p> : null}{save.error ? <p role="alert">{save.error.message}</p> : null}</form></section>;
}

function ReceiverTuneControl({ receiver }: { receiver: Row }) {
  const [frequencyHz, setFrequencyHz] = useState(4_625_000);
  const [mode, setMode] = useState("USB");
  const [message, setMessage] = useState("");
  const tune = useMutation({
    mutationFn: () => api<Envelope<{ url: string }>>(
      `/receivers/${encodeURIComponent(String(receiver.id))}/tune?frequency_hz=${frequencyHz}&mode=${encodeURIComponent(mode)}`,
    ),
    onSuccess: response => {
      setMessage(response.warnings[0] ?? "Opening receiver tuning page.");
      window.open(response.data.url, "_blank", "noopener,noreferrer");
    },
  });
  return <section className="receiver-capture-control"><h3>Browser tuning link</h3><p>This opens the public receiver UI at the requested frequency. It is not an audio capture command.</p><div className="form-grid"><label>Frequency Hz<input value={frequencyHz} min="0" type="number" onChange={event => setFrequencyHz(Number(event.target.value) || 0)}/></label><label>Mode<input value={mode} maxLength={20} onChange={event => setMode(event.target.value.toUpperCase())}/></label></div><button className="primary" onClick={() => tune.mutate()} disabled={tune.isPending}>Open tuned receiver</button>{message ? <p role="status">{message}</p> : null}{tune.error ? <p role="alert">{tune.error.message}</p> : null}</section>;
}

export function ReceiversView({ id }: { id?: string }) {
  const list = useApi<Row[]>(["receivers"], "/receivers?limit=500");
  const detail = useApi<Row>(["receiver", id], id ? `/receivers/${encodeURIComponent(id)}` : "/capabilities");
  const history = useApi<Row[]>(["receiver-status", id], id ? `/receivers/${encodeURIComponent(id)}/status-history?limit=100` : "/receivers?limit=1");
  const rows = list.data?.data ?? [];
  const selected = id ? detail.data?.data : undefined;
  return (
    <DataState loading={list.isLoading || (Boolean(id) && detail.isLoading)} error={list.error || (id ? detail.error : null)} empty={rows.length === 0}>
      <div className="split"><section className="panel"><p className="map-note">Receiver positions only; transmitter location is not inferred. Nearby receivers are clustered.</p><ReceiverMap rows={rows}/></section><aside className="panel receiver-list">{selected ? <><Layer kind="observed"/><h2>{String(selected.name)}</h2><p>{String(selected.receiver_type)} · {String(selected.status)}</p><p>{formatFrequency(selected.min_frequency_hz)}–{formatFrequency(selected.max_frequency_hz)}</p><a className="primary" href={String(selected.base_url)} target="_blank" rel="noreferrer">Open receiver home</a><ReceiverTuneControl receiver={selected}/><ReceiverCaptureControl receiver={selected}/><h3>Status history</h3>{(history.data?.data ?? []).map(row => <p key={String(row.id)}><b>{String(row.status)}</b><br/><span>{String(row.created_at)} · {String(row.latency_ms ?? "—")} ms</span></p>)}</> : rows.map(row => <Link href={`/receivers/${String(row.id)}`} key={String(row.id)}><div><b>{String(row.name)}</b><span>{String(row.receiver_type)} · {String(row.status)}</span></div></Link>)}</aside></div>
    </DataState>
  );
}
