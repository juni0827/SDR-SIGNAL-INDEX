"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import {
  Activity, Antenna, AudioLines, Bell, BookOpen, Braces, ChevronRight, Clock3,
  Database, Download, FileAudio, Filter, GitBranch, Headphones, Inbox, LayoutDashboard,
  MapPinned, Menu, Network, Pause, Play, Radio, Search, Settings, ShieldCheck,
  SlidersHorizontal, Sparkles, Upload, X,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, type Envelope } from "@/lib/api";
import { queueOffline, syncMutations } from "@/lib/offline";
import { useUI } from "@/lib/store";

const GraphCanvas = dynamic(() => import("./graph-canvas").then((value) => value.GraphCanvas), {ssr: false});

type SessionRow = {
  id: string; frequency: string; started: string; className: string;
  callsign: string; numbers: string; confidence: number; status: string;
};
const sampleSessions: SessionRow[] = [
  {id:"S-81A2",frequency:"4.625 MHz",started:"2026-07-25 18:42:11",className:"VOICE",callsign:"KILO 72",numbers:"281 · 46 · 992",confidence:.87,status:"UNREVIEWED"},
  {id:"S-819F",frequency:"8.992 MHz",started:"2026-07-25 16:06:49",className:"DIGITAL",callsign:"—",numbers:"—",confidence:.91,status:"REVIEWED"},
  {id:"S-818B",frequency:"11.175 MHz",started:"2026-07-25 13:25:02",className:"VOICE",callsign:"SIERRA 14",numbers:"552 · 08",confidence:.64,status:"UNREVIEWED"},
  {id:"S-816C",frequency:"5.455 MHz",started:"2026-07-25 09:12:33",className:"TONE",callsign:"—",numbers:"—",confidence:.78,status:"CONFIRMED"},
];
const nav = [
  ["/dashboard","Dashboard",LayoutDashboard], ["/inbox","Inbox",Inbox],
  ["/frequencies","Spectrum",Activity], ["/receivers","Receivers",MapPinned],
  ["/recordings","Recordings",FileAudio], ["/sessions","Sessions",Radio],
  ["/timeline","Timeline",Clock3], ["/graph","Relations",GitBranch],
  ["/hypotheses","Hypotheses",BookOpen], ["/sources","Sources",Database],
  ["/capture","Capture",Antenna],
] as const;
const layers = {
  observed: ["Observed","observed"], machine: ["Machine-generated","machine"],
  corrected: ["User-corrected","corrected"], interpretation: ["User interpretation","interpretation"],
  llm: ["Local LLM hypothesis","llm"], confirmed: ["Confirmed","confirmed"],
} as const;

function Layer({kind}: {kind: keyof typeof layers}) {
  return <span className={`layer ${layers[kind][1]}`}>{layers[kind][0]}</span>;
}

function Mark() {
  return <div className="mark" aria-hidden="true">{[1,2,3,4,5].map((n)=><i key={n}/>)}</div>;
}

function Shell({path, title, eyebrow, children}: {path:string;title:string;eyebrow:string;children:React.ReactNode}) {
  const {sidebar, command, setSidebar, setCommand} = useUI();
  const [online, setOnline] = useState(() => typeof navigator === "undefined" || navigator.onLine);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {event.preventDefault();setCommand(!command);}
      if (event.key === "Escape") setCommand(false);
    };
    const on = () => {setOnline(true);void syncMutations();};
    const off = () => setOnline(false);
    window.addEventListener("keydown", key);window.addEventListener("online", on);window.addEventListener("offline", off);
    return () => {window.removeEventListener("keydown", key);window.removeEventListener("online", on);window.removeEventListener("offline", off);};
  }, [command,setCommand]);
  return <div className="frame">
    <a href="#main" className="skip">Skip to content</a>
    <aside className={`sidebar ${sidebar?"open":""}`} aria-label="Primary navigation">
      <header><Mark/><b>Signal <em>Index</em></b><button onClick={()=>setSidebar(false)} aria-label="Close navigation"><X/></button></header>
      <nav>{nav.map(([href,label,Icon])=><Link key={href} href={href} aria-current={path.startsWith(href)?"page":undefined} className={path.startsWith(href)?"active":""} data-testid={`nav-${label.toLowerCase()}`}><Icon/><span>{label}</span></Link>)}</nav>
      <section className="system"><b><i/> System nominal</b><span>API · worker · storage</span><small>UTC index · private bucket</small></section>
      <footer><span>J</span><div><b>Owner</b><small>Local workspace</small></div><Settings/></footer>
    </aside>
    <section className="workspace">
      <header className="topbar">
        <button className="mobile" aria-label="Open navigation" onClick={()=>setSidebar(true)}><Menu/></button>
        <div><span>{eyebrow}</span><h1>{title}</h1></div>
        <button className="command" onClick={()=>setCommand(true)} data-testid="command-trigger"><Search/><span>Search records or run a command</span><kbd>Ctrl K</kbd></button>
        <span className={`live ${online?"":"offline"}`}><i/>{online?"Live":"Offline"}</span>
        <button aria-label="Notifications"><Bell/></button><Link className="primary" href="/inbox"><Upload/>Add</Link>
      </header>
      <main id="main" data-testid="main-content">{children}</main>
      <nav className="bottom" aria-label="Mobile navigation">{nav.slice(0,5).map(([href,label,Icon])=><Link key={href} href={href}><Icon/><span>{label}</span></Link>)}</nav>
    </section>
    {command?<CommandPalette close={()=>setCommand(false)}/>:null}
  </div>;
}

