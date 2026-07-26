"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type Envelope } from "@/lib/api";
import { queueOffline } from "@/lib/offline";
import { DataState, Layer } from "./data-state";

type Row = Record<string, unknown>;

export function InboxView() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["inbox"], queryFn: () => api<Envelope<Row[]>>("/inbox?limit=100") });
  const [message, setMessage] = useState("");
  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const type = String(form.get("item_type"));
    const observed = String(form.get("observed_at_utc"));
    const payload = {
      item_type: type,
      text_content: String(form.get("text_content") || "") || null,
      source_url: String(form.get("source_url") || "") || null,
      frequency_hz: Number(form.get("frequency_hz")) || null,
      mode: String(form.get("mode") || "") || null,
      observed_at_utc: observed ? new Date(observed).toISOString() : new Date().toISOString(),
      note: String(form.get("note") || "") || null,
      tags: String(form.get("tags") || "").split(",").map(value => value.trim()).filter(Boolean),
    };
    try {
      const file = form.get("file");
      if (!navigator.onLine) {
        await queueOffline("inbox", payload);
        setMessage("Queued offline; reconnect will synchronize it.");
      } else if (type === "audio" && file instanceof File && file.size) {
        const upload = new FormData();
        upload.set("file", file);
        upload.set("frequency_hz", String(payload.frequency_hz ?? 0));
        upload.set("mode", payload.mode ?? "");
        upload.set("started_at_utc", payload.observed_at_utc);
        upload.set("source_type", "MANUAL_UPLOAD");
        await api("/recordings/upload", { method: "POST", body: upload });
        setMessage("Immutable original stored and processing queued.");
      } else {
        await api("/inbox", { method: "POST", body: JSON.stringify(payload) });
        setMessage("Inbox item stored.");
      }
      await client.invalidateQueries({ queryKey: ["inbox"] });
      event.currentTarget.reset();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Inbox save failed");
    }
  };
  return (
    <div className="split inbox-page">
      <section className="panel inbox-form">
        <span className="kicker">UNIVERSAL INBOX</span><h2>Capture now, classify later</h2>
        <form onSubmit={submit} data-testid="inbox-form">
          <label>Type<select name="item_type"><option value="audio">Audio</option><option value="text">Text</option><option value="url">URL</option><option value="image">Image</option><option value="pdf">PDF</option><option value="csv">CSV</option><option value="json">JSON</option><option value="observation">Observation</option></select></label>
          <label className="drop">Optional file<input name="file" type="file"/></label>
          <div className="form-grid"><label>Frequency Hz<input name="frequency_hz" inputMode="numeric"/></label><label>Mode<input name="mode" placeholder="USB"/></label><label>UTC<input name="observed_at_utc" type="datetime-local"/></label><label>Source URL<input name="source_url" type="url"/></label></div>
          <label>Text<textarea name="text_content"/></label><label>Note<textarea name="note"/></label><label>Tags<input name="tags" placeholder="watchlist, voice"/></label>
          <button className="primary">Save</button>{message ? <p role="status">{message}</p> : null}
        </form>
      </section>
      <aside className="panel"><span className="kicker">UNCLASSIFIED</span><DataState loading={query.isLoading} error={query.error} empty={(query.data?.data.length ?? 0) === 0}>{(query.data?.data ?? []).map(row => <article className="queue" key={String(row.id)}><Layer kind="observed"/><b>{String(row.item_type)}</b><small>{String(row.note || row.text_content || row.source_url || "No note")}</small></article>)}</DataState></aside>
    </div>
  );
}

export function SourcesView({ id }: { id?: string }) {
  const client = useQueryClient();
  const list = useQuery({ queryKey: ["sources"], queryFn: () => api<Envelope<Row[]>>("/sources?limit=200") });
  const detail = useQuery({ queryKey: ["source", id], enabled: Boolean(id), queryFn: () => api<Envelope<Row>>(`/sources/${encodeURIComponent(id!)}`) });
  const create = useMutation({
    mutationFn: (payload: Row) => api<Envelope<Row>>("/sources", { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["sources"] }),
  });
  const fetchNow = useMutation({ mutationFn: () => api(`/sources/${encodeURIComponent(id!)}/fetch`, { method: "POST", body: "{}" }) });
  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const baseUrl = String(form.get("base_url") || "");
    const host = baseUrl ? new URL(baseUrl).hostname : "";
    create.mutate({
      name: String(form.get("name")),
      adapter_type: String(form.get("adapter_type")),
      base_url: baseUrl || null,
      enabled: false,
      config: { record_type: String(form.get("record_type")), allowed_hosts: host ? [host] : [], interval_sec: 3600, archive_raw_response: true },
    });
  };
  if (id) {
    const row = detail.data?.data;
    return <DataState loading={detail.isLoading} error={detail.error} empty={!row}>{row ? <section className="panel full"><Layer kind="observed"/><h2>{String(row.name)}</h2><pre>{JSON.stringify(row, null, 2)}</pre><button disabled={!row.enabled || fetchNow.isPending} onClick={() => fetchNow.mutate()}>Fetch now</button>{fetchNow.data ? <p role="status">Fetch queued.</p> : null}</section> : null}</DataState>;
  }
  return (
    <div className="split">
      <section className="panel"><h2>Registered sources</h2><DataState loading={list.isLoading} error={list.error} empty={(list.data?.data.length ?? 0) === 0}><div className="cards">{(list.data?.data ?? []).map(row => <Link href={`/sources/${String(row.id)}`} key={String(row.id)}><Layer kind="observed"/><h2>{String(row.name)}</h2><p>{String(row.adapter_type)} · {row.enabled ? "enabled" : "disabled"}</p></Link>)}</div></DataState></section>
      <aside className="panel inbox-form"><h2>Register source</h2><form onSubmit={submit}><label>Name<input name="name" required/></label><label>Adapter<select name="adapter_type"><option value="rss_atom">RSS/Atom</option><option value="generic_html_table">HTML table</option><option value="user_defined_static">Static</option></select></label><label>Record type<select name="record_type"><option>EVENT</option><option>FREQUENCY</option><option>RECEIVER</option></select></label><label>URL<input name="base_url" type="url"/></label><button className="primary">Register disabled</button>{create.error ? <p role="alert">{create.error.message}</p> : null}</form><p className="policy">Remote sources are disabled by default and use an explicit host allowlist.</p></aside>
    </div>
  );
}

