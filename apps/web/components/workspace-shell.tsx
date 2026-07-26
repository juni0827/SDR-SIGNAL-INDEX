"use client";

import {
  Activity,
  Antenna,
  Bell,
  BookOpen,
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

import { syncMutations } from "@/lib/offline";
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
  if (path.startsWith("/sources")) return ["Source adapters", "INGESTION / SOURCES"];
  if (path.startsWith("/capture")) return ["Capture scheduler", "INGESTION / WATCHLIST"];
  if (path.startsWith("/settings")) return ["Settings", "SYSTEM / CONFIGURATION"];
  return ["Tool API", "LOCAL LLM / ACCESS"];
}

function CommandPalette({ close }: { close(): void }) {
  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label="Command palette" onMouseDown={close}>
      <section onMouseDown={event => event.stopPropagation()}>
        <header><Search/><input autoFocus aria-label="Command search" placeholder="Type a command…"/><button onClick={close}><X/></button></header>
        {commands.map(([label, href]) => <Link key={href} href={href} onClick={close}>{label}</Link>)}
      </section>
    </div>
  );
}

export function WorkspaceShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [heading, eyebrow] = pageTitle(path);
  const { sidebar, command, setSidebar, setCommand } = useUI();
  const [online, setOnline] = useState(() => typeof navigator === "undefined" || navigator.onLine);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommand(!command);
      }
      if (event.key === "Escape") setCommand(false);
    };
    const on = () => { setOnline(true); void syncMutations(); };
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
          <button aria-label="Notifications"><Bell/></button>
          <Link className="primary" href="/inbox"><Upload/>Add</Link>
        </header>
        <main id="main" data-testid="main-content">{children}</main>
        <nav className="bottom" aria-label="Mobile navigation">{nav.slice(0, 5).map(([href, label, Icon]) => <Link key={href} href={href}><Icon/><span>{label}</span></Link>)}</nav>
      </section>
      {command ? <CommandPalette close={() => setCommand(false)}/> : null}
    </div>
  );
}
