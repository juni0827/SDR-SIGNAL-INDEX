"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Pause, Play } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { api, type Envelope } from "@/lib/api";
import { queueOffline } from "@/lib/offline";
import { DataState, Layer } from "./data-state";

type Row = Record<string, unknown>;
type Media = { processed_url: string | null; waveform_url: string | null; spectrogram_url: string | null };
type RecordingMedia = { original_url: string; processed_url: string | null; preview_url: string | null };

function Waveform({ url }: { url?: string | null }) {
  const query = useQuery({
    queryKey: ["waveform", url],
    enabled: Boolean(url),
    queryFn: async () => {
      const response = await fetch(url!);
      if (!response.ok) throw new Error(`waveform:${response.status}`);
      return response.json() as Promise<{ min: number[]; max: number[] }>;
    },
  });
  const points = query.data?.max ?? [];
  if (!url) return <div className="waveform"><em>No derived waveform available.</em></div>;
  if (query.isLoading) return <div className="waveform"><em>Loading waveform…</em></div>;
  if (query.error) return <div className="waveform"><em>Waveform request failed.</em></div>;
  const sampled = points.filter((_, index) => index % Math.max(1, Math.floor(points.length / 180)) === 0);
  return <div className="waveform" aria-label="Processed segment waveform">{sampled.map((value, index) => <i key={index} style={{ height: `${Math.max(2, Math.abs(value) * 100)}%` }}/>)}</div>;
}

