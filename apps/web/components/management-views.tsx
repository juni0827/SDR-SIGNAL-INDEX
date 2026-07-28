"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type Envelope } from "@/lib/api";
import { queueOffline } from "@/lib/offline";
import { loginWithPasskey, registerPasskey } from "@/lib/passkeys";
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
      if (!navigator.onLine && type === "audio" && file instanceof File && file.size) {
        await queueOffline("inbox", {
          ...payload,
          item_type: "observation",
          note: `${payload.note ?? ""}\nPending audio attachment: ${file.name} (${file.size} bytes)`.trim(),
        });
        setMessage("Audio metadata queued. Large audio is not cached offline; attach it after reconnecting.");
      } else if (!navigator.onLine && file instanceof File && file.size) {
        await queueOffline("inbox_file", {
          file,
          item_type: type,
          frequency_hz: payload.frequency_hz ?? "",
          mode: payload.mode ?? "",
          observed_at_utc: payload.observed_at_utc,
          note: payload.note ?? "",
          tags: payload.tags.join(","),
        });
        setMessage("Binary item queued offline; reconnect will upload and verify it.");
      } else if (!navigator.onLine) {
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
      } else if (file instanceof File && file.size) {
        const upload = new FormData();
        upload.set("file", file);
        upload.set("item_type", type);
        upload.set("frequency_hz", String(payload.frequency_hz ?? ""));
        upload.set("mode", payload.mode ?? "");
        upload.set("observed_at_utc", payload.observed_at_utc);
        upload.set("note", payload.note ?? "");
        upload.set("tags", payload.tags.join(","));
        await api("/inbox/upload", { method: "POST", body: upload });
        setMessage("Binary original stored privately with signature and checksum verification.");
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
      <aside className="panel"><span className="kicker">UNCLASSIFIED</span><DataState loading={query.isLoading} error={query.error} empty={(query.data?.data.length ?? 0) === 0}>{(query.data?.data ?? []).map(row => <article className="queue" key={String(row.id)}><Layer kind="observed"/><b>{String(row.item_type)}</b><small>{String(row.original_filename || row.note || row.text_content || row.source_url || "No note")}{row.size_bytes ? ` · ${String(row.size_bytes)} bytes` : ""}</small></article>)}</DataState></aside>
    </div>
  );
}

