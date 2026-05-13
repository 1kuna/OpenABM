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
import type {
  JudgeCalibrationReport,
  JudgeDefinition,
  JudgePromotionResult,
  Project,
  ReviewTask,
  SpanEnvelope,
  TimelineRow,
  TraceDetail,
  TraceEnvelope,
  TraceStatus
} from "./types";

const DEFAULT_BASE_URL = "http://127.0.0.1:8787";
const DEFAULT_API_KEY = "dev-openabm-key";

type ConnectionState = "connecting" | "live" | "fixture";
type ViewKey =
  | "traces"
  | "issues"
  | "reviews"
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
  const [similarState, setSimilarState] = useState("semantic similarity ready when a model provider is configured");

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
      setSimilarState("similarity requires a live API and configured model provider");
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
          <NavButton icon={<CheckCircle2 />} label="Reviews" active={activeView === "reviews"} onClick={() => setActiveView("reviews")} />
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
        ) : activeView === "reviews" ? (
          <ReviewQueue client={client} connection={connection} projectId={projectId} />
        ) : activeView === "judges" ? (
          <JudgeWorkspace client={client} connection={connection} projectId={projectId} />
        ) : (
          <ScaffoldView
            activeView={activeView}
            client={client}
            connection={connection}
            projectId={projectId}
          />
        )}
      </section>
    </main>
  );
}