export function AudioReviewView({ segmentId }: { segmentId: string }) {
  const client = useQueryClient();
  const audio = useRef<HTMLAudioElement>(null);
  const context = useRef<AudioContext | null>(null);
  const gainNode = useRef<GainNode | null>(null);
  const segment = useQuery({ queryKey: ["segment", segmentId], queryFn: () => api<Envelope<Row>>(`/segments/${encodeURIComponent(segmentId)}`) });
  const recordingId = String(segment.data?.data.recording_id ?? "");
  const media = useQuery({ queryKey: ["segment-media", segmentId], queryFn: () => api<Envelope<Media>>(`/segments/${encodeURIComponent(segmentId)}/media`) });
  const recordingMedia = useQuery({ queryKey: ["recording-media", recordingId], enabled: Boolean(recordingId), queryFn: () => api<Envelope<RecordingMedia>>(`/recordings/${encodeURIComponent(recordingId)}/media`) });
  const [variant, setVariant] = useState<"segment" | "processed" | "original" | "preview">("segment");
  const [playing, setPlaying] = useState(false);
  const [text, setText] = useState("");
  const [language, setLanguage] = useState("en");
  const [splitAt, setSplitAt] = useState("");
  const [mergeIds, setMergeIds] = useState(segmentId);
  const [annotation, setAnnotation] = useState("");
  const [status, setStatus] = useState("");
  const [loop, setLoop] = useState(false);
  const row = segment.data?.data;
  const transcripts = useMemo(() => (row?.transcripts as Row[] | undefined) ?? [], [row?.transcripts]);
  const entities = useMemo(() => (row?.entities as Row[] | undefined) ?? [], [row?.entities]);
  useEffect(() => {
    const preferred = transcripts.find(value => value.is_preferred) ?? transcripts[0];
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      setText(String(preferred?.text ?? ""));
      setLanguage(String(preferred?.language ?? "en"));
    });
    return () => { active = false; };
  }, [transcripts]);
  const source = variant === "segment"
    ? media.data?.data.processed_url
    : variant === "original"
      ? recordingMedia.data?.data.original_url
      : variant === "preview"
        ? recordingMedia.data?.data.preview_url
        : recordingMedia.data?.data.processed_url;
  const refresh = async () => {
    await client.invalidateQueries({ queryKey: ["segment", segmentId] });
    await client.invalidateQueries({ queryKey: ["recording", recordingId] });
  };
  const action = async (label: string, callback: () => Promise<unknown>) => {
    setStatus(`${label}…`);
    try {
      await callback();
      await refresh();
      setStatus(`${label} completed.`);
    } catch (error) {
      setStatus(`${label} failed: ${error instanceof Error ? error.message : "unknown error"}`);
    }
  };
  const toggle = async () => {
    if (!audio.current || !source) return;
    if (audio.current.paused) {
      await audio.current.play();
      setPlaying(true);
    } else {
      audio.current.pause();
      setPlaying(false);
    }
  };
  useEffect(() => {
    const keyboard = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      if (event.code === "Space") {
        event.preventDefault();
        void toggle();
      } else if (event.key.toLowerCase() === "a") {
        setVariant(current => current === "original" ? "processed" : "original");
      } else if (event.key.toLowerCase() === "l") {
        setLoop(current => !current);
      } else if (event.key === "[") {
        if (audio.current) audio.current.playbackRate = Math.max(0.5, audio.current.playbackRate - 0.25);
      } else if (event.key === "]") {
        if (audio.current) audio.current.playbackRate = Math.min(2, audio.current.playbackRate + 0.25);
      }
    };
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  });
  const setGain = (value: number) => {
    if (!audio.current) return;
    try {
      if (!context.current) {
        context.current = new AudioContext();
        const sourceNode = context.current.createMediaElementSource(audio.current);
        gainNode.current = context.current.createGain();
        sourceNode.connect(gainNode.current).connect(context.current.destination);
      }
      if (gainNode.current) gainNode.current.gain.value = value;
    } catch (error) {
      console.error("web_audio_gain_failed", error);
      audio.current.volume = Math.min(1, value);
    }
  };
  const saveAnnotation = async () => {
    const payload = { target_type: "SEGMENT", target_id: segmentId, body: annotation, tags: [] };
    if (!navigator.onLine) {
      await queueOffline("annotation", payload);
      setStatus("Annotation queued offline.");
      return;
    }
    await action("Save annotation", () => api("/annotations", { method: "POST", body: JSON.stringify(payload) }));
    setAnnotation("");
  };
  return (
    <DataState loading={segment.isLoading || media.isLoading} error={segment.error || media.error} empty={!row}>
      {row ? <div className="review" data-testid="audio-review">
        <section className="panel audio">
          <header><div><span className="kicker">SEGMENT · {segmentId}</span><h2>{Number(row.start_sec).toFixed(2)}–{Number(row.end_sec).toFixed(2)} s · {String(row.segment_type)}</h2></div><Layer kind={row.manually_adjusted ? "corrected" : "machine"}/></header>
          <div className="tabs">{(["segment", "processed", "original", "preview"] as const).map(value => <button key={value} aria-pressed={variant === value} onClick={() => setVariant(value)}>{value}</button>)}</div>
          <audio ref={audio} src={source ?? undefined} preload="metadata" onLoadedMetadata={() => {
            if (audio.current && variant !== "segment") audio.current.currentTime = Number(row.start_sec);
          }} onTimeUpdate={() => {
            if (!audio.current || !loop) return;
            const start = variant === "segment" ? 0 : Number(row.start_sec);
            const end = variant === "segment" ? Number(row.duration_sec) : Number(row.end_sec);
            if (audio.current.currentTime >= end) audio.current.currentTime = start;
          }} onEnded={() => setPlaying(false)} aria-label="Recording audio"/>
          <Waveform url={media.data?.data.waveform_url}/>
          {media.data?.data.spectrogram_url ? <object className="spectrogram" data={media.data.data.spectrogram_url} type="image/png" aria-label="Processed segment spectrogram"/> : <div className="spectrogram" aria-label="No spectrogram"/>}
          <footer className="transport"><button onClick={() => void toggle()} aria-label={playing ? "Pause audio" : "Play audio"}>{playing ? <Pause/> : <Play/>}</button>{[0.75, 1, 1.25, 1.5].map(rate => <button key={rate} onClick={() => { if (audio.current) audio.current.playbackRate = rate; }}>{rate}×</button>)}<label>Gain<input type="range" min=".1" max="2" step=".1" defaultValue="1" onChange={event => setGain(Number(event.target.value))}/></label><button aria-pressed={loop} onClick={() => setLoop(current => !current)}>Loop selection</button><button aria-pressed={variant === "preview"} onClick={() => setVariant(current => current === "preview" ? "processed" : "preview")}>Noise reduction preview</button></footer>
          <div className="segment-actions">
            <label>Split at seconds<input aria-label="Split at seconds" value={splitAt} onChange={event => setSplitAt(event.target.value)}/></label>
            <button onClick={() => void action("Split", () => api(`/segments/${encodeURIComponent(segmentId)}/split`, { method: "POST", body: JSON.stringify({ at_sec: Number(splitAt) }) }))}>Split</button>
            <label>Merge IDs<input aria-label="Merge segment IDs" value={mergeIds} onChange={event => setMergeIds(event.target.value)}/></label>
            <button onClick={() => void action("Merge", () => api("/segments/merge", { method: "POST", body: JSON.stringify({ segment_ids: mergeIds.split(",").map(value => value.trim()).filter(Boolean) }) }))}>Merge</button>
            <button onClick={() => void action("Rerun VAD", () => api(`/recordings/${encodeURIComponent(recordingId)}/reprocess`, { method: "POST", body: JSON.stringify({ threshold: 0.55, minimum_speech_ms: 250, minimum_silence_ms: 400, padding_ms: 180, maximum_segment_sec: 45, merge_shorter_than_ms: 350 }) }))}>Rerun VAD</button>
            <select aria-label="Signal classification" value={String(row.segment_type)} onChange={event => void action("Classification", () => api(`/segments/${encodeURIComponent(segmentId)}/classification`, { method: "PATCH", body: JSON.stringify({ segment_type: event.target.value }) }))}>{["VOICE", "TONE", "MULTIPLE_TONE", "DIGITAL", "MUSIC", "NOISE", "CARRIER", "UNKNOWN"].map(value => <option key={value}>{value}</option>)}</select>
            <button onClick={() => void action("Review", () => api(`/segments/${encodeURIComponent(segmentId)}/review`, { method: "PATCH", body: JSON.stringify({ reviewed: !row.reviewed }) }))}>{row.reviewed ? "Mark unreviewed" : "Mark reviewed"}</button>
          </div>
        </section>
        <section className="panel transcript">
          <header><div><span className="kicker">TRANSCRIPT CANDIDATES · {transcripts.length}</span><h2>Evidence-preserving correction</h2></div><b>{Math.round(Number((transcripts.find(value => value.is_preferred) ?? transcripts[0])?.confidence ?? 0) * 100)}%</b></header>
          <div className="cards">{transcripts.map(candidate => <article key={String(candidate.id)}><Layer kind={candidate.transcript_type === "MACHINE" || candidate.transcript_type === "ALTERNATIVE" ? "machine" : "corrected"}/><b>{String(candidate.model_version || candidate.transcript_type)}</b><p>{String(candidate.text)}</p><button disabled={Boolean(candidate.is_preferred)} onClick={() => void action("Select transcript", () => api(`/transcripts/${encodeURIComponent(String(candidate.id))}/preferred`, { method: "PATCH", body: "{}" }))}>{candidate.is_preferred ? "Preferred" : "Make preferred"}</button></article>)}</div>
          <textarea data-testid="transcript-editor" aria-label="Transcript correction" value={text} onChange={event => setText(event.target.value)}/>
          <label>Language<input value={language} onChange={event => setLanguage(event.target.value)}/></label>
          <div className="entities">{entities.map(entity => <button key={String(entity.id)}>{String(entity.entity_type)} · {String(entity.raw_value)} → {String(entity.normalized_value)}</button>)}</div>
          <footer><button className="primary" data-testid="save-transcript" onClick={() => void action("Save corrected transcript", () => api(`/segments/${encodeURIComponent(segmentId)}/transcripts`, { method: "POST", body: JSON.stringify({ text, language, mark_preferred: true }) }))}>Save corrected & preferred</button></footer>
          <label>Annotation<textarea value={annotation} onChange={event => setAnnotation(event.target.value)} placeholder="Evidence-linked note…"/></label>
          <footer><button onClick={() => void saveAnnotation()} disabled={!annotation.trim()}>Save annotation</button></footer>
          {status ? <p role="status">{status}</p> : null}
          <h3>Word timestamps</h3>
          <div className="cards">{((transcripts.find(value => value.is_preferred)?.word_timestamps as Row[] | undefined) ?? []).map((word, index) => <button key={`${String(word.word)}-${index}`} onClick={() => { if (audio.current) audio.current.currentTime = Number(word.start); }}>{String(word.word)} · {Number(word.start).toFixed(2)}s</button>)}</div>
        </section>
        <aside className="panel review-context"><span className="kicker">REVIEW CONTEXT</span><h2>Entities</h2>{entities.map(entity => <p key={String(entity.id)}><b>{String(entity.entity_type)}</b><br/>{String(entity.raw_value)} → {String(entity.normalized_value)}</p>)}<h2>Keyboard</h2><dl><dt>Space</dt><dd>Play/pause</dd><dt>A</dt><dd>Original/processed</dd><dt>L</dt><dd>Loop selection</dd><dt>[ / ]</dt><dd>Playback speed</dd></dl><p className="policy">Acoustic similarity is not speaker identity.</p></aside>
      </div> : null}
    </DataState>
  );
}