export function SourcesView({ id }: { id?: string }) {
  const client = useQueryClient();
  const [adapterType, setAdapterType] = useState("rss_atom");
  const list = useQuery({ queryKey: ["sources"], queryFn: () => api<Envelope<Row[]>>("/sources?limit=200") });
  const detail = useQuery({ queryKey: ["source", id], enabled: Boolean(id), queryFn: () => api<Envelope<Row>>(`/sources/${encodeURIComponent(id!)}`) });
  const create = useMutation({
    mutationFn: (payload: Row) => api<Envelope<Row>>("/sources", { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["sources"] }),
  });
  const patch = useMutation({
    mutationFn: (payload: Row) => api<Envelope<Row>>(`/sources/${encodeURIComponent(id!)}`, { method: "PATCH", body: JSON.stringify(payload) }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["source", id] });
      void client.invalidateQueries({ queryKey: ["sources"] });
      void client.invalidateQueries({ queryKey: ["automation-status"] });
    },
  });
  const fetchNow = useMutation({ mutationFn: () => api(`/sources/${encodeURIComponent(id!)}/fetch`, { method: "POST", body: "{}" }) });
  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const baseUrl = String(form.get("base_url") || "");
    const host = baseUrl ? new URL(baseUrl).hostname : "";
    const enabled = form.get("enabled") === "on";
    create.mutate({
      name: String(form.get("name")),
      adapter_type: adapterType,
      base_url: baseUrl || null,
      enabled,
      config: {
        record_type: String(form.get("record_type")),
        allowed_hosts: host ? [host] : [],
        interval_sec: Number(form.get("interval_sec")) || 3600,
        archive_raw_response: true,
      },
    });
  };
  if (id) {
    const row = detail.data?.data;
    const config = (row?.config as Row | undefined) ?? {};
    const remote = row?.adapter_type === "rss_atom" || row?.adapter_type === "generic_html_table";
    return <DataState loading={detail.isLoading} error={detail.error} empty={!row}>{row ? <section className="panel full"><Layer kind="observed"/><h2>{String(row.name)}</h2><p>{remote ? "This source is controlled by Celery Beat, not by this browser." : "Manual/static source; it is not fetched by the background scheduler."}</p><dl><dt>Adapter</dt><dd>{String(row.adapter_type)}</dd><dt>Last fetch UTC</dt><dd>{String(row.last_fetched_at ?? "never")}</dd><dt>Interval</dt><dd>{String(config.interval_sec ?? "—")} seconds</dd><dt>State</dt><dd>{row.enabled ? "Enabled for unattended collection" : "Paused"}</dd></dl>{remote ? <div className="toolbar"><button className="primary" disabled={patch.isPending} onClick={() => patch.mutate({ enabled: !row.enabled })}>{row.enabled ? "Pause background collection" : "Enable background collection"}</button><button disabled={!row.enabled || fetchNow.isPending} onClick={() => fetchNow.mutate()}>Fetch now</button></div> : null}{patch.error ? <p role="alert">{patch.error.message}</p> : null}{fetchNow.error ? <p role="alert">{fetchNow.error.message}</p> : null}{fetchNow.data ? <p role="status">Fetch queued; the worker continues independently of this page.</p> : null}<details><summary>Raw source configuration</summary><pre>{JSON.stringify(row, null, 2)}</pre></details></section> : null}</DataState>;
  }
  return (
    <div className="split">
      <section className="panel"><h2>Registered sources</h2><DataState loading={list.isLoading} error={list.error} empty={(list.data?.data.length ?? 0) === 0}><div className="cards">{(list.data?.data ?? []).map(row => <Link href={`/sources/${String(row.id)}`} key={String(row.id)}><Layer kind="observed"/><h2>{String(row.name)}</h2><p>{String(row.adapter_type)} · {row.enabled ? "enabled" : "disabled"}</p></Link>)}</div></DataState></section>
      <aside className="panel inbox-form"><h2>Register source</h2><form onSubmit={submit}><label>Name<input name="name" required/></label><label>Adapter<select name="adapter_type" value={adapterType} onChange={event => setAdapterType(event.target.value)}><option value="rss_atom">RSS/Atom</option><option value="generic_html_table">HTML table</option><option value="user_defined_static">Static (manual)</option></select></label><label>Record type<select name="record_type"><option>EVENT</option><option>FREQUENCY</option><option>RECEIVER</option></select></label><label>URL<input name="base_url" type="url" required={adapterType !== "user_defined_static"}/></label><label>Poll interval seconds<input name="interval_sec" type="number" min="300" max="604800" defaultValue="3600" required disabled={adapterType === "user_defined_static"}/></label><label><input name="enabled" type="checkbox" defaultChecked={adapterType !== "user_defined_static"} disabled={adapterType === "user_defined_static"}/> Start unattended collection after registration</label><button className="primary">Register source</button>{create.error ? <p role="alert">{create.error.message}</p> : null}</form><p className="policy">The source hostname is pinned at registration. Enable only sources whose terms and robots policy permit collection.</p></aside>
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
  const patch = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => api(`/capture/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["captures"] }); void client.invalidateQueries({ queryKey: ["automation-status"] }); },
  });
  const runNow = useMutation({
    mutationFn: (id: string) => api(`/capture/${encodeURIComponent(id)}/run-now`, { method: "POST", body: "{}" }),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["captures"] }); },
  });
  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    create.mutate({ receiver_id: form.get("receiver_id"), frequency_hz: Number(form.get("frequency_hz")), mode: form.get("mode"), schedule_utc: form.get("schedule_utc"), repetition: form.get("repetition") || null, capture_duration_sec: Number(form.get("capture_duration_sec")), maximum_storage_bytes: Number(form.get("maximum_storage_bytes")) || null, enabled: form.get("enabled") === "on", retention_policy: { days: Number(form.get("retention_days")) || 3650 } });
  };
  const configured = (receivers.data?.data ?? []).filter(row => Boolean((row.metadata_json as Row | undefined)?.capture_enabled) && Boolean((row.metadata_json as Row | undefined)?.capture_url_template));
  return <div className="split"><section className="panel inbox-form"><h2>Unattended receiver capture</h2><p>After a receiver transport and this schedule are explicitly enabled, Celery Beat triggers capture every 30 seconds without this page or browser being open.</p><form onSubmit={submit}><label>Receiver<select name="receiver_id" required>{configured.map(row => <option value={String(row.id)} key={String(row.id)}>{String(row.name)}</option>)}</select></label>{configured.length === 0 ? <p role="alert">No receiver has an enabled direct-audio transport. Open a receiver and configure one first.</p> : null}<label>Frequency Hz<input name="frequency_hz" type="number" required/></label><label>Mode<input name="mode" defaultValue="USB" required/></label><label>First UTC run (ISO timestamp or five-field cron)<input name="schedule_utc" defaultValue="*/15 * * * *" required/></label><label>Repeat cron (blank = one run)<input name="repetition" defaultValue="*/15 * * * *"/></label><label>Duration seconds<input name="capture_duration_sec" type="number" min="1" max="86400" defaultValue="60"/></label><label>Maximum bytes per capture<input name="maximum_storage_bytes" type="number" min="1" defaultValue="25000000"/></label><label>Retention days<input name="retention_days" type="number" min="1" defaultValue="3650"/></label><label><input name="enabled" type="checkbox" defaultChecked disabled={configured.length === 0}/> Enable schedule now</label><button className="primary" disabled={configured.length === 0 || create.isPending}>Create autonomous schedule</button>{create.error ? <p role="alert">{create.error.message}</p> : null}</form></section><aside className="panel"><h2>Capture jobs</h2><DataState loading={jobs.isLoading} error={jobs.error} empty={(jobs.data?.data.length ?? 0) === 0}>{(jobs.data?.data ?? []).map(row => <article className="queue" key={String(row.id)}><b>{String(row.frequency_hz)} Hz · {String(row.mode)}</b><small>{String(row.status)} · next {String(row.next_run_at ?? "—")}</small>{row.last_error ? <small role="alert">{String(row.last_error)}</small> : null}<div className="toolbar"><button onClick={() => patch.mutate({ id: String(row.id), enabled: !row.enabled })} disabled={patch.isPending}>{row.enabled ? "Pause" : "Enable"}</button><button onClick={() => runNow.mutate(String(row.id))} disabled={!row.enabled || runNow.isPending}>Run now</button></div></article>)}</DataState>{runNow.error ? <p role="alert">{runNow.error.message}</p> : null}</aside></div>;
}

export function EventsView({ id }: { id?: string }) {
  const client = useQueryClient();
  const list = useQuery({
    queryKey: ["events"],
    queryFn: () => api<Envelope<Row[]>>("/events?limit=500"),
  });
  const detail = useQuery({
    queryKey: ["event", id],
    enabled: Boolean(id),
    queryFn: () => api<Envelope<Row>>(`/events/${encodeURIComponent(id!)}`),
  });
  const create = useMutation({
    mutationFn: (payload: Row) => api<Envelope<Row>>("/events", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
    onSuccess: result => {
      void client.invalidateQueries({ queryKey: ["events"] });
      location.assign(`/events/${String(result.data.id)}`);
    },
  });
  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const started = String(form.get("started_at_utc") || "");
    create.mutate({
      title: String(form.get("title")),
      event_type: String(form.get("event_type")),
      started_at_utc: started ? new Date(started).toISOString() : null,
      country_codes: String(form.get("country_codes") || "").split(",").map(value => value.trim().toUpperCase()).filter(Boolean),
      description: String(form.get("description") || "") || null,
      source_url: String(form.get("source_url") || "") || null,
      source_name: String(form.get("source_name") || "") || null,
      confidence: Number(form.get("confidence") || 0.5),
      location: { text: String(form.get("location") || "") || null },
    });
  };
  if (id) {
    const row = detail.data?.data;
    return <DataState loading={detail.isLoading} error={detail.error} empty={!row}>{row ? <section className="panel full docs"><Layer kind="observed"/><h2>{String(row.title)}</h2><p>{String(row.event_type)} · {String(row.started_at_utc ?? "time unknown")}</p><p>{String(row.description ?? "")}</p><pre>{JSON.stringify(detail.data?.provenance ?? [], null, 2)}</pre><p className="policy">This is an external-event record. Association with an SDR observation does not establish causation.</p></section> : null}</DataState>;
  }
  return <div className="split"><section className="panel"><h2>External events</h2><DataState loading={list.isLoading} error={list.error} empty={(list.data?.data.length ?? 0) === 0}><div className="cards">{(list.data?.data ?? []).map(row => <Link href={`/events/${String(row.id)}`} key={String(row.id)}><Layer kind="observed"/><h2>{String(row.title)}</h2><p>{String(row.event_type)} · {String(row.started_at_utc ?? "time unknown")}</p></Link>)}</div></DataState></section><aside className="panel inbox-form"><h2>Register public event</h2><form onSubmit={submit}><label>Title<input name="title" required/></label><label>Type<input name="event_type" required/></label><label>UTC<input name="started_at_utc" type="datetime-local"/></label><label>Country codes<input name="country_codes" placeholder="FI, NO"/></label><label>Location text<input name="location"/></label><label>Source name<input name="source_name"/></label><label>Source URL<input name="source_url" type="url"/></label><label>Confidence<input name="confidence" type="number" min="0" max="1" step=".05" defaultValue=".5"/></label><label>Description<textarea name="description"/></label><button className="primary">Create observed event</button>{create.error ? <p role="alert">{create.error.message}</p> : null}</form></aside></div>;
}

export function SettingsView() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["settings"], queryFn: () => api<Envelope<Row[]>>("/settings?limit=200") });
  const active = useQuery({ queryKey: ["settings-active"], queryFn: () => api<Envelope<Row>>("/settings/active") });
  const [gamepad, setGamepad] = useState(
    () => typeof window !== "undefined" && localStorage.getItem("signal-index-gamepad") === "true",
  );
  const [passkeyStatus, setPasskeyStatus] = useState("");
  const secrets = useQuery({ queryKey: ["secret-status"], queryFn: () => api<Envelope<Row[]>>("/settings/secrets") });
  const secretSave = useMutation({
    mutationFn: (payload: Row) => api("/settings/secrets", { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["secret-status"] }),
  });
  const save = useMutation({
    mutationFn: (payload: Row) => api("/settings", { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["settings"] });
      void client.invalidateQueries({ queryKey: ["settings-active"] });
    },
  });
  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const raw = String(form.get("value"));
    let value: unknown = raw;
    try {
      value = JSON.parse(raw);
    } catch {
      value = raw;
    }
    save.mutate({ key: String(form.get("key")), value: { value } });
  };
  const keys = ["display.timezone","display.language","asr.model","asr.device","vad.threshold","processing.preset","session.merge_threshold","similarity.threshold","capture.maximum_storage_bytes","retention.days","embedding.model","receiver.default_id","watchlist.frequency_ids","source.schedule","ui.density","graph.layout"];
  return <div className="split"><section className="panel settings-view"><h2>Versioned configuration</h2><form onSubmit={submit}><label>Key<select name="key" required>{keys.map(key => <option key={key}>{key}</option>)}</select></label><label>JSON or scalar value<input name="value" required placeholder='e.g. "UTC", 0.55, ["id"]'/></label><button className="primary">Save new revision</button>{save.data ? <p role="status">Revision stored.</p> : null}{save.error ? <p role="alert">{save.error.message}</p> : null}</form><fieldset><legend>Device controls</legend><label><input type="checkbox" checked={gamepad} onChange={event => {
    const enabled = event.target.checked;
    setGamepad(enabled);
    localStorage.setItem("signal-index-gamepad", String(enabled));
    window.dispatchEvent(new Event("signal-gamepad-setting"));
  }}/>Enable optional Gamepad navigation on this device</label></fieldset><fieldset><legend>Encrypted secrets</legend><form onSubmit={event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    secretSave.mutate({ key: String(form.get("secret_key")), value: String(form.get("secret_value")) });
    event.currentTarget.reset();
  }}><label>Secret<select name="secret_key"><option value="local_llm.api_key">Local LLM API key</option><option value="tool_api.key">Tool API key</option></select></label><label>New value<input type="password" name="secret_value" autoComplete="new-password" required/></label><button>Encrypt and rotate</button></form><pre>{JSON.stringify(secrets.data?.data ?? [], null, 2)}</pre></fieldset><fieldset><legend>Optional passkey</legend><button type="button" onClick={() => {
    setPasskeyStatus("Waiting for authenticator…");
    void registerPasskey("Signal Index device").then(() => setPasskeyStatus("Passkey registered.")).catch(error => setPasskeyStatus(error instanceof Error ? error.message : "Passkey registration failed"));
  }}>Register this device</button>{passkeyStatus ? <p role="status">{passkeyStatus}</p> : null}</fieldset><h3>Active values</h3><pre>{JSON.stringify(active.data?.data ?? {}, null, 2)}</pre></section><aside className="panel"><h2>Revision history</h2><DataState loading={query.isLoading} error={query.error} empty={(query.data?.data.length ?? 0) === 0}><pre>{JSON.stringify(query.data?.data ?? [], null, 2)}</pre></DataState></aside></div>;
}

export function ApiDocsView() {
  const query = useQuery({ queryKey: ["capabilities"], queryFn: () => api<Envelope<Row>>("/capabilities") });
  return <section className="panel full docs"><h2>Local LLM tool API</h2><p>The live response below is the authority; unavailable features are not advertised as implemented.</p><DataState loading={query.isLoading} error={query.error} empty={!query.data}><pre>{JSON.stringify(query.data, null, 2)}</pre></DataState><a href={`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1"}`.replace("/api/v1", "/docs")} target="_blank" rel="noreferrer">OpenAPI documentation</a></section>;
}

export function LoginView() {
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");
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
  return <main className="login"><section><span className="kicker">PRIVATE WORKSPACE</span><h1>Signal Index</h1><p>Structure observations. Preserve evidence. Test hypotheses.</p><form onSubmit={submit}><label>Email<input name="email" type="email" autoComplete="username" required value={email} onChange={event => setEmail(event.target.value)}/></label><label>Password<input name="password" type="password" autoComplete="current-password" required/></label><button className="primary">Sign in</button><button type="button" disabled={!email.trim()} onClick={() => {
    setError("");
    void loginWithPasskey(email).then(() => location.assign("/dashboard")).catch(passkeyError => setError(passkeyError instanceof Error ? passkeyError.message : "Passkey login failed"));
  }}>Sign in with passkey</button>{error ? <p role="alert">{error}</p> : null}</form><small>Public registration disabled · secure session cookie · optional WebAuthn</small></section></main>;
}
