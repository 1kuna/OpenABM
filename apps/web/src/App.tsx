import {
  Activity,
  AlertTriangle,
  Box,
  Braces,
  CheckCircle2,
  Database,
  FileSearch,
  GitBranch,
  KeyRound,
  Network,
  Play,
  Search,
  Shield,
  Split,
  TimerReset
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { OpenAbmClient } from "./api";
import { fixtureDetails, fixtureProjects, fixtureTraces } from "./fixtures";
import type { Project, SpanEnvelope, TimelineRow, TraceDetail, TraceEnvelope, TraceStatus } from "./types";

const DEFAULT_BASE_URL = "http://127.0.0.1:8787";
const DEFAULT_API_KEY = "dev-openabm-key";

type ConnectionState = "connecting" | "live" | "fixture";
type ViewKey =
  | "traces"
  | "issues"
  | "judges"
  | "behaviors"
  | "datasets"
  | "prompts"
  | "mcp"
  | "ops";

export function App() {
  const [baseUrl, setBaseUrl] = useState(localStorage.getItem("openabm.baseUrl") ?? DEFAULT_BASE_URL);
  const [apiKey, setApiKey] = useState(localStorage.getItem("openabm.apiKey") ?? DEFAULT_API_KEY);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [projects, setProjects] = useState<Project[]>(fixtureProjects);
  const [projectId, setProjectId] = useState("proj_demo");
  const [traces, setTraces] = useState<TraceEnvelope[]>(fixtureTraces);
  const [selectedTraceId, setSelectedTraceId] = useState(fixtureTraces[0]?.trace_id ?? "");
  const [detail, setDetail] = useState<TraceDetail | null>(fixtureDetails[0] ?? null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [activeView, setActiveView] = useState<ViewKey>("traces");
  const [similarState, setSimilarState] = useState("semantic search deferred");

  const client = useMemo(() => new OpenAbmClient({ baseUrl, apiKey }), [baseUrl, apiKey]);

  useEffect(() => {
    localStorage.setItem("openabm.baseUrl", baseUrl);
    localStorage.setItem("openabm.apiKey", apiKey);
  }, [baseUrl, apiKey]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setConnection("connecting");
      try {
        const loadedProjects = await client.listProjects();
        if (cancelled) return;
        setProjects(loadedProjects.length ? loadedProjects : fixtureProjects);
        const nextProjectId = loadedProjects[0]?.project_id ?? projectId;
        setProjectId(nextProjectId);
        const loadedTraces = await client.listTraces(nextProjectId);
        if (cancelled) return;
        setConnection("live");
        setTraces(loadedTraces.length ? loadedTraces : fixtureTraces);
        setSelectedTraceId((current) => current || loadedTraces[0]?.trace_id || fixtureTraces[0]?.trace_id || "");
      } catch {
        if (cancelled) return;
        setConnection("fixture");
        setProjects(fixtureProjects);
        setTraces(fixtureTraces);
        setProjectId("proj_demo");
        setSelectedTraceId(fixtureTraces[0]?.trace_id ?? "");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [client]);

  useEffect(() => {
    let cancelled = false;
    async function loadDetail() {
      if (!selectedTraceId) return;
      if (connection !== "live") {
        setDetail(fixtureDetails.find((item) => item.trace.trace_id === selectedTraceId) ?? fixtureDetails[0]);
        return;
      }
      try {
        const loaded = await client.getTrace(projectId, selectedTraceId);
        if (!cancelled) setDetail(loaded);
      } catch {
        if (!cancelled) setDetail(fixtureDetails[0]);
      }
    }
    void loadDetail();
    return () => {
      cancelled = true;
    };
  }, [client, connection, projectId, selectedTraceId]);

  async function refreshTraces() {
    if (connection !== "live") {
      setTraces(fixtureTraces);
      return;
    }
    const loaded = query
      ? await client.searchTraces(projectId, query)
      : await client.listTraces(projectId, status || undefined);
    setTraces(loaded);
    if (loaded[0]) setSelectedTraceId(loaded[0].trace_id);
  }

  async function checkSimilarity() {
    if (!selectedTraceId) return;
    if (connection !== "live") {
      setSimilarState("semantic search deferred until embeddings are enabled");
      return;
    }
    const result = await client.searchSimilar(projectId, selectedTraceId);
    setSimilarState(result.disabled ? result.reason ?? "disabled" : "ready");
  }

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brandMark">OA</div>
          <div>
            <h1>OpenABM</h1>
            <span>{connectionLabel(connection)}</span>
          </div>
        </div>
        <nav className="nav">
          <NavButton icon={<FileSearch />} label="Traces" active={activeView === "traces"} onClick={() => setActiveView("traces")} />
          <NavButton icon={<AlertTriangle />} label="Issues" active={activeView === "issues"} onClick={() => setActiveView("issues")} />
          <NavButton icon={<Braces />} label="Judges" active={activeView === "judges"} onClick={() => setActiveView("judges")} />
          <NavButton icon={<GitBranch />} label="Behaviors" active={activeView === "behaviors"} onClick={() => setActiveView("behaviors")} />
          <NavButton icon={<Database />} label="Datasets" active={activeView === "datasets"} onClick={() => setActiveView("datasets")} />
          <NavButton icon={<Split />} label="Prompts" active={activeView === "prompts"} onClick={() => setActiveView("prompts")} />
          <NavButton icon={<Network />} label="MCP" active={activeView === "mcp"} onClick={() => setActiveView("mcp")} />
          <NavButton icon={<Shield />} label="Ops" active={activeView === "ops"} onClick={() => setActiveView("ops")} />
        </nav>
        <div className="connectionBox">
          <label>
            API
            <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
          </label>
          <label>
            Key
            <input value={apiKey} onChange={(event) => setApiKey(event.target.value)} type="password" />
          </label>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="sectionLabel">{activeView}</p>
            <h2>{viewTitle(activeView)}</h2>
          </div>
          <div className="topbarControls">
            <select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
              {projects.map((project) => (
                <option key={project.project_id} value={project.project_id}>
                  {project.name}
                </option>
              ))}
            </select>
            <button className="primaryButton" onClick={() => void refreshTraces()}>
              <TimerReset size={16} />
              Refresh
            </button>
          </div>
        </header>

        {activeView === "traces" ? (
          <TraceExplorer
            traces={traces}
            detail={detail}
            query={query}
            status={status}
            selectedTraceId={selectedTraceId}
            similarState={similarState}
            onQueryChange={setQuery}
            onStatusChange={setStatus}
            onSearch={() => void refreshTraces()}
            onSelectTrace={setSelectedTraceId}
            onCheckSimilarity={() => void checkSimilarity()}
          />
        ) : (
          <ScaffoldView activeView={activeView} />
        )}
      </section>
    </main>
  );
}

function TraceExplorer(props: {
  traces: TraceEnvelope[];
  detail: TraceDetail | null;
  query: string;
  status: string;
  selectedTraceId: string;
  similarState: string;
  onQueryChange: (value: string) => void;
  onStatusChange: (value: string) => void;
  onSearch: () => void;
  onSelectTrace: (traceId: string) => void;
  onCheckSimilarity: () => void;
}) {
  const { traces, detail } = props;
  const selectedSpan = detail?.spans[0] ?? null;
  return (
    <div className="traceGrid">
      <section className="traceList panel">
        <div className="toolbar">
          <div className="searchBox">
            <Search size={16} />
            <input
              value={props.query}
              placeholder="Search traces"
              onChange={(event) => props.onQueryChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") props.onSearch();
              }}
            />
          </div>
          <select value={props.status} onChange={(event) => props.onStatusChange(event.target.value)}>
            <option value="">Any status</option>
            <option value="ok">ok</option>
            <option value="error">error</option>
            <option value="incomplete">incomplete</option>
            <option value="timeout">timeout</option>
          </select>
          <button className="iconButton" onClick={props.onSearch} aria-label="Run trace search">
            <Play size={16} />
          </button>
        </div>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>Trace</th>
                <th>Session</th>
                <th>Started</th>
                <th>Tags</th>
              </tr>
            </thead>
            <tbody>
              {traces.map((trace) => (
                <tr
                  key={trace.trace_id}
                  className={trace.trace_id === props.selectedTraceId ? "selectedRow" : ""}
                  onClick={() => props.onSelectTrace(trace.trace_id)}
                >
                  <td><StatusBadge status={trace.status} /></td>
                  <td>
                    <strong>{trace.trace_id}</strong>
                    <span>{trace.summary}</span>
                  </td>
                  <td>{trace.session_id ?? "none"}</td>
                  <td>{formatTime(trace.started_at)}</td>
                  <td>{trace.tags.slice(0, 3).join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="traceDetail panel">
        {detail ? (
          <>
            <div className="detailHeader">
              <div>
                <p className="sectionLabel">trace detail</p>
                <h3>{detail.trace.trace_id}</h3>
              </div>
              <StatusBadge status={detail.trace.status} />
            </div>
            <div className="metricsRow">
              <Metric icon={<Activity />} label="Spans" value={String(detail.spans.length)} />
              <Metric icon={<AlertTriangle />} label="Warnings" value={String(detail.reconstruction.warnings.length)} />
              <Metric icon={<Box />} label="Payloads" value={payloadSummary(detail)} />
            </div>
            <Timeline rows={detail.reconstruction.timeline_rows} />
            <Inspector span={selectedSpan} />
            <div className="actionStrip">
              <button onClick={props.onCheckSimilarity}>
                <Search size={15} />
                Similar
              </button>
              <button>
                <Braces size={15} />
                Deterministic check
              </button>
              <button>
                <Database size={15} />
                Dataset draft
              </button>
            </div>
            <p className="systemNote">{props.similarState}</p>
          </>
        ) : (
          <div className="emptyState">No trace selected</div>
        )}
      </section>
    </div>
  );
}

function Timeline({ rows }: { rows: TimelineRow[] }) {
  return (
    <div className="timeline">
      {rows.map((row) => (
        <div className="timelineRow" key={row.span_id}>
          <span className={`dot ${row.status}`} />
          <div>
            <strong>{row.name}</strong>
            <small>{row.span_type} · {formatTime(row.started_at)}</small>
          </div>
        </div>
      ))}
    </div>
  );
}

function Inspector({ span }: { span: SpanEnvelope | null }) {
  if (!span) return <div className="emptyState">No span</div>;
  return (
    <div className="inspector">
      <div className="inspectorHeader">
        <span>{span.span_type}</span>
        <strong>{span.name}</strong>
      </div>
      <pre>{JSON.stringify({ attributes: span.attributes, events: span.events }, null, 2)}</pre>
    </div>
  );
}

function ScaffoldView({ activeView }: { activeView: ViewKey }) {
  const rows = scaffoldRows(activeView);
  return (
    <section className="panel scaffoldPanel">
      <div className="scaffoldGrid">
        {rows.map((row) => (
          <div className="workRow" key={row.title}>
            <div className="workIcon">{row.icon}</div>
            <div>
              <h3>{row.title}</h3>
              <p>{row.status}</p>
            </div>
            <span>{row.phase}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function scaffoldRows(view: ViewKey) {
  const shared = {
    judges: [
      { icon: <Braces />, title: "Deterministic rule judges", status: "available", phase: "Phase 4" },
      { icon: <Shield />, title: "Rubric judge provider", status: "disabled until model work resumes", phase: "Phase 4" },
      { icon: <KeyRound />, title: "Code judge sandbox", status: "development-only isolation", phase: "Phase 4" }
    ],
    behaviors: [
      { icon: <GitBranch />, title: "Manual labels", status: "schema and API surface pending", phase: "Phase 6" },
      { icon: <Braces />, title: "Rule detectors", status: "condition grammar available", phase: "Phase 6" },
      { icon: <Network />, title: "Cluster discovery", status: "deferred until embeddings", phase: "Phase 6" }
    ],
    datasets: [
      { icon: <Database />, title: "Dataset provenance", status: "schema and storage tables available", phase: "Phase 5" },
      { icon: <Play />, title: "Offline runner", status: "make demo-eval available", phase: "Phase 5" },
      { icon: <CheckCircle2 />, title: "Baseline comparison", status: "deterministic data model pending", phase: "Phase 5" }
    ],
    prompts: [
      { icon: <Split />, title: "Prompt commit IDs", status: "available", phase: "Phase 7" },
      { icon: <FileSearch />, title: "Prompt diff", status: "available", phase: "Phase 7" },
      { icon: <Shield />, title: "Secret interpolation", status: "blocked by renderer", phase: "Phase 7" }
    ],
    mcp: [
      { icon: <Network />, title: "Tool contracts", status: "all required names registered", phase: "Phase 7" },
      { icon: <FileSearch />, title: "Read handlers", status: "next implementation slice", phase: "Phase 7" },
      { icon: <Shield />, title: "Write confirmations", status: "metadata scaffolded", phase: "Phase 7" }
    ],
    ops: [
      { icon: <Activity />, title: "Health and readiness", status: "available", phase: "Phase 8" },
      { icon: <Shield />, title: "RBAC and secrets", status: "scaffold pending", phase: "Phase 8" },
      { icon: <Database />, title: "Retention/export/delete", status: "storage hooks pending", phase: "Phase 8" }
    ],
    traces: [],
    issues: [
      { icon: <AlertTriangle />, title: "Issue intake", status: "API and storage available", phase: "Spec v2" },
      { icon: <FileSearch />, title: "Deterministic investigation", status: "structured search and impact scaffold available", phase: "Spec v2" },
      { icon: <Database />, title: "Affected entities", status: "computed from trace dimensions", phase: "Spec v2" }
    ],
  };
  return shared[view];
}

function NavButton(props: { icon: React.ReactNode; label: string; active: boolean; onClick: () => void }) {
  return (
    <button className={props.active ? "active" : ""} onClick={props.onClick}>
      {props.icon}
      {props.label}
    </button>
  );
}

function StatusBadge({ status }: { status: TraceStatus }) {
  return <span className={`statusBadge ${status}`}>{status}</span>;
}

function Metric(props: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="metric">
      {props.icon}
      <span>{props.label}</span>
      <strong>{props.value}</strong>
    </div>
  );
}

function payloadSummary(detail: TraceDetail) {
  const states = Object.values(detail.reconstruction.payload_availability).flatMap((state) => [
    state.input,
    state.output
  ]);
  return Array.from(new Set(states)).join(", ") || "none";
}

function connectionLabel(connection: ConnectionState) {
  if (connection === "live") return "live API";
  if (connection === "fixture") return "fixture mode";
  return "connecting";
}

function viewTitle(view: ViewKey) {
  const labels: Record<ViewKey, string> = {
    traces: "Trace explorer",
    issues: "Issues and investigations",
    judges: "Judge runtime",
    behaviors: "Behavior monitoring",
    datasets: "Datasets and evals",
    prompts: "Prompt registry",
    mcp: "MCP server",
    ops: "Operations"
  };
  return labels[view];
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  }).format(new Date(value));
}