function CommandPalette({close}:{close:()=>void}) {
  const commands = [["Open 4.625 MHz","/frequencies/4625000"],["Open sessions","/sessions"],["Create hypothesis","/hypotheses/new"],["Upload recording","/inbox"],["Start capture","/capture"],["Show timeline","/timeline"],["Create context bundle","/api-docs"]];
  return <div className="modal" role="dialog" aria-modal="true" aria-label="Command palette" onMouseDown={close}><section onMouseDown={(e)=>e.stopPropagation()}><header><Search/><input autoFocus placeholder="Type a command…"/><button onClick={close}><X/></button></header>{commands.map(([label,href])=><Link key={label} href={href} onClick={close}><ChevronRight/>{label}</Link>)}</section></div>;
}

function Dashboard() {
  return <div className="dashboard">
    <section className="stats">{[["Sessions · 24h","47","+18%"],["Active frequencies","12","+3"],["Unreviewed","31","needs review"],["Worker queue","4","2 running"]].map((x)=><article key={x[0]}><span>{x[0]}</span><b>{x[1]}</b><small>{x[2]}</small></article>)}</section>
    <section className="panel activity-panel"><header><div><span className="kicker">FREQUENCY ACTIVITY</span><h2>Observed activity against baseline</h2></div><button><SlidersHorizontal/>24 hours</button></header><ActivityChart/></section>
    <section className="panel recent"><header><div><span className="kicker">RECENT SESSIONS</span><h2>Indexed transmissions</h2></div><Link href="/sessions">View all</Link></header><SessionTable rows={sampleSessions.slice(0,3)}/></section>
    <aside className="panel watch"><span className="kicker">WATCHLIST</span><h2>Priority frequencies</h2>{[["4.625 MHz","VOICE · 19"],["8.992 MHz","DIGITAL · 8"],["11.175 MHz","VOICE · 6"]].map(x=><Link href="/frequencies" key={x[0]}><Activity/><div><b>{x[0]}</b><small>{x[1]} sessions</small></div><ChevronRight/></Link>)}</aside>
    <aside className="panel entities"><span className="kicker">REPEATED ENTITIES</span><h2>Last seven days</h2><p><Layer kind="machine"/><b>KILO 72</b><span>14 observations</span></p><p><Layer kind="machine"/><b>281 · 46</b><span>9 observations</span></p></aside>
    <aside className="panel failures"><span className="kicker">ATTENTION</span><h2>Processing failures</h2><p><i/>R-0014 · FFmpeg probe failed</p><p><i/>Source event-feed · timeout</p></aside>
  </div>;
}