export function CaptureView() {
  const client = useQueryClient();
  const receivers = useQuery({ queryKey: ["receivers"], queryFn: () => api<Envelope<Row[]>>("/receivers?limit=500") });
  const jobs = useQuery({ queryKey: ["captures"], queryFn: () => api<Envelope<Row[]>>("/capture?limit=100") });
  const create = useMutation({
    mutationFn: (payload: Row) => api("/capture", { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["captures"] }),
  });
  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    create.mutate({ receiver_id: form.get("receiver_id"), frequency_hz: Number(form.get("frequency_hz")), mode: form.get("mode"), schedule_utc: form.get("schedule_utc"), capture_duration_sec: Number(form.get("capture_duration_sec")), enabled: false, retention_policy: {} });
  };
  return <div className="split"><section className="panel inbox-form"><h2>Explicit watchlist capture</h2><p>New schedules are deliberately saved disabled.</p><form onSubmit={submit}><label>Receiver<select name="receiver_id" required>{(receivers.data?.data ?? []).map(row => <option value={String(row.id)} key={String(row.id)}>{String(row.name)}</option>)}</select></label><label>Frequency Hz<input name="frequency_hz" type="number" required/></label><label>Mode<input name="mode" defaultValue="USB" required/></label><label>UTC ISO or cron<input name="schedule_utc" defaultValue="40 18 * * *" required/></label><label>Duration seconds<input name="capture_duration_sec" type="number" min="1" max="86400" defaultValue="60"/></label><button className="primary">Save disabled schedule</button>{create.error ? <p role="alert">{create.error.message}</p> : null}</form></section><aside className="panel"><h2>Capture jobs</h2><DataState loading={jobs.isLoading} error={jobs.error} empty={(jobs.data?.data.length ?? 0) === 0}>{(jobs.data?.data ?? []).map(row => <p key={String(row.id)}><b>{String(row.frequency_hz)} Hz</b><br/>{String(row.status)} · next {String(row.next_run_at)}</p>)}</DataState></aside></div>;
}

export function SettingsView() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["settings"], queryFn: () => api<Envelope<Row[]>>("/settings?limit=200") });
  const save = useMutation({
    mutationFn: (payload: Row) => api("/settings", { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["settings"] }),
  });
  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    save.mutate({ key: String(form.get("key")), value: { value: String(form.get("value")) } });
  };
  return <div className="split"><section className="panel settings-view"><h2>Versioned configuration</h2><form onSubmit={submit}><label>Key<input name="key" placeholder="display.timezone" required/></label><label>Value<input name="value" required/></label><button className="primary">Save new revision</button>{save.data ? <p role="status">Revision stored.</p> : null}{save.error ? <p role="alert">{save.error.message}</p> : null}</form></section><aside className="panel"><h2>Revision history</h2><DataState loading={query.isLoading} error={query.error} empty={(query.data?.data.length ?? 0) === 0}><pre>{JSON.stringify(query.data?.data ?? [], null, 2)}</pre></DataState></aside></div>;
}

export function ApiDocsView() {
  const query = useQuery({ queryKey: ["capabilities"], queryFn: () => api<Envelope<Row>>("/capabilities") });
  return <section className="panel full docs"><h2>Local LLM tool API</h2><p>The live response below is the authority; unavailable features are not advertised as implemented.</p><DataState loading={query.isLoading} error={query.error} empty={!query.data}><pre>{JSON.stringify(query.data, null, 2)}</pre></DataState><a href={`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1"}`.replace("/api/v1", "/docs")} target="_blank" rel="noreferrer">OpenAPI documentation</a></section>;
}

export function LoginView() {
  const [error, setError] = useState("");
  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api("/auth/login", { method: "POST", body: JSON.stringify({ email: form.get("email"), password: form.get("password") }) });
      location.assign("/dashboard");
    } catch {
      setError("Invalid credentials or API unavailable.");
    }
  };
  return <main className="login"><section><span className="kicker">PRIVATE WORKSPACE</span><h1>Signal Index</h1><p>Structure observations. Preserve evidence. Test hypotheses.</p><form onSubmit={submit}><label>Email<input name="email" type="email" autoComplete="username" required/></label><label>Password<input name="password" type="password" autoComplete="current-password" required/></label><button className="primary">Sign in</button>{error ? <p role="alert">{error}</p> : null}</form><small>Public registration disabled · secure session cookie</small></section></main>;
}
