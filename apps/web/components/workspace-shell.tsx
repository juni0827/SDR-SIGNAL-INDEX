"use client";

import {
  Activity,
  Antenna,
  Bell,
  BookOpen,
  CalendarDays,
  Clock3,
  Database,
  FileAudio,
  GitBranch,
  Inbox,
  LayoutDashboard,
  MapPinned,
  Menu,
  Radio,
  Search,
  Settings,
  Upload,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, type Envelope } from "@/lib/api";
import { offlineQueueStatus, syncMutations } from "@/lib/offline";
import { useUI } from "@/lib/store";

const nav = [
  ["/dashboard", "Dashboard", LayoutDashboard],
  ["/inbox", "Inbox", Inbox],
  ["/frequencies", "Spectrum", Activity],
  ["/receivers", "Receivers", MapPinned],
  ["/recordings", "Recordings", FileAudio],
  ["/sessions", "Sessions", Radio],
  ["/timeline", "Timeline", Clock3],
  ["/graph", "Relations", GitBranch],
  ["/hypotheses", "Hypotheses", BookOpen],
  ["/events", "Events", CalendarDays],
  ["/sources", "Sources", Database],
  ["/capture", "Capture", Antenna],
] as const;

const commands = [
  ["Open 4.625 MHz", "/frequencies/4625000"],
  ["Open sessions", "/sessions"],
  ["Create hypothesis", "/hypotheses/new"],
  ["Upload recording", "/inbox"],
  ["Start capture", "/capture"],
  ["Show timeline", "/timeline"],
  ["Create context bundle", "/api-docs"],
  ["Compare sessions", "/graph"],
  ["Search callsign", "/sessions"],
  ["Search number group", "/sessions"],
  ["Export data", "/api-docs"],
] as const;

function Mark() {
  return <div className="mark" aria-hidden="true">{[1, 2, 3, 4, 5].map(value => <i key={value}/>)}</div>;
}

function pageTitle(path: string): [string, string] {
  if (path.startsWith("/dashboard")) return ["Observation dashboard", "OPERATIONS / LIVE INDEX"];
  if (path.startsWith("/inbox")) return ["Universal inbox", "CAPTURE / UNCLASSIFIED"];
  if (path.startsWith("/frequencies")) return ["Spectrum explorer", "INDEX / FREQUENCIES"];
  if (path.startsWith("/receivers")) return ["Receiver directory", "SOURCES / RECEIVERS"];
  if (path.startsWith("/recordings")) return ["Recordings", "EVIDENCE / RECORDINGS"];
  if (path.startsWith("/segments")) return ["Audio review", "EVIDENCE / SEGMENT"];
  if (path.startsWith("/sessions")) return ["Session explorer", "INDEX / SESSIONS"];
  if (path.startsWith("/timeline")) return ["Observation timeline", "ANALYSIS / TEMPORAL"];
  if (path.startsWith("/graph")) return ["Relationship graph", "ANALYSIS / RELATIONS"];
  if (path.startsWith("/hypotheses")) return ["Hypothesis notebook", "ANALYSIS / NOTEBOOK"];
  if (path.startsWith("/events")) return ["External events", "EVIDENCE / PUBLIC EVENTS"];
  if (path.startsWith("/sources")) return ["Source adapters", "INGESTION / SOURCES"];
  if (path.startsWith("/capture")) return ["Capture scheduler", "INGESTION / WATCHLIST"];
  if (path.startsWith("/settings")) return ["Settings", "SYSTEM / CONFIGURATION"];
  return ["Tool API", "LOCAL LLM / ACCESS"];
}

function CommandPalette({ close, path }: { close(): void; path: string }) {
  const [term, setTerm] = useState("");
  const results = useQuery({
    queryKey: ["command-search", term],
    enabled: term.trim().length >= 2,
    queryFn: () => api<Envelope<Array<Record<string, unknown>>>>("/search/sessions", {
      method: "POST",
      body: JSON.stringify({ text: term.trim(), limit: 8 }),
    }),
  });
  const normalized = term.trim().toLowerCase();
  const filtered = commands.filter(([label]) => label.toLowerCase().includes(normalized));
  const frequency = Number(term.replaceAll(/[^0-9.]/g, ""));
  const frequencyHref = Number.isFinite(frequency) && frequency > 0
    ? `/frequencies/${Math.round(frequency < 100_000 ? frequency * 1_000 : frequency)}`
    : null;
  const markReviewed = async () => {
    const match = path.match(/^\/segments\/([^/]+)/);
    if (!match) return;
    await api(`/segments/${encodeURIComponent(match[1])}/review`, {
      method: "PATCH",
      body: JSON.stringify({ reviewed: true }),
    });
    close();
  };
  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label="Command palette" onMouseDown={close}>
      <section onMouseDown={event => event.stopPropagation()}>
        <header><Search/><input autoFocus aria-label="Command search" placeholder="Command, session, callsign, number, frequency…" value={term} onChange={event => setTerm(event.target.value)}/><button onClick={close}><X/></button></header>
        {filtered.map(([label, href]) => <Link key={label} href={href} onClick={close}>{label}</Link>)}
        {frequencyHref ? <Link href={frequencyHref} onClick={close}>Open frequency {term}</Link> : null}
        {path.startsWith("/segments/") ? <button onClick={() => void markReviewed()}>Mark current segment reviewed</button> : null}
        {(results.data?.data ?? []).map(row => <Link key={String(row.id)} href={`/sessions/${String(row.id)}`} onClick={close}>Session · {String(row.title || row.id)} · {String(row.primary_frequency_hz)} Hz</Link>)}
      </section>
    </div>
  );
}