function ActivityChart() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let chart: import("echarts").ECharts | undefined;
    let disposed = false;
    void import("echarts").then((echarts) => {
      if (!ref.current || disposed) return;
      chart = echarts.init(ref.current);
      chart.setOption({grid:{left:30,right:12,top:10,bottom:25},xAxis:{type:"category",data:["00","03","06","09","12","15","18","21"]},yAxis:{type:"value"},series:[{type:"line",smooth:true,data:[3,2,5,7,6,11,19,8],lineStyle:{color:"#67e6a0"},areaStyle:{color:"rgba(103,230,160,.08)"}},{type:"line",data:[4,4,5,6,7,8,9,7],lineStyle:{color:"#d4a948",type:"dashed"}}]});
    });
    return () => {disposed=true;chart?.dispose();};
  },[]);
  return <div className="chart" ref={ref} aria-label="Frequency activity chart"/>;
}

function SessionTable({rows}:{rows:SessionRow[]}) {
  return <div className="table-scroll"><table data-testid="session-table"><thead><tr><th>Session</th><th>Frequency</th><th>Started UTC</th><th>Class</th><th>Entities</th><th>Confidence</th><th>Status</th></tr></thead><tbody>{rows.map(row=><tr key={row.id}><td><Link href={`/sessions/${row.id}`}>{row.id}</Link></td><td>{row.frequency}</td><td>{row.started}</td><td><span className={`class ${row.className.toLowerCase()}`}>{row.className}</span></td><td><b>{row.callsign}</b><small>{row.numbers}</small></td><td><meter min="0" max="1" value={row.confidence}/>{Math.round(row.confidence*100)}%</td><td>{row.status}</td></tr>)}</tbody></table></div>;
}

function Sessions() {
  const [text,setText]=useState("");
  const query=useQuery({queryKey:["sessions",text],queryFn:()=>api<Envelope<Array<Record<string,unknown>>>>("/search/sessions",{method:"POST",body:JSON.stringify({text:text||null,limit:50})})});
  const rows:SessionRow[]=(query.data?.data??[]).map(row=>({id:String(row.id),frequency:`${(Number(row.primary_frequency_hz)/1e6).toFixed(3)} MHz`,started:String(row.start_at_utc).replace("T"," ").slice(0,19),className:String(row.category??"UNKNOWN"),callsign:Array.isArray(row.callsigns)?row.callsigns.join(", ")||"—":"—",numbers:Array.isArray(row.number_groups)?row.number_groups.join(" · ")||"—":"—",confidence:Number(row.confidence),status:String(row.status)}));
  return <section className="panel full"><div className="toolbar"><label><Search/><input data-testid="session-search" aria-label="Search sessions" value={text} onChange={e=>setText(e.target.value)} placeholder="Callsign, number group, transcript…"/></label><button><Filter/>Structured filters</button><button>UTC · 90 days</button><button>Copy query JSON</button></div><div className="query"><Braces/><code>{JSON.stringify({text:text||null,limit:50,order:"desc"})}</code></div>{query.isError?<p className="notice">API unavailable — deterministic seed preview shown.</p>:null}<SessionTable rows={rows.length?rows:sampleSessions}/></section>;
}

function Spectrum() {
  return <div className="split"><section className="panel spectrum"><header><div><span className="kicker">HF OVERVIEW</span><h2>1.8–30 MHz activity</h2></div><button><Filter/>Filters</button></header><div className="bands">{Array.from({length:90},(_,i)=><i key={i} style={{height:`${10+(i*37)%80}%`}}/>)}<Link href="/frequencies/4625000" style={{left:"10%"}}><b>4.625</b><span>19 sessions</span></Link></div>{["Voice","Digital","Tone","Unknown"].map((name,r)=><div className="heat" key={name}><span>{name}</span>{Array.from({length:36},(_,i)=><i key={i} style={{opacity:((i+1)*(r+2)%10)/10}}/>)}</div>)}</section><aside className="panel inspector"><span className="kicker">SELECTED FREQUENCY</span><h2>4.625 MHz</h2><Layer kind="observed"/><dl><dt>Mode</dt><dd>USB</dd><dt>Category</dt><dd>Utility</dd><dt>Sessions</dt><dd>47 / 90d</dd><dt>Receivers</dt><dd>3</dd></dl><button className="primary"><Headphones/>Latest session</button><button><Antenna/>Receiver tuning link</button></aside></div>;
}