function JudgeWorkspace(props: {
  client: OpenAbmClient;
  connection: ConnectionState;
  projectId: string;
}) {
  const { client, connection, projectId } = props;
  const [judges, setJudges] = useState<JudgeDefinition[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [report, setReport] = useState<JudgeCalibrationReport | null>(null);
  const [promotion, setPromotion] = useState<JudgePromotionResult | null>(null);
  const [statusText, setStatusText] = useState("Judge workspace needs a live API");
  const [minScoreCount, setMinScoreCount] = useState("1");
  const [maxInvalidRate, setMaxInvalidRate] = useState("0");
  const [requireAcceptedReview, setRequireAcceptedReview] = useState(true);
  const [requireNoOpenReviews, setRequireNoOpenReviews] = useState(true);

  const selectedJudge = judges.find((judge) => judge.judge_id === selectedId) ?? judges[0] ?? null;

  async function loadJudges() {
    if (connection !== "live") {
      setJudges([]);
      setSelectedId("");
      setReport(null);
      setPromotion(null);
      setStatusText("fixture mode");
      return;
    }
    try {
      const loaded = await client.listJudges(projectId);
      setJudges(loaded);
      setSelectedId((current) =>
        loaded.some((judge) => judge.judge_id === current)
          ? current
          : loaded[0]?.judge_id ?? ""
      );
      setPromotion(null);
      setStatusText(`${loaded.length} judges`);
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : "request failed");
    }
  }

  useEffect(() => {
    void loadJudges();
  }, [client, connection, projectId]);

  useEffect(() => {
    let cancelled = false;
    async function loadReport() {
      if (connection !== "live" || !selectedJudge) {
        setReport(null);
        return;
      }
      try {
        const [freshJudge, nextReport] = await Promise.all([
          client.getJudge(projectId, selectedJudge.judge_id),
          client.getJudgeCalibrationReport(projectId, selectedJudge.judge_id)
        ]);
        if (cancelled) return;
        setJudges((current) =>
          current.map((judge) => (judge.judge_id === freshJudge.judge_id ? freshJudge : judge))
        );
        setReport(nextReport);
        setStatusText(`calibration ready for ${freshJudge.name}`);
      } catch (error) {
        if (!cancelled) {
          setReport(null);
          setStatusText(error instanceof Error ? error.message : "report unavailable");
        }
      }
    }
    void loadReport();
    return () => {
      cancelled = true;
    };
  }, [client, connection, projectId, selectedJudge?.judge_id]);

  async function promoteSelectedJudge() {
    if (!selectedJudge || connection !== "live") return;
    const policy = {
      min_score_count: Number.parseInt(minScoreCount, 10) || 0,
      max_invalid_output_rate: Number.parseFloat(maxInvalidRate) || 0,
      require_accepted_review: requireAcceptedReview,
      require_no_open_reviews: requireNoOpenReviews
    };
    try {
      const result = await client.promoteJudge(projectId, selectedJudge.judge_id, policy);
      setPromotion(result);
      setReport(result.calibration_report);
      if (result.judge) {
        setJudges((current) =>
          current.map((judge) => (judge.judge_id === result.judge?.judge_id ? result.judge : judge))
        );
      }
      setStatusText(result.status === "promoted" ? "judge promoted" : "promotion blocked");
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : "promotion failed");
    }
  }

  return (
    <div className="judgeGrid">
      <section className="panel judgeList">
        <div className="toolbar">
          <button className="iconButton" onClick={() => void loadJudges()} aria-label="Refresh judges">
            <TimerReset size={16} />
          </button>
          <span className="systemNote">{statusText}</span>
        </div>
        <div className="judgeRows">
          {judges.map((judge) => (
            <button
              className={judge.judge_id === selectedJudge?.judge_id ? "selectedJudge" : ""}
              key={judge.judge_id}
              onClick={() => {
                setSelectedId(judge.judge_id);
                setPromotion(null);
              }}
            >
              <span className={`judgeStatus ${judge.status}`}>{judge.status}</span>
              <strong>{judge.name}</strong>
              <small>{judge.judge_type} · {judge.versions?.length ?? 0} versions</small>
            </button>
          ))}
          {!judges.length ? <div className="emptyState">No judges</div> : null}
        </div>
      </section>

      <section className="panel judgeDetail">
        {selectedJudge ? (
          <>
            <div className="detailHeader">
              <div>
                <p className="sectionLabel">judge</p>
                <h3>{selectedJudge.name}</h3>
              </div>
              <span className={`judgeStatus ${selectedJudge.status}`}>{selectedJudge.status}</span>
            </div>
            <p className="entityDescription">{selectedJudge.description ?? selectedJudge.judge_id}</p>
            <div className="metricsRow judgeMetrics">
              <Metric icon={<Activity />} label="Scores" value={report ? String(report.score_count) : "none"} />
              <Metric icon={<AlertTriangle />} label="Invalid output" value={formatRate(report?.invalid_output_rate)} />
              <Metric icon={<CheckCircle2 />} label="Accepted reviews" value={String(report?.human_review_labels.accepted ?? 0)} />
            </div>
            <div className="judgeSections">
              <section className="judgeSection">
                <h4>Calibration</h4>
                {report ? (
                  <>
                    <dl className="reviewFacts">
                      <div>
                        <dt>Verdicts</dt>
                        <dd>{formatCounts(report.verdict_counts)}</dd>
                      </div>
                      <div>
                        <dt>Status counts</dt>
                        <dd>{formatCounts(report.status_counts)}</dd>
                      </div>
                      <div>
                        <dt>Eval runs</dt>
                        <dd>{report.eval_run_ids.join(", ") || "none"}</dd>
                      </div>
                      <div>
                        <dt>Tokens</dt>
                        <dd>{report.token_usage ?? "none"}</dd>
                      </div>
                    </dl>
                    <div className="driftTable">
                      {report.drift_report.map((row) => (
                        <div key={String(row.eval_run_id)}>
                          <strong>{String(row.eval_run_id)}</strong>
                          <span>{String(row.score_count ?? 0)} scores · {formatCounts(asRecord(row.verdict_counts))}</span>
                        </div>
                      ))}
                      {!report.drift_report.length ? <p className="systemNote">No eval drift rows yet</p> : null}
                    </div>
                  </>
                ) : (
                  <div className="emptyState">No calibration report</div>
                )}
              </section>

              <section className="judgeSection">
                <h4>Promotion gate</h4>
                <div className="policyGrid">
                  <label>
                    Min scores
                    <input value={minScoreCount} onChange={(event) => setMinScoreCount(event.target.value)} inputMode="numeric" />
                  </label>
                  <label>
                    Max invalid rate
                    <input value={maxInvalidRate} onChange={(event) => setMaxInvalidRate(event.target.value)} inputMode="decimal" />
                  </label>
                  <label className="toggleLabel">
                    <input
                      type="checkbox"
                      checked={requireAcceptedReview}
                      onChange={(event) => setRequireAcceptedReview(event.target.checked)}
                    />
                    Accepted review
                  </label>
                  <label className="toggleLabel">
                    <input
                      type="checkbox"
                      checked={requireNoOpenReviews}
                      onChange={(event) => setRequireNoOpenReviews(event.target.checked)}
                    />
                    No open reviews
                  </label>
                </div>
                <button className="primaryButton" onClick={() => void promoteSelectedJudge()}>
                  <Shield size={15} />
                  Promote
                </button>
                {promotion ? (
                  <div className={`promotionResult ${promotion.status}`}>
                    <strong>{promotion.status}</strong>
                    <span>{promotion.blocking_reasons.join(", ") || "all gates passed"}</span>
                  </div>
                ) : null}
              </section>

              <section className="judgeSection">
                <h4>Versions</h4>
                <div className="versionRows">
                  {(selectedJudge.versions ?? []).map((version) => (
                    <div key={version.judge_version_id}>
                      <strong>v{version.version}</strong>
                      <span>{version.judge_version_id}</span>
                      <small>{formatTime(version.created_at)}</small>
                    </div>
                  ))}
                  {!selectedJudge.versions?.length ? <p className="systemNote">No immutable versions yet</p> : null}
                </div>
              </section>
            </div>
          </>
        ) : (
          <div className="emptyState">{statusText}</div>
        )}
      </section>
    </div>
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

function ReviewQueue(props: {
  client: OpenAbmClient;
  connection: ConnectionState;
  projectId: string;
}) {
  const { client, connection, projectId } = props;
  const [tasks, setTasks] = useState<ReviewTask[]>([]);
  const [statusFilter, setStatusFilter] = useState("open");
  const [typeFilter, setTypeFilter] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [notes, setNotes] = useState("");
  const [reviewState, setReviewState] = useState("Review queue needs a live API");

  const selectedTask = tasks.find((task) => task.review_task_id === selectedId) ?? tasks[0] ?? null;

  async function loadTasks() {
    if (connection !== "live") {
      setTasks([]);
      setSelectedId("");
      setReviewState("fixture mode");
      return;
    }
    try {
      const loaded = await client.listReviewTasks(projectId, {
        status: statusFilter || undefined,
        taskType: typeFilter || undefined
      });
      setTasks(loaded);
      setSelectedId((current) =>
        loaded.some((task) => task.review_task_id === current)
          ? current
          : loaded[0]?.review_task_id ?? ""
      );
      setReviewState(`${loaded.length} tasks`);
    } catch (error) {
      setReviewState(error instanceof Error ? error.message : "request failed");
    }
  }

  useEffect(() => {
    void loadTasks();
  }, [client, connection, projectId, statusFilter, typeFilter]);

  useEffect(() => {
    setNotes(selectedTask?.notes_nullable ?? "");
  }, [selectedTask?.review_task_id]);

  async function decide(status: ReviewTask["status"], decision: string) {
    if (!selectedTask || connection !== "live") return;
    const updated = await client.updateReviewTask(projectId, selectedTask.review_task_id, {
      status,
      decision,
      notes
    });
    setTasks((current) =>
      current.map((task) => (task.review_task_id === updated.review_task_id ? updated : task))
    );
    setReviewState(`${updated.status}: ${updated.review_task_id}`);
  }

  return (
    <div className="reviewGrid">
      <section className="panel reviewList">
        <div className="toolbar">
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="">Any status</option>
            <option value="open">open</option>
            <option value="accepted">accepted</option>
            <option value="rejected">rejected</option>
            <option value="needs_more_evidence">needs more evidence</option>
            <option value="resolved">resolved</option>
          </select>
          <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
            <option value="">Any type</option>
            <option value="judge_output">judge output</option>
            <option value="behavior_candidate">behavior candidate</option>
            <option value="grounding_check">grounding check</option>
            <option value="affected_entity">affected entity</option>
            <option value="root_cause_candidate">root cause candidate</option>
          </select>
          <button className="iconButton" onClick={() => void loadTasks()} aria-label="Refresh reviews">
            <TimerReset size={16} />
          </button>
        </div>
        <div className="reviewRows">
          {tasks.map((task) => (
            <button
              className={task.review_task_id === selectedTask?.review_task_id ? "selectedReview" : ""}
              key={task.review_task_id}
              onClick={() => setSelectedId(task.review_task_id)}
            >
              <span className={`reviewStatus ${task.status}`}>{task.status}</span>
              <strong>{task.task_type}</strong>
              <small>{task.source_entity_type} · {task.source_entity_id}</small>
            </button>
          ))}
          {!tasks.length ? <div className="emptyState">No review tasks</div> : null}
        </div>
      </section>

      <section className="panel reviewDetail">
        {selectedTask ? (
          <>
            <div className="detailHeader">
              <div>
                <p className="sectionLabel">review task</p>
                <h3>{selectedTask.review_task_id}</h3>
              </div>
              <span className={`reviewStatus ${selectedTask.status}`}>{selectedTask.status}</span>
            </div>
            <div className="reviewMeta">
              <Metric icon={<Braces />} label="Type" value={selectedTask.task_type} />
              <Metric icon={<FileSearch />} label="Evidence" value={String(selectedTask.evidence_ids.length)} />
              <Metric icon={<Activity />} label="Updated" value={formatTime(selectedTask.updated_at)} />
            </div>
            <dl className="reviewFacts">
              <div>
                <dt>Source</dt>
                <dd>{selectedTask.source_entity_type} · {selectedTask.source_entity_id}</dd>
              </div>
              <div>
                <dt>Decision</dt>
                <dd>{selectedTask.decision_nullable ?? "none"}</dd>
              </div>
              <div>
                <dt>Evidence</dt>
                <dd>{selectedTask.evidence_ids.join(", ") || "none"}</dd>
              </div>
            </dl>
            <label className="notesBox">
              Notes
              <textarea value={notes} onChange={(event) => setNotes(event.target.value)} />
            </label>
            <div className="reviewActions">
              <button onClick={() => void decide("accepted", "accepted")}>
                <CheckCircle2 size={15} />
                Accept
              </button>
              <button onClick={() => void decide("needs_more_evidence", "needs_more_evidence")}>
                <FileSearch size={15} />
                Needs evidence
              </button>
              <button onClick={() => void decide("rejected", "rejected")}>
                <AlertTriangle size={15} />
                Reject
              </button>
            </div>
            <p className="systemNote">{reviewState}</p>
          </>
        ) : (
          <div className="emptyState">{reviewState}</div>
        )}
      </section>
    </div>
  );
}

function ScaffoldView(props: {
  activeView: ViewKey;
  client: OpenAbmClient;
  connection: ConnectionState;
  projectId: string;
}) {
  const { activeView, client, connection, projectId } = props;
  const rows = scaffoldRows(activeView);
  const [summary, setSummary] = useState<ModuleSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadSummary() {
      if (connection !== "live") {
        setSummary(moduleFixtureSummary(activeView));
        return;
      }
      try {
        const nextSummary = await moduleLiveSummary(activeView, client, projectId);
        if (!cancelled) setSummary(nextSummary);
      } catch (error) {
        if (!cancelled) {
          setSummary({
            label: "Live check",
            value: "unavailable",
            detail: error instanceof Error ? error.message : "request failed"
          });
        }
      }
    }
    void loadSummary();
    return () => {
      cancelled = true;
    };
  }, [activeView, client, connection, projectId]);

  return (
    <section className="panel scaffoldPanel">
      {summary ? (
        <div className="moduleSummary">
          <Metric icon={<Activity />} label={summary.label} value={summary.value} />
          <p>{summary.detail}</p>
        </div>
      ) : null}
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

type ModuleSummary = {
  label: string;
  value: string;
  detail: string;
};

async function moduleLiveSummary(
  view: ViewKey,
  client: OpenAbmClient,
  projectId: string
): Promise<ModuleSummary> {
  if (view === "judges") {
    const judges = await client.listJudges(projectId);
    return {
      label: "Judges",
      value: String(judges.length),
      detail: judges[0]
        ? `Latest: ${judges[0].name} (${judges[0].judge_type})`
        : "No judge drafts or versions yet"
    };
  }
  if (view === "datasets") {
    const evals = await client.listEvalRuns(projectId);
    const latest = evals[0];
    return {
      label: "Eval runs",
      value: String(evals.length),
      detail: latest ? `Latest ${latest.status} run: ${latest.eval_run_id}` : "No eval runs yet"
    };
  }
  if (view === "reviews") {
    const tasks = await client.listReviewTasks(projectId, { status: "open" });
    return {
      label: "Open reviews",
      value: String(tasks.length),
      detail: tasks[0]
        ? `${tasks[0].task_type}: ${tasks[0].source_entity_id}`
        : "No open review tasks"
    };
  }
  if (view === "mcp") {
    const hits = await client.searchDocs("judge eval docs");
    return {
      label: "Docs hits",
      value: String(hits.length),
      detail: hits[0] ? `${hits[0].path}:${hits[0].line}` : "No public doc hits"
    };
  }
  return moduleFixtureSummary(view);
}

function moduleFixtureSummary(view: ViewKey): ModuleSummary {
  const summaries: Record<ViewKey, ModuleSummary> = {
    traces: { label: "Mode", value: "fixture", detail: "Trace explorer uses bundled fixtures offline" },
    issues: { label: "Issue flow", value: "ready", detail: "Issue and investigation APIs are wired" },
    reviews: { label: "Reviews", value: "live", detail: "Review decisions are API-backed" },
    judges: { label: "Judges", value: "ready", detail: "Registry, drafts, and versions are API-backed" },
    behaviors: { label: "Behaviors", value: "ready", detail: "Rules and backtests are API-backed" },
    datasets: { label: "Evals", value: "ready", detail: "Local eval run and compare APIs are wired" },
    prompts: { label: "Prompts", value: "ready", detail: "Versions, tags, render, and diff are API-backed" },
    mcp: { label: "MCP", value: "35 tools", detail: "Judge, eval, and docs handlers are routed" },
    ops: { label: "Ops", value: "ready", detail: "Health, export, retention, and tombstones are wired" }
  };
  return summaries[view];
}

function scaffoldRows(view: ViewKey) {
  const shared = {
    judges: [
      { icon: <Braces />, title: "Judge registry", status: "drafts and immutable versions available", phase: "Phase 4" },
      { icon: <Shield />, title: "Rubric judge provider", status: "local model-backed and review-gated", phase: "Phase 4" },
      { icon: <KeyRound />, title: "Code judge sandbox", status: "development-only isolation", phase: "Phase 4" }
    ],
    behaviors: [
      { icon: <GitBranch />, title: "Manual labels", status: "schema and API surface pending", phase: "Phase 6" },
      { icon: <Braces />, title: "Rule detectors", status: "condition grammar available", phase: "Phase 6" },
      { icon: <Network />, title: "Cluster discovery", status: "deferred until embeddings", phase: "Phase 6" }
    ],
    datasets: [
      { icon: <Database />, title: "Dataset provenance", status: "schema and storage tables available", phase: "Phase 5" },
      { icon: <Play />, title: "Eval runner", status: "deterministic and rubric judges supported", phase: "Phase 5" },
      { icon: <CheckCircle2 />, title: "Baseline comparison", status: "pass-rate and score deltas available", phase: "Phase 5" }
    ],
    prompts: [
      { icon: <Split />, title: "Prompt commit IDs", status: "available", phase: "Phase 7" },
      { icon: <FileSearch />, title: "Prompt diff", status: "available", phase: "Phase 7" },
      { icon: <Shield />, title: "Secret interpolation", status: "blocked by renderer", phase: "Phase 7" }
    ],
    mcp: [
      { icon: <Network />, title: "Tool contracts", status: "all required names registered", phase: "Phase 7" },
      { icon: <FileSearch />, title: "API-backed handlers", status: "judges, evals, docs, prompts, configs, automations routed", phase: "Phase 7" },
      { icon: <Shield />, title: "Write confirmations", status: "metadata scaffolded", phase: "Phase 7" }
    ],
    ops: [
      { icon: <Activity />, title: "Health and readiness", status: "available", phase: "Phase 8" },
      { icon: <Shield />, title: "API key scopes and audit", status: "local scaffold available", phase: "Phase 8" },
      { icon: <Database />, title: "Retention/export/delete", status: "policy, manifest, and tombstone paths available", phase: "Phase 8" }
    ],
    traces: [],
    issues: [
      { icon: <AlertTriangle />, title: "Issue intake", status: "API and storage available", phase: "Spec v2" },
      { icon: <FileSearch />, title: "Deterministic investigation", status: "structured search and impact scaffold available", phase: "Spec v2" },
      { icon: <Database />, title: "Affected entities", status: "computed from trace dimensions", phase: "Spec v2" }
    ],
    reviews: [
      { icon: <CheckCircle2 />, title: "Review queue", status: "live task list and decisions", phase: "Phase 6" },
      { icon: <FileSearch />, title: "Evidence IDs", status: "visible on task detail", phase: "Phase 6" },
      { icon: <Shield />, title: "Audit trail", status: "update path records review decisions", phase: "Phase 8" }
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

function formatCounts(counts: Record<string, unknown>) {
  const entries = Object.entries(counts).filter(([, value]) => Number(value) !== 0);
  return entries.map(([key, value]) => `${key}: ${String(value)}`).join(", ") || "none";
}

function formatRate(value: number | null | undefined) {
  if (value == null) return "none";
  return `${Math.round(value * 1000) / 10}%`;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
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
    reviews: "Review queue",
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