export function WorkspaceShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [heading, eyebrow] = pageTitle(path);
  const { sidebar, command, setSidebar, setCommand } = useUI();
  const [online, setOnline] = useState(() => typeof navigator === "undefined" || navigator.onLine);
  const [gamepad, setGamepad] = useState(false);
  const [offlineQueue, setOfflineQueue] = useState({queued: 0, conflicts: 0});
  useEffect(() => {
    let active = true;
    const refresh = async () => {
      const status = await offlineQueueStatus();
      if (active) setOfflineQueue(status);
    };
    void refresh();
    const interval = window.setInterval(() => void refresh(), 10_000);
    window.addEventListener("signal-offline-queue", refresh);
    return () => {
      active = false;
      window.clearInterval(interval);
      window.removeEventListener("signal-offline-queue", refresh);
    };
  }, []);
  useEffect(() => {
    const refresh = () => setGamepad(localStorage.getItem("signal-index-gamepad") === "true");
    refresh();
    window.addEventListener("signal-gamepad-setting", refresh);
    return () => window.removeEventListener("signal-gamepad-setting", refresh);
  }, []);
  useEffect(() => {
    if (!gamepad || !("getGamepads" in navigator)) return;
    let frame = 0;
    let lastMove = 0;
    const poll = (timestamp: number) => {
      const controller = Array.from(navigator.getGamepads()).find(Boolean);
      const horizontal = controller?.axes[0] ?? 0;
      const vertical = controller?.axes[1] ?? 0;
      if (controller && timestamp - lastMove > 260 && (Math.abs(horizontal) > 0.65 || Math.abs(vertical) > 0.65)) {
        const focusable = Array.from(document.querySelectorAll<HTMLElement>("a[href],button:not(:disabled),input,select,textarea")).filter(element => element.offsetParent !== null);
        const current = Math.max(0, focusable.indexOf(document.activeElement as HTMLElement));
        const direction = horizontal < -0.65 || vertical < -0.65 ? -1 : 1;
        focusable[(current + direction + focusable.length) % focusable.length]?.focus();
        lastMove = timestamp;
      }
      frame = requestAnimationFrame(poll);
    };
    frame = requestAnimationFrame(poll);
    return () => cancelAnimationFrame(frame);
  }, [gamepad]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommand(!command);
      }
      if (event.key === "Escape") setCommand(false);
    };
    const on = () => {
      setOnline(true);
      void syncMutations()
        .then(() => offlineQueueStatus())
        .then(setOfflineQueue)
        .catch((error: unknown) => console.error("offline_sync_failed", error));
    };
    const off = () => setOnline(false);
    window.addEventListener("keydown", key);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("keydown", key);
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, [command, setCommand]);
  return (
    <div className="frame">
      <a href="#main" className="skip">Skip to content</a>
      <aside className={`sidebar ${sidebar ? "open" : ""}`} role="navigation" aria-label="Primary navigation">
        <header><Mark/><b>Signal <em>Index</em></b><button onClick={() => setSidebar(false)} aria-label="Close navigation"><X/></button></header>
        <nav>{nav.map(([href, label, Icon]) => <Link key={href} href={href} aria-current={path.startsWith(href) ? "page" : undefined} className={path.startsWith(href) ? "active" : ""} data-testid={`nav-${label.toLowerCase()}`}><Icon/><span>{label}</span></Link>)}</nav>
        <section className="system"><b><i/> Connected status is verified per page</b><span>API · worker · storage</span><small>UTC index · private bucket</small></section>
        <footer><span>J</span><div><b>Owner</b><small>Local workspace</small></div><Link href="/settings" aria-label="Settings"><Settings/></Link></footer>
      </aside>
      <section className="workspace">
        <header className="topbar">
          <button className="mobile" aria-label="Open navigation" onClick={() => setSidebar(true)}><Menu/></button>
          <div><span>{eyebrow}</span><h1>{heading}</h1></div>
          <button className="command" onClick={() => setCommand(true)} data-testid="command-trigger"><Search/><span>Search records or run a command</span><kbd>Ctrl K</kbd></button>
          <span className={`live ${online ? "" : "offline"}`}><i/>{online ? "Online" : "Offline"}</span>
          {offlineQueue.queued > 0 || offlineQueue.conflicts > 0 ? (
            <Link
              href="/inbox"
              className={`sync-status ${offlineQueue.conflicts > 0 ? "conflict" : ""}`}
              aria-label={`${offlineQueue.queued} queued offline changes, ${offlineQueue.conflicts} sync conflicts`}
              data-testid="offline-sync-status"
            >
              {offlineQueue.conflicts > 0 ? `${offlineQueue.conflicts} conflict` : `${offlineQueue.queued} queued`}
            </Link>
          ) : null}
          <button aria-label="Notifications"><Bell/></button>
          <Link className="primary" href="/inbox"><Upload/>Add</Link>
        </header>
        <main id="main" data-testid="main-content">{children}</main>
        <nav className="bottom" aria-label="Mobile navigation">{nav.slice(0, 5).map(([href, label, Icon]) => <Link key={href} href={href}><Icon/><span>{label}</span></Link>)}</nav>
      </section>
      {command ? <CommandPalette close={() => setCommand(false)} path={path}/> : null}
    </div>
  );
}