function ReceiverMap() {
  const ref=useRef<HTMLDivElement>(null);
  useEffect(()=>{let map:import("maplibre-gl").Map|undefined;let disposed=false;void import("maplibre-gl").then(({default:maplibre})=>{if(disposed||!ref.current)return;map=new maplibre.Map({container:ref.current,center:[25,35],zoom:1.2,style:{version:8,sources:{},layers:[{id:"background",type:"background",paint:{"background-color":"#081311"}}]}});for(const [lng,lat,name] of [[5.2,52.1,"NL-01"],[-76.5,44.2,"CA-02"],[37.6,55.7,"RU-03"],[139.7,35.6,"JP-04"],[18.4,-33.9,"ZA-05"]] as [number,number,string][]){const el=document.createElement("button");el.className="receiver-dot";el.ariaLabel=`${name} receiver location`;new maplibre.Marker({element:el}).setLngLat([lng,lat]).addTo(map);}});return()=>{disposed=true;map?.remove();};},[]);
  return <div ref={ref} className="map" data-testid="receiver-map" aria-label="Receiver locations map"/>;
}
function Receivers(){return <div className="split"><section className="panel"><p className="map-note"><MapPinned/>Receiver locations only. Transmitter positions are not inferred.</p><ReceiverMap/></section><aside className="panel receiver-list"><span className="kicker">PUBLIC RECEIVERS</span><h2>5 registered</h2>{[["NL-01 · Utrecht","KIWISDR · ONLINE"],["CA-02 · Ontario","WEBSDR · ONLINE"],["RU-03 · Moscow","KIWISDR · OFFLINE"],["JP-04 · Tokyo","OTHER · ONLINE"],["ZA-05 · Cape Town","KIWISDR · UNKNOWN"]].map(x=><Link href="/receivers/demo" key={x[0]}><i/><div><b>{x[0]}</b><span>{x[1]}</span></div></Link>)}</aside></div>;}

function Waveform(){return <div className="waveform">{Array.from({length:140},(_,i)=><i key={i} style={{height:`${10+Math.abs(Math.sin(i*.43))*78}%`}}/>)}<span/><em>VOICE · 00:16.2–00:48.9</em></div>;}
function AudioReview({segmentId}:{segmentId?:string}){
  const [playing,setPlaying]=useState(false);const [text,setText]=useState("Kilo seven two, message follows. Two eight one, four six, nine nine two. End.");const [saved,setSaved]=useState(false);
  const save=async()=>{if(segmentId)await api(`/segments/${encodeURIComponent(segmentId)}/transcripts/correct`,{method:"POST",body:JSON.stringify({text,language:"en",make_preferred:true})});setSaved(true);};
  return <div className="review" data-testid="audio-review"><section className="panel audio"><header><div><span className="kicker">ORIGINAL PRESERVED · R-0021</span><h2>4.625 MHz · USB</h2></div><Layer kind="observed"/></header><div className="tabs"><button>Processed · voice 300–3,000 Hz</button><button>Original</button><button>Noise preview</button></div><Waveform/><div className="spectrogram">{Array.from({length:100},(_,i)=><i key={i} style={{left:`${i}%`,top:`${(i*37)%90}%`}}/>)}</div><footer className="transport"><button onClick={()=>setPlaying(!playing)}>{playing?<Pause/>:<Play/>}</button><b>00:27.8 / 01:00.0</b><button>0.75×</button><button>1×</button><button>1.25×</button><label>Gain<input type="range"/></label><button>Loop</button></footer><div className="segment-actions"><button>Split</button><button>Merge</button><button>Rerun VAD</button><b>3 voice · 1 noise</b></div></section><section className="panel transcript"><header><div><span className="kicker">TRANSCRIPT CANDIDATES</span><h2>Segment SG-210</h2></div><b>84%</b></header><div className="tabs"><button>Preferred · corrected</button><button>ASR · large-v3</button></div><Layer kind="corrected"/><textarea data-testid="transcript-editor" aria-label="Transcript correction" value={text} onChange={e=>setText(e.target.value)}/><div className="entities"><span>EXTRACTED</span><button>CALLSIGN · KILO 72</button><button>NUMBER · 281</button><button>NUMBER · 46</button><button>NUMBER · 992</button></div><label>Annotation<textarea placeholder="Evidence-linked note…"/></label><footer><button>Save alternative</button><button className="primary" data-testid="save-transcript" onClick={()=>void save()}>Save corrected & preferred</button></footer>{saved?<p role="status">Correction saved; machine candidate preserved.</p>:null}</section></div>;
}

function Timeline(){return <section className="panel full"><div className="toolbar"><button>UTC · 25 Jul 2026</button><button>Overlay period</button><button>Compare selection</button><button>Layers · 7</button></div><div className="timeline" data-testid="timeline">{["Frequency activity","Sessions","Callsigns","Number groups","Receiver observations","External events","Annotations","Hypotheses"].map((name,r)=><div key={name}><span>{name}</span><section>{[10+r*3,38+r,72-r].map((x,i)=><button key={i} style={{left:`${x}%`,width:`${4+(r%3)}%`}} aria-label={`${name} item ${i+1}`}/>)}</section></div>)}</div><footer className="timeline-foot">Selection 09:00–11:52 UTC · Local 18:00–20:52 KST · delta 02:52:18</footer></section>;}
function Graph(){return <div className="graph"><section className="panel toolbar"><button>Node types · 6</button><button>Relations · all</button><label>Min confidence<input type="range"/></label><button><Download/>PNG / SVG / JSON</button></section><section className="panel graph-canvas" data-testid="relation-graph"><GraphCanvas/></section><aside className="panel inspector"><span className="kicker">EDGE EVIDENCE</span><h2>Temporally precedes</h2><Layer kind="machine"/><dl><dt>Confidence</dt><dd>0.68</dd><dt>Delta</dt><dd>+4h 18m</dd><dt>Causal claim</dt><dd>No</dd><dt>Evidence</dt><dd>2</dd></dl><p>Time order is not treated as causation.</p></aside></div>;}
function Hypotheses({detail=false}:{detail?:boolean}){if(detail)return <div className="notebook"><section className="panel"><span className="kicker">H-014 · USER INTERPRETATION</span><h2>Daily 4.625 MHz format recurrence</h2><Layer kind="interpretation"/><textarea defaultValue="A structurally similar voice session occurs near 18:40 UTC across multiple observation days."/><div className="evidence"><section><h3>Supporting · 8</h3><button>S-81A2 · observed</button><button>S-812E · observed</button></section><section><h3>Contradicting · 1</h3><button>S-792A · timing deviation</button></section></div><button className="primary">Update evaluation</button></section><aside className="panel"><span className="kicker">HISTORY</span><p>ACTIVE · 0.72 · User</p><p>DRAFT · Local LLM</p><button>Create context bundle</button></aside></div>;return <section className="panel full"><div className="toolbar"><label><Search/><input placeholder="Search hypotheses…"/></label><Link className="primary" href="/hypotheses/new"><Sparkles/>New hypothesis</Link></div><div className="cards">{["Daily 4.625 MHz format recurrence","KILO 72 across receiver regions","Number group 281 event relationship"].map((x,i)=><Link href={`/hypotheses/H-0${14-i}`} key={x}><Layer kind={i===1?"llm":"interpretation"}/><h2>{x}</h2><p>{i===0?"8 supporting · 1 contradicting":"Unresolved evidence remains"}</p></Link>)}</div></section>;}

function InboxView(){
  const [type,setType]=useState("audio");const [status,setStatus]=useState("");
  const submit=async(event:React.FormEvent<HTMLFormElement>)=>{event.preventDefault();const form=new FormData(event.currentTarget);const payload={item_type:type==="data"?"json":type,frequency_hz:Number(String(form.get("frequency_hz")??"").replace(/[^\d]/g,""))||null,mode:String(form.get("mode")??"USB"),observed_at_utc:new Date().toISOString(),note:String(form.get("note")??""),tags:String(form.get("tags")??"").split(",").filter(Boolean)};try{if(!navigator.onLine)await queueOffline("inbox",payload);else{const file=form.get("file");if(type==="audio"&&file instanceof File&&file.size){const upload=new FormData();upload.set("file",file);upload.set("metadata",JSON.stringify({frequency_hz:payload.frequency_hz??0,mode:payload.mode,started_at_utc:payload.observed_at_utc,source_type:"MANUAL_UPLOAD",bandpass_preset:"VOICE"}));await api("/recordings/upload",{method:"POST",body:upload});}else await api("/inbox",{method:"POST",body:JSON.stringify(payload)});}setStatus("Saved with provenance.");}catch(error){console.error("inbox_save_failed",error);setStatus("API unavailable; retry or use offline mode.");}};
  return <div className="split inbox-page"><section className="panel inbox-form"><span className="kicker">UNIVERSAL INBOX</span><h2>Capture now, classify later</h2><div className="types">{[["audio",AudioLines],["text",Braces],["url",Network],["image",FileAudio],["pdf",BookOpen],["data",Database]].map(([name,Icon])=><button key={name as string} className={type===name?"active":""} onClick={()=>setType(name as string)}><Icon/>{name as string}</button>)}</div><form onSubmit={submit} data-testid="inbox-form"><label className="drop"><Upload/><b>Drop or choose a file</b><input name="file" type="file"/></label><div className="form-grid"><label>Frequency Hz<input name="frequency_hz" placeholder="4625000"/></label><label>Mode<select name="mode"><option>USB</option><option>LSB</option><option>AM</option></select></label><label>UTC<input type="datetime-local"/></label><label>Receiver<select><option>Unassigned</option><option>NL-01</option></select></label></div><label>Note<textarea name="note"/></label><label>Tags<input name="tags" placeholder="watchlist, voice"/></label><button className="primary">Save to inbox</button>{status?<p role="status">{status}</p>:null}</form></section><aside className="panel"><span className="kicker">UNCLASSIFIED</span><h2>3 items</h2>{["field-note.wav","Receiver directory URL","4625 kHz short voice"].map(x=><button className="queue" key={x}><i/><b>{x}</b><ChevronRight/></button>)}</aside></div>;
}

function Sources(){return <section className="panel full"><div className="toolbar"><label><Search/><input placeholder="Search sources…"/></label><button className="primary"><Database/>Register source</button></div><div className="cards">{[["Frequency CSV","csv"],["Public event feed","rss_atom"],["Receiver table","html_table"],["Static source","static"]].map(x=><article key={x[0]}><Database/><h2>{x[0]}</h2><code>{x[1]}</code><p>Parser 1.0.0 · disabled by default</p><Layer kind="observed"/></article>)}</div><p className="policy"><ShieldCheck/>robots.txt, per-domain rate limits, retry backoff, ETag/Last-Modified, raw archive and dead-letter state are enforced.</p></section>;}
function Capture(){return <div className="split"><section className="panel inbox-form"><span className="kicker">EXPLICIT WATCHLIST CAPTURE</span><h2>Schedule receiver capture</h2><p>Capture is globally disabled by default.</p><div className="form-grid"><label>Receiver<select><option>NL-01</option></select></label><label>Frequency<input defaultValue="4625000"/></label><label>Mode<select><option>USB</option></select></label><label>Duration<input defaultValue="60"/></label><label>UTC cron<input defaultValue="40 18 * * *"/></label><label>Storage cap<input defaultValue="5 GB"/></label></div><button className="primary"><Antenna/>Save disabled schedule</button></section><aside className="panel"><span className="kicker">QUEUE</span><h2>Schedules</h2><p>4.625 MHz · Daily 18:40 · DISABLED</p><p>8.992 MHz · Monday · SCHEDULED</p></aside></div>;}
function SettingsView(){return <section className="panel settings-view"><span className="kicker">VERSIONED CONFIGURATION</span><h2>Workspace settings</h2>{[["Display",["Timezone: UTC + local","Language: English","Density: Compact"]],["Signal processing",["ASR: large-v3","Device: auto","VAD: 0.55","Preset: voice 300–3,000 Hz"]],["Similarity",["Audio: 0.82","Session merge: 0.68","Embedding: spectral-projection"]],["Local LLM",["Enabled: false","Endpoint: host.docker.internal:1234/v1","API key: server only"]]].map(([title,items])=><fieldset key={title as string}><legend>{title as string}</legend>{(items as string[]).map(item=><label key={item}>{item}<input defaultValue={item.split(": ").slice(1).join(": ")}/></label>)}</fieldset>)}<button className="primary">Save new revision</button></section>;}
function ApiDocs(){return <section className="panel full docs"><span className="kicker">LOCAL LLM TOOL API</span><h2>Structured bounded access</h2><p>Every response contains data, provenance, query, pagination, warnings and generated_at_utc.</p>{["GET /api/v1/health","GET /api/v1/capabilities","POST /api/v1/search/sessions","POST /api/v1/search/segments","POST /api/v1/search/entities","GET /api/v1/sessions/{id}/similar","POST /api/v1/correlations/query","POST /api/v1/export/context-bundle","POST /api/v1/export/evidence-bundle"].map(x=><code key={x}>{x}</code>)}</section>;}
function Login(){
  const [error,setError]=useState("");const login=async(e:React.FormEvent<HTMLFormElement>)=>{e.preventDefault();const form=new FormData(e.currentTarget);try{await api("/auth/login",{method:"POST",body:JSON.stringify({email:form.get("email"),password:form.get("password")})});location.assign("/dashboard");}catch{setError("Invalid credentials or API unavailable.");}};
  return <main className="login"><section><Mark/><span className="kicker">PRIVATE WORKSPACE</span><h1>Signal Index</h1><p>Structure observations. Preserve evidence. Test hypotheses.</p><form onSubmit={login}><label>Email<input name="email" type="email" defaultValue="owner@local.test"/></label><label>Password<input name="password" type="password"/></label><button className="primary">Sign in</button>{error?<p role="alert">{error}</p>:null}</form><small>Public registration disabled · secure session cookie</small></section><aside><Waveform/><p>Observed, machine, corrected, interpreted and hypothetical layers never overwrite one another.</p></aside></main>;
}

function title(path:string):[string,string]{if(path.startsWith("/dashboard"))return["Observation dashboard","OPERATIONS / LIVE INDEX"];if(path.startsWith("/inbox"))return["Universal inbox","CAPTURE / UNCLASSIFIED"];if(path.startsWith("/frequencies"))return["Spectrum explorer","INDEX / FREQUENCIES"];if(path.startsWith("/receivers"))return["Receiver directory","SOURCES / RECEIVERS"];if(path.startsWith("/recordings")||path.startsWith("/segments"))return["Audio review","EVIDENCE / RECORDING"];if(path.startsWith("/sessions/"))return["Session detail","INDEX / SESSION"];if(path.startsWith("/sessions"))return["Session explorer","INDEX / SESSIONS"];if(path.startsWith("/timeline"))return["Observation timeline","ANALYSIS / TEMPORAL"];if(path.startsWith("/graph"))return["Relationship graph","ANALYSIS / RELATIONS"];if(path.startsWith("/hypotheses"))return["Hypothesis notebook","ANALYSIS / NOTEBOOK"];if(path.startsWith("/sources"))return["Source adapters","INGESTION / SOURCES"];if(path.startsWith("/capture"))return["Capture scheduler","INGESTION / WATCHLIST"];if(path.startsWith("/settings"))return["Settings","SYSTEM / CONFIGURATION"];return["Tool API","LOCAL LLM / ACCESS"];}

export function SignalIndexApp({initialPath}:{initialPath:string}){
  if(initialPath==="/login")return <Login/>;
  let view:React.ReactNode;
  if(initialPath.startsWith("/dashboard"))view=<Dashboard/>;else if(initialPath.startsWith("/inbox"))view=<InboxView/>;else if(initialPath.startsWith("/frequencies"))view=<Spectrum/>;else if(initialPath.startsWith("/receivers"))view=<Receivers/>;else if(initialPath.startsWith("/segments/"))view=<AudioReview segmentId={initialPath.split("/")[2]}/>;else if(initialPath.startsWith("/recordings/")||initialPath.startsWith("/sessions/"))view=<AudioReview/>;else if(initialPath.startsWith("/sessions")||initialPath.startsWith("/recordings"))view=<Sessions/>;else if(initialPath.startsWith("/timeline"))view=<Timeline/>;else if(initialPath.startsWith("/graph"))view=<Graph/>;else if(initialPath==="/hypotheses"||initialPath==="/hypotheses/new")view=<Hypotheses/>;else if(initialPath.startsWith("/hypotheses/"))view=<Hypotheses detail/>;else if(initialPath.startsWith("/sources"))view=<Sources/>;else if(initialPath.startsWith("/capture"))view=<Capture/>;else if(initialPath.startsWith("/settings"))view=<SettingsView/>;else view=<ApiDocs/>;
  const [heading,eyebrow]=title(initialPath);return <Shell path={initialPath} title={heading} eyebrow={eyebrow}>{view}</Shell>;
}

