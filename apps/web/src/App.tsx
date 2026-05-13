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
  TimerReset,
  XCircle
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { OpenAbmClient } from "./api";
import { fixtureDetails, fixtureProjects, fixtureTraces } from "./fixtures";
import type {
  AffectedEntity,
  AgentConfigCompareResult,
  AgentConfigDefinition,
  AgentConfigVersion,
  AgentContextPack,
  AuthApiKey,
  AuthContract,
  AuthInvite,
  AuthInviteDelivery,
  AuthSession,
  AuthUser,
  AutomationDefinition,
  AutomationPreviewResult,
  AutomationRun,
  BehaviorBacktestResult,
  BehaviorDefinition,
  BehaviorMatch,
  ChatOpsInvestigationResult,
  ClassificationResult,
  DataClassificationPolicy,
  DatasetDefinition,
  DatasetExample,
  EvalAnalytics,
  EvalComparison,
  EvalResult,
  EvalRun,
  HealthStatus,
  ImpactReport,
  InvestigationRun,
  IssueDefinition,
  IssueLink,
  JudgeCalibrationReport,
  JudgeDefinition,
  JudgePromotionResult,
  NotificationTarget,
  OpsStatus,
  Project,
  ProjectExportBundle,
  PromptDefinition,
  PromptDiffResult,
  PromptVersion,
  RetentionApplyResult,
  RetentionPolicy,
  ReviewTask,
  SavedSearch,
  ScoreResult,
  ScreenshotIssueResult,
  SecretAccessLogEntry,
  SecretBackendStatus,
  SecretRef,
  SimilarityIndexRebuildResult,
  SimilarityIndexSummary,
  SimilarTraceSearchResult,
  SpanEnvelope,
  SpanNode,
  TimelineRow,
  TraceAssertionResult,
  TraceDetail,
  TraceEnvelope,
  TraceStatus,
  VersionUsageSummary
} from "./types";

const DEFAULT_BASE_URL = "http://127.0.0.1:8787";
const DEFAULT_API_KEY = "dev-openabm-key";

type ConnectionState = "connecting" | "live" | "fixture";
type TraceDetailMode = "tree" | "timeline" | "conversation" | "tools" | "code";
type ViewKey =
  | "traces"
  | "issues"
  | "reviews"
  | "judges"
  | "behaviors"
  | "automations"
  | "datasets"
  | "prompts"
  | "configs"
  | "mcp"
  | "ops";
const affectedEntityActionStatuses = ["contacted", "fixed", "ignored", "false_positive"] as const;
const affectedEntityStatuses = ["needs_review", ...affectedEntityActionStatuses] as const;

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
  const [similarResult, setSimilarResult] = useState<SimilarTraceSearchResult | null>(null);

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
        setTraces(loadedTraces);
        setSelectedTraceId((current) =>
          loadedTraces.some((trace) => trace.trace_id === current)
            ? current
            : loadedTraces[0]?.trace_id ?? ""
        );
        if (!loadedTraces.length) setDetail(null);
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
      setSimilarResult(null);
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
    setSelectedTraceId(loaded[0]?.trace_id ?? "");
    if (!loaded[0]) setDetail(null);
  }

  async function checkSimilarity() {
    if (!selectedTraceId) return;
    if (connection !== "live") {
      setSimilarState("similarity requires a live API and configured model provider");
      return;
    }
    const result = await client.searchSimilar(projectId, selectedTraceId);
    setSimilarResult(result);
    setSimilarState(
      result.disabled
        ? result.reason ?? "disabled"
        : `${result.data.length} similar traces · ${result.representation_version ?? "model"}`
    );
  }

  async function applySavedSearch(savedSearch: SavedSearch) {
    const savedQuery = asRecord(savedSearch.query);
    const filters = asRecord(savedQuery.filters);
    const nextStatus = typeof filters.status === "string" ? filters.status : "";
    const nextQuery = typeof savedQuery.full_text_query === "string" ? savedQuery.full_text_query : "";
    setQuery(nextQuery);
    setStatus(nextStatus);
    if (connection !== "live") return;
    const loaded = nextQuery
      ? await client.searchTraces(projectId, nextQuery)
      : await client.listTraces(projectId, nextStatus || undefined);
    setTraces(loaded);
    setSelectedTraceId(loaded[0]?.trace_id ?? "");
    if (!loaded[0]) setDetail(null);
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
          <NavButton icon={<Play />} label="Automations" active={activeView === "automations"} onClick={() => setActiveView("automations")} />
          <NavButton icon={<Database />} label="Datasets" active={activeView === "datasets"} onClick={() => setActiveView("datasets")} />
          <NavButton icon={<Split />} label="Prompts" active={activeView === "prompts"} onClick={() => setActiveView("prompts")} />
          <NavButton icon={<KeyRound />} label="Configs" active={activeView === "configs"} onClick={() => setActiveView("configs")} />
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
            similarResult={similarResult}
            client={client}
            connection={connection}
            projectId={projectId}
            onQueryChange={setQuery}
            onStatusChange={setStatus}
            onSearch={() => void refreshTraces()}
            onApplySavedSearch={(savedSearch) => void applySavedSearch(savedSearch)}
            onSelectTrace={setSelectedTraceId}
            onCheckSimilarity={() => void checkSimilarity()}
            onOpenPrompts={() => setActiveView("prompts")}
            onOpenConfigs={() => setActiveView("configs")}
          />
        ) : activeView === "issues" ? (
          <IssueInvestigationWorkspace
            client={client}
            connection={connection}
            projectId={projectId}
            traces={traces}
            onOpenTrace={(traceId) => {
              setSelectedTraceId(traceId);
              setActiveView("traces");
            }}
          />
        ) : activeView === "reviews" ? (
          <ReviewQueue client={client} connection={connection} projectId={projectId} />
        ) : activeView === "judges" ? (
          <JudgeWorkspace client={client} connection={connection} projectId={projectId} />
        ) : activeView === "datasets" ? (
          <DatasetEvalWorkspace
            client={client}
            connection={connection}
            projectId={projectId}
            onOpenTrace={(traceId) => {
              setSelectedTraceId(traceId);
              setActiveView("traces");
            }}
          />
        ) : activeView === "behaviors" ? (
          <BehaviorWorkspace
            client={client}
            connection={connection}
            projectId={projectId}
            onOpenTrace={(traceId) => {
              setSelectedTraceId(traceId);
              setActiveView("traces");
            }}
          />
        ) : activeView === "automations" ? (
          <AutomationWorkspace client={client} connection={connection} projectId={projectId} traces={traces} />
        ) : activeView === "prompts" ? (
          <PromptRegistryWorkspace
            client={client}
            connection={connection}
            projectId={projectId}
            onOpenTrace={(traceId) => {
              setSelectedTraceId(traceId);
              setActiveView("traces");
            }}
          />
        ) : activeView === "configs" ? (
          <AgentConfigWorkspace
            client={client}
            connection={connection}
            projectId={projectId}
            onOpenTrace={(traceId) => {
              setSelectedTraceId(traceId);
              setActiveView("traces");
            }}
          />
        ) : activeView === "ops" ? (
          <OpsWorkspace client={client} connection={connection} projectId={projectId} />
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

function AgentConfigWorkspace(props: {
  client: OpenAbmClient;
  connection: ConnectionState;
  projectId: string;
  onOpenTrace: (traceId: string) => void;
}) {
  const { client, connection, projectId, onOpenTrace } = props;
  const [configs, setConfigs] = useState<AgentConfigDefinition[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [name, setName] = useState("Refund runtime");
  const [configType, setConfigType] = useState("runtime");
  const [contentText, setContentText] = useState(
    JSON.stringify({ model: "qwen3.5-9b-mlx", tools: ["trace_search"], context_window: 262144 }, null, 2)
  );
  const [metadataText, setMetadataText] = useState(JSON.stringify({ source: "web-ui" }, null, 2));
  const [configTag, setConfigTag] = useState("prod");
  const [oldCommitId, setOldCommitId] = useState("");
  const [newCommitId, setNewCommitId] = useState("");
  const [comparison, setComparison] = useState<AgentConfigCompareResult | null>(null);
  const [stateText, setStateText] = useState("Agent configs need a live API");

  const selectedConfig = configs.find((config) => config.agent_config_id === selectedId) ?? configs[0] ?? null;
  const versions = selectedConfig?.versions ?? [];

  async function loadConfigs() {
    if (connection !== "live") {
      setConfigs([]);
      setSelectedId("");
      setComparison(null);
      setStateText("fixture mode");
      return;
    }
    try {
      const listed = await client.listAgentConfigs(projectId);
      const hydrated = await Promise.all(listed.map((config) => client.getAgentConfig(projectId, config.agent_config_id)));
      setConfigs(hydrated);
      setSelectedId((current) =>
        hydrated.some((config) => config.agent_config_id === current)
          ? current
          : hydrated[0]?.agent_config_id ?? ""
      );
      setStateText(`${hydrated.length} configs`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "request failed");
    }
  }

  useEffect(() => {
    void loadConfigs();
  }, [client, connection, projectId]);

  useEffect(() => {
    const latest = versions[0]?.commit_id ?? "";
    setNewCommitId((current) => current || latest);
    setOldCommitId((current) => current || versions[1]?.commit_id || latest);
  }, [selectedConfig?.agent_config_id, versions.length]);

  async function createConfig() {
    if (connection !== "live" || !name.trim()) return;
    try {
      const created = await client.createAgentConfig(projectId, name.trim(), configType.trim() || "runtime");
      const hydrated = await client.getAgentConfig(projectId, created.agent_config_id);
      setConfigs((current) => [hydrated, ...current]);
      setSelectedId(hydrated.agent_config_id);
      setComparison(null);
      setStateText(`created ${hydrated.name}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "config creation failed");
    }
  }

  async function commitConfigVersion() {
    if (connection !== "live" || !selectedConfig) return;
    let content: Record<string, unknown>;
    let metadata: Record<string, unknown>;
    try {
      content = parseJsonObject(contentText);
      metadata = parseJsonObject(metadataText);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "invalid config JSON");
      return;
    }
    try {
      const version = await client.commitAgentConfigVersion(
        projectId,
        selectedConfig.agent_config_id,
        content,
        metadata,
        configTag.trim() || undefined
      );
      const hydrated = await client.getAgentConfig(projectId, selectedConfig.agent_config_id);
      setConfigs((current) => current.map((config) => (config.agent_config_id === hydrated.agent_config_id ? hydrated : config)));
      setNewCommitId(version.commit_id);
      setOldCommitId((current) => current || version.commit_id);
      setStateText(`committed ${version.commit_id}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "version commit failed");
    }
  }

  async function compareConfigVersions() {
    if (connection !== "live" || !selectedConfig || !oldCommitId || !newCommitId) return;
    try {
      const result = await client.compareAgentConfigVersions(projectId, selectedConfig.agent_config_id, oldCommitId, newCommitId);
      setComparison(result);
      setStateText("comparison ready");
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "compare failed");
    }
  }

  return (
    <div className="configGrid">
      <section className="panel configList">
        <div className="toolbar">
          <button className="iconButton" onClick={() => void loadConfigs()} aria-label="Refresh agent configs">
            <TimerReset size={16} />
          </button>
          <span className="systemNote">{stateText}</span>
        </div>
        <div className="createStrip">
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Config name" />
          <select value={configType} onChange={(event) => setConfigType(event.target.value)}>
            <option value="runtime">runtime</option>
            <option value="workflow">workflow</option>
            <option value="routing">routing</option>
            <option value="guardrail">guardrail</option>
          </select>
          <button onClick={() => void createConfig()}>
            <KeyRound size={15} />
            Create config
          </button>
        </div>
        <div className="configRows">
          {configs.map((config) => (
            <button
              className={config.agent_config_id === selectedConfig?.agent_config_id ? "selectedConfig" : ""}
              key={config.agent_config_id}
              onClick={() => {
                setSelectedId(config.agent_config_id);
                setComparison(null);
              }}
            >
              <span className="judgeStatus active">{config.config_type}</span>
              <strong>{config.name}</strong>
              <small>{config.versions?.length ?? 0} versions · {config.agent_config_id}</small>
            </button>
          ))}
          {!configs.length ? <div className="emptyState">No agent configs</div> : null}
        </div>
      </section>

      <section className="panel configDetail">
        {selectedConfig ? (
          <>
            <div className="detailHeader">
              <div>
                <p className="sectionLabel">agent config</p>
                <h3>{selectedConfig.name}</h3>
              </div>
              <span className="judgeStatus active">{selectedConfig.config_type}</span>
            </div>
            <div className="metricsRow configMetrics">
              <Metric icon={<KeyRound />} label="Versions" value={String(versions.length)} />
              <Metric icon={<GitBranch />} label="Latest" value={versions[0]?.commit_id ?? "none"} />
              <Metric icon={<Shield />} label="Tags" value={formatTags(selectedConfig.tags)} />
              <Metric icon={<Activity />} label="Created" value={formatTime(selectedConfig.created_at)} />
            </div>
            <div className="configSections">
              <section className="configSection">
                <h4>Commit version</h4>
                <label className="notesBox">
                  Content
                  <textarea value={contentText} onChange={(event) => setContentText(event.target.value)} />
                </label>
                <label className="notesBox">
                  Metadata
                  <textarea value={metadataText} onChange={(event) => setMetadataText(event.target.value)} />
                </label>
                <label>
                  Tag pointer
                  <input value={configTag} onChange={(event) => setConfigTag(event.target.value)} />
                </label>
                <button className="primaryButton" onClick={() => void commitConfigVersion()}>
                  <GitBranch size={15} />
                  Commit
                </button>
              </section>

              <section className="configSection">
                <h4>Versions</h4>
                <div className="versionRows">
                  {versions.map((version) => (
                    <div className="versionUsageRow" key={version.agent_config_version_id}>
                      <button
                        className="versionSelectButton"
                        onClick={() => {
                          setContentText(JSON.stringify(version.content, null, 2));
                          setMetadataText(JSON.stringify(version.metadata, null, 2));
                          setNewCommitId(version.commit_id);
                        }}
                      >
                        <strong>v{version.version} · {version.commit_id}</strong>
                        <span>{formatConfigContent(version.content)}</span>
                        <span>Tags {formatStringList(version.active_tags ?? [])}</span>
                        <small>{formatTime(version.created_at)}</small>
                      </button>
                      <VersionUsageRows usage={version.usage_summary} onOpenTrace={onOpenTrace} />
                    </div>
                  ))}
                  {!versions.length ? <p className="systemNote">No versions yet</p> : null}
                </div>
              </section>

              <section className="configSection">
                <h4>Compare</h4>
                <div className="evalForm">
                  <label>
                    Old
                    <select value={oldCommitId} onChange={(event) => setOldCommitId(event.target.value)}>
                      <option value="">Select old</option>
                      {versions.map((version) => (
                        <option key={version.commit_id} value={version.commit_id}>{version.commit_id}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    New
                    <select value={newCommitId} onChange={(event) => setNewCommitId(event.target.value)}>
                      <option value="">Select new</option>
                      {versions.map((version) => (
                        <option key={version.commit_id} value={version.commit_id}>{version.commit_id}</option>
                      ))}
                    </select>
                  </label>
                  <button onClick={() => void compareConfigVersions()}>
                    <FileSearch size={15} />
                    Compare
                  </button>
                </div>
                {comparison ? <pre>{comparison.content_diff || "No content changes"}</pre> : null}
                {comparison ? <AgentConfigDiffSummary comparison={comparison} /> : null}
              </section>
            </div>
          </>
        ) : (
          <div className="emptyState">{stateText}</div>
        )}
      </section>
    </div>
  );
}

function OpsWorkspace(props: {
  client: OpenAbmClient;
  connection: ConnectionState;
  projectId: string;
}) {
  const { client, connection, projectId } = props;
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [ready, setReady] = useState<HealthStatus | null>(null);
  const [metricsText, setMetricsText] = useState("");
  const [opsStatus, setOpsStatus] = useState<OpsStatus | null>(null);
  const [similarityIndex, setSimilarityIndex] = useState<SimilarityIndexSummary | null>(null);
  const [similarityRebuildLimit, setSimilarityRebuildLimit] = useState("500");
  const [similarityRebuildResult, setSimilarityRebuildResult] = useState<SimilarityIndexRebuildResult | null>(null);
  const [deadLetterRuns, setDeadLetterRuns] = useState<AutomationRun[]>([]);
  const [authContract, setAuthContract] = useState<AuthContract | null>(null);
  const [authApiKeys, setAuthApiKeys] = useState<AuthApiKey[]>([]);
  const [authUsers, setAuthUsers] = useState<AuthUser[]>([]);
  const [authInvites, setAuthInvites] = useState<AuthInvite[]>([]);
  const [authInviteDeliveries, setAuthInviteDeliveries] = useState<AuthInviteDelivery[]>([]);
  const [authSessions, setAuthSessions] = useState<AuthSession[]>([]);
  const [apiKeyName, setApiKeyName] = useState("Local evaluator key");
  const [apiKeyRole, setApiKeyRole] = useState("developer");
  const [newApiKeySecret, setNewApiKeySecret] = useState("");
  const [authEmail, setAuthEmail] = useState("teammate@example.com");
  const [authRole, setAuthRole] = useState("viewer");
  const [secretBackend, setSecretBackend] = useState<SecretBackendStatus | null>(null);
  const [secretRefs, setSecretRefs] = useState<SecretRef[]>([]);
  const [selectedSecretRef, setSelectedSecretRef] = useState("");
  const [secretPurpose, setSecretPurpose] = useState("notification_webhook");
  const [secretValue, setSecretValue] = useState("");
  const [secretAccessLog, setSecretAccessLog] = useState<SecretAccessLogEntry[]>([]);
  const [retentionPolicies, setRetentionPolicies] = useState<RetentionPolicy[]>([]);
  const [selectedRetentionId, setSelectedRetentionId] = useState("");
  const [retentionName, setRetentionName] = useState("Short lived traces");
  const [retentionTtlDays, setRetentionTtlDays] = useState("0");
  const [retentionStatus, setRetentionStatus] = useState<RetentionPolicy["status"]>("active");
  const [retentionResult, setRetentionResult] = useState<RetentionApplyResult | null>(null);
  const [includePayloads, setIncludePayloads] = useState(false);
  const [exportBundle, setExportBundle] = useState<ProjectExportBundle | null>(null);
  const [classificationPolicies, setClassificationPolicies] = useState<DataClassificationPolicy[]>([]);
  const [selectedClassificationId, setSelectedClassificationId] = useState("");
  const [defaultClassification, setDefaultClassification] = useState("internal");
  const [rulePath, setRulePath] = useState("customer.email");
  const [ruleClassification, setRuleClassification] = useState("confidential");
  const [payloadText, setPayloadText] = useState(
    JSON.stringify({ customer: { email: "zach@example.com" }, message: "Need refund status." }, null, 2)
  );
  const [maxClassification, setMaxClassification] = useState("internal");
  const [classificationResult, setClassificationResult] = useState<ClassificationResult | null>(null);
  const [stateText, setStateText] = useState("Operations need a live API");

  const selectedRetentionPolicy =
    retentionPolicies.find((policy) => policy.retention_policy_id === selectedRetentionId) ??
    retentionPolicies[0] ??
    null;
  const selectedClassificationPolicy =
    classificationPolicies.find((policy) => policy.policy_id === selectedClassificationId) ??
    classificationPolicies[0] ??
    null;
  const exportSections = Object.entries(exportBundle?.manifest.sections ?? {});
  const authRoles = Object.keys(authContract?.role_matrix ?? {
    viewer: [],
    developer: [],
    admin: [],
    owner: []
  });
  const activeApiKeyCount = authApiKeys.filter((key) => key.status === "active").length;
  const activeSessionCount = authSessions.filter((session) => session.status === "active").length;
  const selectedSecret =
    secretRefs.find((secret) => secret.secret_ref === selectedSecretRef) ??
    secretRefs[0] ??
    null;
  const workerHeartbeats = opsStatus?.worker_heartbeats ?? [];
  const workerHealth = opsStatus?.worker_health ?? [];
  const workerHealthById = new Map(workerHealth.map((item) => [item.worker_id, item]));
  const storageRows = Object.values(opsStatus?.storage_growth ?? {}).reduce((sum, count) => sum + count, 0);
  const queueDepth = opsStatus?.queue_depth.worker_jobs ?? 0;
  const similarityTraceCount =
    similarityIndex?.representations
      .filter((item) => item.entity_type === "trace")
      .reduce((sum, item) => sum + item.count, 0) ?? 0;
  const latestSimilarityRepresentation =
    similarityIndex?.representations.find((item) => item.entity_type === "trace") ?? null;

  async function loadOps() {
    if (connection !== "live") {
      setHealth(null);
      setReady(null);
      setMetricsText("");
      setOpsStatus(null);
      setSimilarityIndex(null);
      setSimilarityRebuildResult(null);
      setDeadLetterRuns([]);
      setAuthContract(null);
      setAuthApiKeys([]);
      setAuthUsers([]);
      setAuthInvites([]);
      setAuthInviteDeliveries([]);
      setAuthSessions([]);
      setSecretBackend(null);
      setSecretRefs([]);
      setSecretAccessLog([]);
      setRetentionPolicies([]);
      setClassificationPolicies([]);
      setStateText("fixture mode");
      return;
    }
    try {
      const [
        healthStatus,
        readyStatus,
        metrics,
        status,
        similarity,
        deadLetters,
        contract,
        apiKeys,
        users,
        invites,
        inviteDeliveries,
        sessions,
        secretStatus,
        secrets,
        retention,
        classifications
      ] = await Promise.all([
        client.getHealth(),
        client.getReady(),
        client.getMetricsText(),
        client.getOpsStatus(projectId),
        client.getSimilarityIndex(projectId),
        client.listDeadLetterRuns(projectId),
        client.getAuthContract(),
        client.listAuthApiKeys(projectId),
        client.listAuthUsers(projectId),
        client.listAuthInvites(projectId),
        client.listAuthInviteDeliveries(projectId),
        client.listAuthSessions(projectId),
        client.getSecretBackend(),
        client.listSecretRefs(projectId),
        client.listRetentionPolicies(projectId),
        client.listDataClassificationPolicies(projectId)
      ]);
      setHealth(healthStatus);
      setReady(readyStatus);
      setMetricsText(metrics || "No counters emitted yet");
      setOpsStatus(status);
      setSimilarityIndex(similarity);
      setDeadLetterRuns(deadLetters);
      setAuthContract(contract);
      setAuthApiKeys(apiKeys);
      setAuthUsers(users);
      setAuthInvites(invites);
      setAuthInviteDeliveries(inviteDeliveries);
      setAuthSessions(sessions);
      setSecretBackend(secretStatus);
      setSecretRefs(secrets);
      setSelectedSecretRef((current) =>
        secrets.some((secret) => secret.secret_ref === current)
          ? current
          : secrets[0]?.secret_ref ?? ""
      );
      setRetentionPolicies(retention);
      setSelectedRetentionId((current) =>
        retention.some((policy) => policy.retention_policy_id === current)
          ? current
          : retention[0]?.retention_policy_id ?? ""
      );
      setClassificationPolicies(classifications);
      setSelectedClassificationId((current) =>
        classifications.some((policy) => policy.policy_id === current)
          ? current
          : classifications[0]?.policy_id ?? ""
      );
      setStateText("operations refreshed");
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "operations refresh failed");
    }
  }

  useEffect(() => {
    void loadOps();
  }, [client, connection, projectId]);

  useEffect(() => {
    void loadSecretAccessLog();
  }, [selectedSecretRef]);

  async function sendWorkerHeartbeat() {
    if (connection !== "live") return;
    try {
      const heartbeat = await client.recordWorkerHeartbeat(projectId, "web-ops-preview", queueDepth);
      setOpsStatus((current) => current ? {
        ...current,
        queue_depth: { ...current.queue_depth, worker_jobs: heartbeat.queue_depth },
        worker_heartbeats: [
          heartbeat,
          ...current.worker_heartbeats.filter((item) => item.worker_id !== heartbeat.worker_id)
        ],
        worker_health: [
          {
            worker_id: heartbeat.worker_id,
            worker_type: heartbeat.worker_type,
            status: "healthy",
            reported_status: heartbeat.status,
            queue_depth: heartbeat.queue_depth,
            last_seen_at: heartbeat.last_seen_at,
            last_seen_age_seconds: 0,
            stale_after_seconds: 900
          },
          ...current.worker_health.filter((item) => item.worker_id !== heartbeat.worker_id)
        ],
        stale_worker_count: current.worker_health.filter(
          (item) => item.worker_id !== heartbeat.worker_id && item.status !== "healthy"
        ).length
      } : current);
      setStateText(`heartbeat ${heartbeat.worker_id}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "worker heartbeat failed");
    }
  }

  async function rebuildSimilarityIndex() {
    if (connection !== "live") return;
    const limit = Math.max(1, Number(similarityRebuildLimit) || 500);
    try {
      const result = await client.rebuildSimilarityIndex(projectId, limit);
      const summary = await client.getSimilarityIndex(projectId);
      setSimilarityRebuildResult(result);
      setSimilarityIndex(summary);
      setStateText(`indexed ${result.indexed_counts.trace ?? 0} traces`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "similarity index rebuild failed");
    }
  }

  async function createLocalApiKey() {
    if (connection !== "live" || !apiKeyName.trim()) return;
    try {
      const created = await client.createAuthApiKey(projectId, apiKeyName.trim(), apiKeyRole, ["*"]);
      setAuthApiKeys([created, ...authApiKeys.filter((key) => key.api_key_id !== created.api_key_id)]);
      setNewApiKeySecret(created.api_key ?? "");
      setStateText(`created ${created.name}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "API key creation failed");
    }
  }

  async function revokeLocalApiKey(apiKeyId: string) {
    if (connection !== "live") return;
    if (!window.confirm("Revoke this API key?")) return;
    try {
      const revoked = await client.revokeAuthApiKey(projectId, apiKeyId);
      setAuthApiKeys(authApiKeys.map((key) => (key.api_key_id === apiKeyId ? revoked : key)));
      setNewApiKeySecret("");
      setStateText(`revoked ${revoked.name}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "API key revoke failed");
    }
  }

  async function createLocalAuthUser() {
    if (connection !== "live" || !authEmail.trim()) return;
    try {
      const created = await client.createAuthUser(projectId, authEmail.trim(), authRole);
      setAuthUsers([created, ...authUsers.filter((user) => user.user_id !== created.user_id)]);
      setStateText(`created user ${created.email}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "auth user creation failed");
    }
  }

  async function createLocalInvite() {
    if (connection !== "live" || !authEmail.trim()) return;
    try {
      const created = await client.createAuthInvite(projectId, authEmail.trim(), authRole);
      setAuthInvites([created, ...authInvites]);
      if (created.delivery) {
        setAuthInviteDeliveries([created.delivery, ...authInviteDeliveries]);
      }
      setStateText(`invited ${created.email}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "invite creation failed");
    }
  }

  async function createLocalAuthSession(userId: string) {
    if (connection !== "live") return;
    try {
      const created = await client.createAuthSession(projectId, userId);
      setAuthSessions([created, ...authSessions]);
      setStateText(`created session ${created.auth_session_id}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "auth session creation failed");
    }
  }

  async function revokeLocalAuthSession(sessionId: string) {
    if (connection !== "live") return;
    try {
      const revoked = await client.revokeAuthSession(projectId, sessionId);
      setAuthSessions(authSessions.map((session) => (
        session.auth_session_id === sessionId ? revoked : session
      )));
      setStateText(`revoked session ${revoked.auth_session_id}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "auth session revoke failed");
    }
  }

  async function loadSecretAccessLog(secretRef = selectedSecret?.secret_ref) {
    if (connection !== "live" || !secretRef) {
      setSecretAccessLog([]);
      return;
    }
    try {
      const log = await client.listSecretAccessLog(projectId, secretRef);
      setSecretAccessLog(log);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "secret access log failed");
    }
  }

  async function createLocalSecretRef() {
    if (connection !== "live" || !secretPurpose.trim() || !secretValue) return;
    try {
      const created = await client.createSecretRef(projectId, secretPurpose.trim(), secretValue);
      setSecretRefs([created, ...secretRefs.filter((secret) => secret.secret_ref !== created.secret_ref)]);
      setSelectedSecretRef(created.secret_ref);
      setSecretValue("");
      setStateText(`created secret ref ${created.secret_ref}`);
      void loadSecretAccessLog(created.secret_ref);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "secret creation failed");
    }
  }

  async function rotateLocalSecretRef() {
    if (connection !== "live" || !selectedSecret || !secretValue) return;
    try {
      const rotated = await client.rotateSecretRef(projectId, selectedSecret.secret_ref, secretValue);
      setSecretRefs(secretRefs.map((secret) => (
        secret.secret_ref === rotated.secret_ref ? rotated : secret
      )));
      setSecretValue("");
      setStateText(`rotated ${rotated.secret_ref}`);
      void loadSecretAccessLog(rotated.secret_ref);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "secret rotation failed");
    }
  }

  async function createRetentionPolicy() {
    if (connection !== "live" || !retentionName.trim()) return;
    const ttlDays = Number.parseInt(retentionTtlDays, 10);
    if (!Number.isFinite(ttlDays) || ttlDays < 0) {
      setStateText("ttl_days must be a non-negative integer");
      return;
    }
    try {
      const created = await client.createRetentionPolicy(
        projectId,
        retentionName.trim(),
        [{ entity: "traces", ttl_days: ttlDays }],
        retentionStatus
      );
      const nextPolicies = [created, ...retentionPolicies.filter((policy) => policy.retention_policy_id !== created.retention_policy_id)];
      setRetentionPolicies(nextPolicies);
      setSelectedRetentionId(created.retention_policy_id);
      setRetentionResult(null);
      setStateText(`created ${created.name}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "retention policy creation failed");
    }
  }

  async function applyRetentionPolicy(dryRun: boolean) {
    if (connection !== "live" || !selectedRetentionPolicy) return;
    if (!dryRun && !window.confirm(`Apply ${selectedRetentionPolicy.name} and tombstone matching traces?`)) {
      return;
    }
    try {
      const result = await client.applyRetentionPolicy(projectId, selectedRetentionPolicy.retention_policy_id, dryRun);
      setRetentionResult(result);
      setStateText(
        dryRun
          ? `planned ${result.candidate_trace_ids.length} candidates`
          : `deleted ${result.deleted_trace_ids.length} traces`
      );
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "retention apply failed");
    }
  }

  async function exportProject() {
    if (connection !== "live") return;
    try {
      const bundle = await client.exportProject(projectId, includePayloads);
      setExportBundle(bundle);
      setStateText(`export ${bundle.manifest.export_id}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "project export failed");
    }
  }

  async function createClassificationPolicy() {
    if (connection !== "live") return;
    if (!rulePath.trim() || !ruleClassification.trim()) {
      setStateText("classification rule path and value are required");
      return;
    }
    try {
      const created = await client.createDataClassificationPolicy(projectId, defaultClassification, [
        { path: rulePath.trim(), classification: ruleClassification.trim() }
      ]);
      const nextPolicies = [
        created,
        ...classificationPolicies.filter((policy) => policy.policy_id !== created.policy_id)
      ];
      setClassificationPolicies(nextPolicies);
      setSelectedClassificationId(created.policy_id);
      setClassificationResult(null);
      setStateText(`created classification policy ${created.policy_id}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "classification policy creation failed");
    }
  }

  async function classifyPayload() {
    if (connection !== "live" || !selectedClassificationPolicy) return;
    let payload: Record<string, unknown>;
    try {
      payload = parseJsonObject(payloadText);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "invalid payload JSON");
      return;
    }
    try {
      const result = await client.classifyPayload(payload, selectedClassificationPolicy, maxClassification.trim() || undefined);
      setClassificationResult(result);
      setStateText(`classified as ${result.classification}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "classification failed");
    }
  }

  return (
    <div className="opsGrid">
      <section className="panel opsDetail">
        <div className="detailHeader">
          <div>
            <p className="sectionLabel">runtime</p>
            <h3>Health, metrics, and export</h3>
          </div>
          <button className="iconButton" onClick={() => void loadOps()} aria-label="Refresh operations">
            <TimerReset size={16} />
          </button>
        </div>
        <div className="metricsRow opsMetrics">
          <Metric icon={<Activity />} label="Health" value={health?.status ?? connectionLabel(connection)} />
          <Metric icon={<CheckCircle2 />} label="Ready" value={ready?.status ?? "unknown"} />
          <Metric icon={<Database />} label="Counters" value={String(countMetricLines(metricsText))} />
          <Metric icon={<AlertTriangle />} label="Dead letters" value={String(opsStatus?.dead_letter_count ?? 0)} />
          <Metric icon={<Shield />} label="Worker risk" value={String(opsStatus?.stale_worker_count ?? 0)} />
        </div>
        <p className="systemNote">{stateText}</p>

        <div className="opsSections">
          <section className="opsSection">
            <h4>Readiness</h4>
            <dl className="reviewFacts">
              <div>
                <dt>Service</dt>
                <dd>{health?.service ?? "not connected"}</dd>
              </div>
              <div>
                <dt>Environment</dt>
                <dd>{String(health?.details?.env ?? "unknown")}</dd>
              </div>
              <div>
                <dt>Store</dt>
                <dd>{String(ready?.details?.store ?? "unknown")}</dd>
              </div>
              <div>
                <dt>Generated</dt>
                <dd>{opsStatus ? formatTime(opsStatus.generated_at) : "unknown"}</dd>
              </div>
            </dl>
          </section>

          <section className="opsSection">
            <h4>Admin status</h4>
            <div className="metricsRow compactMetrics">
              <Metric icon={<Database />} label="Rows" value={String(storageRows)} />
              <Metric icon={<Box />} label="Payload bytes" value={String(opsStatus?.payload_store_growth.total_bytes ?? 0)} />
              <Metric icon={<Activity />} label="Queue" value={String(queueDepth)} />
              <Metric icon={<Network />} label="MCP calls" value={String(opsStatus?.mcp_tool_observability.total_calls ?? 0)} />
            </div>
            <dl className="reviewFacts">
              <div>
                <dt>Open reviews</dt>
                <dd>{String(opsStatus?.queue_depth.open_review_tasks ?? 0)}</dd>
              </div>
              <div>
                <dt>Retention job</dt>
                <dd>{opsStatus?.retention_job_status ? "recorded" : "none recorded"}</dd>
              </div>
              <div>
                <dt>Automation failures</dt>
                <dd>{String(opsStatus?.automation_action_failures ?? 0)}</dd>
              </div>
              <div>
                <dt>MCP errors</dt>
                <dd>{String(opsStatus?.mcp_tool_observability.error_count ?? 0)}</dd>
              </div>
            </dl>
            <button onClick={() => void sendWorkerHeartbeat()}>
              <Activity size={15} />
              Send heartbeat
            </button>
            <div className="sectionRows">
              {workerHeartbeats.slice(0, 4).map((heartbeat) => (
                <div key={heartbeat.worker_id}>
                  <strong>{heartbeat.worker_id}</strong>
                  <span>
                    {heartbeat.worker_type} · {workerHealthById.get(heartbeat.worker_id)?.status ?? heartbeat.status} · queue {heartbeat.queue_depth}
                  </span>
                  <small>{formatTime(heartbeat.last_seen_at)}</small>
                </div>
              ))}
              {!workerHeartbeats.length ? <div className="emptyState">No worker heartbeats</div> : null}
            </div>
            <div className="sectionRows">
              {(opsStatus?.mcp_tool_observability.tools ?? []).slice(0, 4).map((tool) => (
                <div key={tool.tool_name}>
                  <strong>{tool.tool_name}</strong>
                  <span>{tool.call_count} calls · {tool.error_count} errors</span>
                  <small>{Math.round(tool.avg_latency_ms)} ms avg · {tool.max_latency_ms} ms max</small>
                </div>
              ))}
              {opsStatus && !opsStatus.mcp_tool_observability.tools.length ? <div className="emptyState">No MCP calls recorded</div> : null}
            </div>
            <div className="sectionRows">
              {deadLetterRuns.slice(0, 4).map((run) => (
                <div key={run.automation_run_id}>
                  <strong>{run.status}</strong>
                  <span>{run.automation_id} · {formatTime(run.started_at)}</span>
                </div>
              ))}
              {!deadLetterRuns.length ? <div className="emptyState">No dead-letter runs</div> : null}
            </div>
          </section>

          <section className="opsSection">
            <h4>Similarity index</h4>
            <div className="metricsRow compactMetrics">
              <Metric icon={<Network />} label="Trace vectors" value={String(similarityTraceCount)} />
              <Metric
                icon={<Database />}
                label="Representations"
                value={String(similarityIndex?.representations.length ?? 0)}
              />
              <Metric
                icon={<Activity />}
                label="Latest"
                value={latestSimilarityRepresentation?.representation_version ?? "none"}
              />
            </div>
            <div className="inlineControls">
              <input
                value={similarityRebuildLimit}
                onChange={(event) => setSimilarityRebuildLimit(event.target.value)}
                placeholder="limit"
              />
              <button onClick={() => void rebuildSimilarityIndex()}>
                <Network size={15} />
                Rebuild
              </button>
            </div>
            <div className="sectionRows">
              {(similarityIndex?.representations ?? []).slice(0, 6).map((item) => (
                <div key={`${item.representation_version}:${item.entity_type}`}>
                  <strong>{item.entity_type}</strong>
                  <span>{item.count} vectors · {item.representation_version}</span>
                  <small>{item.last_updated_at ? formatTime(item.last_updated_at) : "never"}</small>
                </div>
              ))}
              {similarityIndex && !similarityIndex.representations.length ? (
                <div className="emptyState">No similarity index records</div>
              ) : null}
            </div>
            {similarityRebuildResult ? (
              <div className="exportSummary">
                <strong>{similarityRebuildResult.representation_version ?? "index"}</strong>
                <span>
                  traces {similarityRebuildResult.indexed_counts.trace ?? 0} · spans {similarityRebuildResult.indexed_counts.span ?? 0}
                </span>
              </div>
            ) : null}
          </section>

          <section className="opsSection authSection">
            <h4>Auth and access</h4>
            <div className="metricsRow compactMetrics">
              <Metric icon={<Shield />} label="Mode" value={authContract?.active_auth_mode ?? "unknown"} />
              <Metric icon={<KeyRound />} label="Active keys" value={String(activeApiKeyCount)} />
              <Metric icon={<Activity />} label="Sessions" value={String(activeSessionCount)} />
            </div>
            <dl className="reviewFacts">
              <div>
                <dt>Password decision</dt>
                <dd>{authContract?.password_or_passwordless_decision ?? "unknown"}</dd>
              </div>
              <div>
                <dt>CSRF</dt>
                <dd>{String(authContract?.csrf_policy?.required_for_mutating_requests ?? "unknown")}</dd>
              </div>
              <div>
                <dt>IdP boundary</dt>
                <dd>{String(authContract?.external_identity_provider_integration_point?.status ?? "unknown")}</dd>
              </div>
            </dl>

            <div className="inlineControls">
              <input value={apiKeyName} onChange={(event) => setApiKeyName(event.target.value)} />
              <select value={apiKeyRole} onChange={(event) => setApiKeyRole(event.target.value)}>
                {authRoles.map((role) => (
                  <option key={role} value={role}>{role}</option>
                ))}
              </select>
              <button onClick={() => void createLocalApiKey()}>
                <KeyRound size={15} />
                Create key
              </button>
            </div>
            {newApiKeySecret ? (
              <div className="secretReveal">
                <strong>New key</strong>
                <code>{newApiKeySecret}</code>
              </div>
            ) : null}
            <div className="sectionRows">
              {authApiKeys.slice(0, 5).map((key) => (
                <div key={key.api_key_id}>
                  <strong>{key.name}</strong>
                  <span>{key.role} · {key.status} · {key.scopes.join(", ")}</span>
                  {key.status === "active" ? (
                    <button onClick={() => void revokeLocalApiKey(key.api_key_id)}>Revoke</button>
                  ) : null}
                </div>
              ))}
              {!authApiKeys.length ? <div className="emptyState">No API keys</div> : null}
            </div>

            <div className="inlineControls">
              <input value={authEmail} onChange={(event) => setAuthEmail(event.target.value)} />
              <select value={authRole} onChange={(event) => setAuthRole(event.target.value)}>
                {authRoles.map((role) => (
                  <option key={role} value={role}>{role}</option>
                ))}
              </select>
              <button onClick={() => void createLocalAuthUser()}>
                <Shield size={15} />
                Add user
              </button>
              <button onClick={() => void createLocalInvite()}>
                <FileSearch size={15} />
                Invite
              </button>
            </div>
            <div className="sectionRows">
              {authUsers.slice(0, 5).map((user) => (
                <div key={user.user_id}>
                  <strong>{user.email}</strong>
                  <span>{String(user.membership?.role ?? "no role")} · {user.status}</span>
                  <button onClick={() => void createLocalAuthSession(user.user_id)}>New session</button>
                </div>
              ))}
              {!authUsers.length ? <div className="emptyState">No auth users</div> : null}
            </div>
            <div className="sectionRows">
              {authSessions.slice(0, 3).map((session) => (
                <div key={session.auth_session_id}>
                  <strong>{session.email}</strong>
                  <span>{session.status} · expires {formatTime(session.expires_at)}</span>
                  {session.status === "active" ? (
                    <button onClick={() => void revokeLocalAuthSession(session.auth_session_id)}>Revoke</button>
                  ) : null}
                </div>
              ))}
              {authInvites.slice(0, 3).map((invite) => (
                <div key={invite.invite_id}>
                  <strong>{invite.email}</strong>
                  <span>
                    {invite.role} invite · {invite.status} · {invite.delivery?.delivery_status ?? "not queued"}
                  </span>
                </div>
              ))}
            </div>
            <div className="sectionRows">
              {authInviteDeliveries.slice(0, 3).map((delivery) => (
                <div key={delivery.invite_delivery_id}>
                  <strong>{delivery.recipient_email}</strong>
                  <span>{delivery.delivery_channel} · {delivery.delivery_status}</span>
                  <small>{formatTime(delivery.created_at)}</small>
                </div>
              ))}
              {!authInviteDeliveries.length ? <div className="emptyState">No invite deliveries</div> : null}
            </div>
          </section>

          <section className="opsSection">
            <h4>Metrics</h4>
            <pre>{metricsText || "No metrics loaded"}</pre>
          </section>

          <section className="opsSection secretSection">
            <h4>Secrets</h4>
            <div className="metricsRow compactMetrics">
              <Metric icon={<KeyRound />} label="Mode" value={secretBackend?.active_mode ?? "unknown"} />
              <Metric icon={<Shield />} label="Plaintext storage" value={String(secretBackend?.plaintext_storage ?? "unknown")} />
              <Metric icon={<Database />} label="Refs" value={String(secretRefs.length)} />
            </div>
            <dl className="reviewFacts">
              <div>
                <dt>Local encryption</dt>
                <dd>{String(secretBackend?.local_development_secret_mode?.encryption ?? "unknown")}</dd>
              </div>
              <div>
                <dt>External provider</dt>
                <dd>{String(secretBackend?.production_external_secret_manager_integration_point?.status ?? "unknown")}</dd>
              </div>
              <div>
                <dt>Sandbox mount</dt>
                <dd>{secretBackend?.sandbox_mount_default ?? "unknown"}</dd>
              </div>
            </dl>
            <div className="inlineControls">
              <input
                value={secretPurpose}
                onChange={(event) => setSecretPurpose(event.target.value)}
                placeholder="purpose"
              />
              <input
                type="password"
                value={secretValue}
                onChange={(event) => setSecretValue(event.target.value)}
                placeholder="secret value"
              />
              <button onClick={() => void createLocalSecretRef()}>
                <KeyRound size={15} />
                Create secret
              </button>
              <button onClick={() => void rotateLocalSecretRef()} disabled={!selectedSecret}>
                <TimerReset size={15} />
                Rotate
              </button>
            </div>
            <div className="sectionRows">
              {secretRefs.slice(0, 6).map((secret) => (
                <button
                  className={secret.secret_ref === selectedSecret?.secret_ref ? "selectedRetention" : ""}
                  key={secret.secret_ref}
                  onClick={() => setSelectedSecretRef(secret.secret_ref)}
                >
                  <strong>{secret.secret_ref}</strong>
                  <span>
                    {secret.purpose} · v{secret.current_version} · {secret.encryption_mode}
                  </span>
                  <small>{secret.redacted_value} · {secret.ciphertext_sha256.slice(0, 12)}</small>
                </button>
              ))}
              {!secretRefs.length ? <div className="emptyState">No secret refs</div> : null}
            </div>
            {selectedSecret ? (
              <div className="exportSummary">
                <strong>{selectedSecret.secret_ref}</strong>
                <span>{selectedSecret.status} · updated {formatTime(selectedSecret.updated_at)}</span>
                <div className="sectionRows">
                  {secretAccessLog.slice(0, 5).map((entry) => (
                    <div key={entry.secret_access_id}>
                      <strong>{entry.action}</strong>
                      <span>{entry.actor_id ?? "unknown"} · {formatTime(entry.created_at)}</span>
                    </div>
                  ))}
                  {!secretAccessLog.length ? <div className="emptyState">No access log</div> : null}
                </div>
              </div>
            ) : null}
          </section>

          <section className="opsSection exportSection">
            <h4>Project export</h4>
            <label className="toggleLabel">
              <input
                type="checkbox"
                checked={includePayloads}
                onChange={(event) => setIncludePayloads(event.target.checked)}
              />
              Include payload bodies
            </label>
            <button className="primaryButton" onClick={() => void exportProject()}>
              <Database size={15} />
              Export manifest
            </button>
            {exportBundle ? (
              <div className="exportSummary">
                <strong>{exportBundle.manifest.export_id}</strong>
                <span>{formatTime(exportBundle.manifest.created_at)} · {exportSections.length} sections</span>
                <div className="sectionRows">
                  {exportSections.map(([name, section]) => (
                    <div key={name}>
                      <strong>{name}</strong>
                      <span>{section.count} rows · {section.sha256.slice(0, 12)}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </section>

          <section className="opsSection classificationSection">
            <h4>Classification check</h4>
            <div className="inlineControls">
              <input
                value={defaultClassification}
                onChange={(event) => setDefaultClassification(event.target.value)}
                placeholder="default"
              />
              <input
                value={ruleClassification}
                onChange={(event) => setRuleClassification(event.target.value)}
                placeholder="rule classification"
              />
            </div>
            <input value={rulePath} onChange={(event) => setRulePath(event.target.value)} placeholder="payload.path" />
            <button onClick={() => void createClassificationPolicy()}>
              <Shield size={15} />
              Create policy
            </button>
            <select
              value={selectedClassificationPolicy?.policy_id ?? ""}
              onChange={(event) => setSelectedClassificationId(event.target.value)}
            >
              <option value="">Select policy</option>
              {classificationPolicies.map((policy) => (
                <option key={policy.policy_id} value={policy.policy_id}>
                  {policy.default_classification} · {policy.policy_id}
                </option>
              ))}
            </select>
            <label className="notesBox">
              Payload
              <textarea value={payloadText} onChange={(event) => setPayloadText(event.target.value)} />
            </label>
            <input
              value={maxClassification}
              onChange={(event) => setMaxClassification(event.target.value)}
              placeholder="max classification"
            />
            <button onClick={() => void classifyPayload()}>
              <FileSearch size={15} />
              Classify
            </button>
            {classificationResult ? <pre>{JSON.stringify(classificationResult, null, 2)}</pre> : null}
          </section>
        </div>
      </section>

      <section className="panel opsDetail">
        <div className="detailHeader">
          <div>
            <p className="sectionLabel">retention</p>
            <h3>Policy dry-run and tombstone</h3>
          </div>
          <span className="judgeStatus active">{retentionPolicies.length} policies</span>
        </div>
        <div className="opsSection">
          <h4>Create policy</h4>
          <div className="inlineControls">
            <input value={retentionName} onChange={(event) => setRetentionName(event.target.value)} placeholder="Policy name" />
            <input value={retentionTtlDays} onChange={(event) => setRetentionTtlDays(event.target.value)} placeholder="ttl_days" />
          </div>
          <select
            value={retentionStatus}
            onChange={(event) => setRetentionStatus(event.target.value as RetentionPolicy["status"])}
          >
            <option value="active">active</option>
            <option value="draft">draft</option>
            <option value="paused">paused</option>
            <option value="archived">archived</option>
          </select>
          <button onClick={() => void createRetentionPolicy()}>
            <Shield size={15} />
            Create retention policy
          </button>
        </div>

        <div className="retentionRows">
          {retentionPolicies.map((policy) => (
            <button
              className={policy.retention_policy_id === selectedRetentionPolicy?.retention_policy_id ? "selectedRetention" : ""}
              key={policy.retention_policy_id}
              onClick={() => {
                setSelectedRetentionId(policy.retention_policy_id);
                setRetentionResult(null);
              }}
            >
              <span className={`judgeStatus ${policy.status}`}>{policy.status}</span>
              <strong>{policy.name}</strong>
              <small>{formatRetentionRules(policy.rules)} · {policy.retention_policy_id}</small>
            </button>
          ))}
          {!retentionPolicies.length ? <div className="emptyState">No retention policies</div> : null}
        </div>

        {selectedRetentionPolicy ? (
          <div className="opsSection">
            <h4>Apply selected</h4>
            <div className="reviewActions">
              <button onClick={() => void applyRetentionPolicy(true)}>
                <FileSearch size={15} />
                Dry run
              </button>
              <button onClick={() => void applyRetentionPolicy(false)}>
                <AlertTriangle size={15} />
                Apply tombstone
              </button>
            </div>
            {retentionResult ? (
              <div className={`retentionResult ${retentionResult.status}`}>
                <strong>{retentionResult.status}</strong>
                <span>{retentionResult.candidate_trace_ids.length} candidates</span>
                <span>{retentionResult.deleted_trace_ids.length} deleted</span>
                <pre>{JSON.stringify(retentionResult, null, 2)}</pre>
              </div>
            ) : null}
          </div>
        ) : null}
      </section>
    </div>
  );
}

function IssueInvestigationWorkspace(props: {
  client: OpenAbmClient;
  connection: ConnectionState;
  projectId: string;
  traces: TraceEnvelope[];
  onOpenTrace: (traceId: string) => void;
}) {
  const { client, connection, projectId, traces } = props;
  const [issues, setIssues] = useState<IssueDefinition[]>([]);
  const [investigations, setInvestigations] = useState<InvestigationRun[]>([]);
  const [impactReports, setImpactReports] = useState<ImpactReport[]>([]);
  const [affectedEntities, setAffectedEntities] = useState<AffectedEntity[]>([]);
  const [contextPacks, setContextPacks] = useState<AgentContextPack[]>([]);
  const [issueLinks, setIssueLinks] = useState<IssueLink[]>([]);
  const [notificationTargets, setNotificationTargets] = useState<NotificationTarget[]>([]);
  const [selectedIssueId, setSelectedIssueId] = useState("");
  const [selectedInvestigationId, setSelectedInvestigationId] = useState("");
  const [selectedContextPackId, setSelectedContextPackId] = useState("");
  const [issueTitle, setIssueTitle] = useState("Refund workflow uses the wrong tool");
  const [issueDescription, setIssueDescription] = useState("Customer refund path appears to route through order lookup.");
  const [seedTraceId, setSeedTraceId] = useState("");
  const [seedSessionId, setSeedSessionId] = useState("");
  const [screenshotTitle, setScreenshotTitle] = useState("Screenshot shows refund failure");
  const [screenshotPayloadId, setScreenshotPayloadId] = useState("payload_screenshot_1");
  const [screenshotText, setScreenshotText] = useState("damaged order refund");
  const [screenshotAttachmentPayloadId, setScreenshotAttachmentPayloadId] = useState("payload_log_1");
  const [screenshotAttachmentText, setScreenshotAttachmentText] = useState("order lookup refund");
  const [screenshotResult, setScreenshotResult] = useState<ScreenshotIssueResult | null>(null);
  const [chatMessage, setChatMessage] = useState("Investigate damaged order refund failures");
  const [chatMaxClassification, setChatMaxClassification] = useState("internal");
  const [chatopsResult, setChatopsResult] = useState<ChatOpsInvestigationResult | null>(null);
  const [investigationProblem, setInvestigationProblem] = useState("refund failure");
  const [filterStatus, setFilterStatus] = useState("error");
  const [writeConfirmation, setWriteConfirmation] = useState(false);
  const [stateText, setStateText] = useState("Issues need a live API");

  const selectedIssue = issues.find((issue) => issue.issue_id === selectedIssueId) ?? issues[0] ?? null;
  const sessionIds = Array.from(new Set(traces.flatMap((trace) => (trace.session_id ? [trace.session_id] : [])))).sort();
  const issueInvestigations = selectedIssue
    ? investigations.filter((run) => run.issue_id_nullable === selectedIssue.issue_id)
    : investigations;
  const selectedInvestigation =
    issueInvestigations.find((run) => run.investigation_run_id === selectedInvestigationId) ??
    issueInvestigations[0] ??
    (!selectedIssue ? investigations[0] ?? null : null);
  const selectedImpact =
    investigationImpact(selectedInvestigation) ??
    (selectedIssue
      ? impactReports.find((report) => report.issue_id === selectedIssue.issue_id) ?? null
      : impactReports[0] ?? null);
  const selectedContextPack =
    contextPacks.find((pack) => pack.context_pack_id === selectedContextPackId) ??
    contextPacks[0] ??
    null;
  const evidenceTraceIds = stringsFromUnknown(selectedInvestigation?.result.evidence_trace_ids);
  const assistance = asRecord(selectedInvestigation?.result.model_assistance);
  const behaviorDrafts = recordsFrom(assistance.behavior_drafts);
  const rubricDrafts = recordsFrom(assistance.rubric_drafts);
  const evidenceSpanIds = recordsFrom(assistance.suspected_root_causes)
    .flatMap((cause) => stringsFromUnknown(cause.evidence_span_ids));
  const screenshotIntakeCounts = asRecord(screenshotResult?.intake_evidence.source_counts);

  async function loadIssues() {
    if (connection !== "live") {
      setIssues([]);
      setInvestigations([]);
      setImpactReports([]);
      setAffectedEntities([]);
      setContextPacks([]);
      setIssueLinks([]);
      setNotificationTargets([]);
      setStateText("fixture mode");
      return;
    }
    try {
      const [loadedIssues, loadedInvestigations, loadedReports, loadedTargets] = await Promise.all([
        client.listIssues(projectId),
        client.listInvestigations(projectId),
        client.listImpactReports(projectId),
        client.listNotificationTargets(projectId).catch(() => [] as NotificationTarget[])
      ]);
      setIssues(loadedIssues);
      setInvestigations(loadedInvestigations);
      setImpactReports(loadedReports);
      setNotificationTargets(loadedTargets);
      setSelectedIssueId((current) =>
        loadedIssues.some((issue) => issue.issue_id === current)
          ? current
          : loadedIssues[0]?.issue_id ?? ""
      );
      setSelectedInvestigationId((current) =>
        loadedInvestigations.some((run) => run.investigation_run_id === current)
          ? current
          : loadedInvestigations[0]?.investigation_run_id ?? ""
      );
      setStateText(
        `${loadedIssues.length} issues · ${loadedInvestigations.length} investigations · ${loadedTargets.length} targets`
      );
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "issue refresh failed");
    }
  }

  useEffect(() => {
    void loadIssues();
  }, [client, connection, projectId]);

  async function loadIssueLinks(issue: IssueDefinition | null = selectedIssue) {
    if (connection !== "live" || !issue) {
      setIssueLinks([]);
      return;
    }
    try {
      setIssueLinks(await client.listIssueLinks(projectId, issue.issue_id));
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "issue links unavailable");
    }
  }

  useEffect(() => {
    void loadIssueLinks();
  }, [client, connection, projectId, selectedIssue?.issue_id]);

  async function loadAffectedEntities(issue: IssueDefinition | null = selectedIssue) {
    if (connection !== "live" || !issue) {
      setAffectedEntities([]);
      return;
    }
    try {
      setAffectedEntities(await client.listAffectedEntities(projectId, issue.issue_id));
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "affected entities unavailable");
    }
  }

  useEffect(() => {
    void loadAffectedEntities();
  }, [client, connection, projectId, selectedIssue?.issue_id]);

  async function loadContextPacks(issue: IssueDefinition | null = selectedIssue) {
    if (connection !== "live") {
      setContextPacks([]);
      setSelectedContextPackId("");
      return;
    }
    try {
      const loaded = await client.listContextPacks(projectId, issue?.issue_id);
      setContextPacks(loaded);
      setSelectedContextPackId((current) =>
        loaded.some((pack) => pack.context_pack_id === current)
          ? current
          : loaded[0]?.context_pack_id ?? ""
      );
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "context packs unavailable");
    }
  }

  useEffect(() => {
    void loadContextPacks();
  }, [client, connection, projectId, selectedIssue?.issue_id]);

  async function createManualIssue() {
    if (connection !== "live" || !issueTitle.trim()) return;
    try {
      const created = await client.createIssue(projectId, {
        title: issueTitle.trim(),
        description: issueDescription.trim(),
        seedTraceId: seedTraceId || undefined,
        seedSessionId: seedSessionId || undefined
      });
      setIssues((current) => [created, ...current.filter((issue) => issue.issue_id !== created.issue_id)]);
      setSelectedIssueId(created.issue_id);
      setStateText(`created ${created.issue_id}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "issue creation failed");
    }
  }

  async function createScreenshotIssue() {
    if (connection !== "live" || !screenshotTitle.trim() || !screenshotPayloadId.trim()) return;
    try {
      const created = await client.createIssueFromScreenshot(projectId, {
        title: screenshotTitle.trim(),
        screenshotPayloadId: screenshotPayloadId.trim(),
        extractedText: screenshotText.trim(),
        attachmentPayloadId: screenshotAttachmentPayloadId.trim() || undefined,
        attachmentText: screenshotAttachmentText.trim() || undefined
      });
      setScreenshotResult(created);
      setIssues((current) => [created, ...current.filter((issue) => issue.issue_id !== created.issue_id)]);
      setSelectedIssueId(created.issue_id);
      setStateText(`screenshot issue created with ${created.candidate_seed_traces.length} seed candidates`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "screenshot issue failed");
    }
  }

  async function runChatopsIntake() {
    if (connection !== "live" || !chatMessage.trim()) return;
    try {
      const result = await client.chatopsInvestigate(
        projectId,
        chatMessage.trim(),
        seedTraceId || undefined,
        seedSessionId || undefined,
        { maxClassification: chatMaxClassification.trim() || "internal" }
      );
      setChatopsResult(result);
      if (result.issue && result.investigation_run) {
        setIssues((current) => [
          result.issue as IssueDefinition,
          ...current.filter((issue) => issue.issue_id !== result.issue?.issue_id)
        ]);
        setInvestigations((current) => [
          result.investigation_run as InvestigationRun,
          ...current.filter((run) => run.investigation_run_id !== result.investigation_run?.investigation_run_id)
        ]);
        setSelectedIssueId(result.issue.issue_id);
        setSelectedInvestigationId(result.investigation_run.investigation_run_id);
        setIssueLinks(await client.listIssueLinks(projectId, result.issue.issue_id));
      }
      setStateText(result.redacted ? "ChatOps artifacts created; response redacted" : "ChatOps artifacts created");
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "ChatOps intake failed");
    }
  }

  async function startSelectedInvestigation() {
    if (connection !== "live") return;
    const issueSeed = selectedIssue?.seed_trace_id_nullable || seedTraceId || undefined;
    const sessionSeed = selectedIssue?.seed_session_id_nullable || seedSessionId || undefined;
    try {
      const run = await client.startInvestigation(projectId, {
        issueId: selectedIssue?.issue_id,
        seedTraceId: issueSeed,
        seedSessionId: sessionSeed,
        problem: investigationProblem.trim() || selectedIssue?.title,
        filters: filterStatus ? { status: filterStatus } : {}
      });
      setInvestigations((current) => [run, ...current.filter((item) => item.investigation_run_id !== run.investigation_run_id)]);
      const impact = investigationImpact(run);
      if (impact) {
        setImpactReports((current) => [impact, ...current.filter((report) => report.report_id !== impact.report_id)]);
      }
      setSelectedInvestigationId(run.investigation_run_id);
      await loadIssueLinks();
      await loadAffectedEntities(selectedIssue);
      setStateText(`investigation ${run.status}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "investigation failed");
    }
  }

  async function createSelectedContextPack() {
    if (connection !== "live" || !selectedInvestigation) return;
    const traceIds = evidenceTraceIds.length
      ? evidenceTraceIds
      : selectedIssue?.seed_trace_id_nullable
        ? [selectedIssue.seed_trace_id_nullable]
        : seedTraceId
          ? [seedTraceId]
          : [];
    if (!traceIds.length) {
      setStateText("context pack needs at least one source trace");
      return;
    }
    try {
      const pack = await client.createContextPack(projectId, {
        issueId: selectedIssue?.issue_id,
        sourceTraceIds: traceIds,
        allowedNextActions: ["read", "draft_behavior", "draft_judge", "create_dataset"],
        classification: "internal"
      });
      setContextPacks((current) => [pack, ...current.filter((item) => item.context_pack_id !== pack.context_pack_id)]);
      setSelectedContextPackId(pack.context_pack_id);
      setStateText(`context pack ${pack.context_pack_id}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "context pack failed");
    }
  }

  async function createBehaviorFromDraft(draft: Record<string, unknown>) {
    if (!writeConfirmation || !window.confirm("Create behavior draft from this investigation?")) return;
    try {
      const name = String(draft.name ?? "investigation_behavior");
      const created = await client.createBehavior(projectId, {
        name,
        description: String(draft.description ?? "Investigation behavior draft."),
        severity: "medium",
        detector: { type: "manual_label", labels: [name] },
        issueId: selectedIssue?.issue_id,
        evidenceTraceIds: stringsFromUnknown(draft.positive_trace_ids).length
          ? stringsFromUnknown(draft.positive_trace_ids)
          : evidenceTraceIds,
        evidenceSpanIds
      });
      await loadIssueLinks();
      setStateText(`created behavior ${created.behavior_id}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "behavior draft action failed");
    }
  }

  async function createJudgeFromDraft(draft: Record<string, unknown>) {
    if (!writeConfirmation || !window.confirm("Create judge draft from this investigation?")) return;
    try {
      const name = String(draft.name ?? "Investigation rubric");
      const created = await client.createJudgeDraft(projectId, {
        name,
        description: "Investigation rubric draft.",
        judgeType: "rubric_judge",
        definition: {
          judge_type: "rubric_judge",
          rubric: {
            pass: String(draft.pass ?? "Trace satisfies the intended behavior."),
            fail: String(draft.fail ?? "Trace violates the intended behavior."),
            unsure: String(draft.unsure ?? "Trace lacks enough evidence.")
          },
          failure_modes: [name],
          evidence_trace_ids: stringsFromUnknown(draft.evidence_trace_ids)
        }
      });
      if (selectedIssue) {
        await client.createIssueLink(projectId, selectedIssue.issue_id, {
          targetType: "judge",
          targetId: created.judge_id,
          relation: "proposed_judge",
          source: "judge_draft_create",
          evidenceTraceIds: stringsFromUnknown(draft.evidence_trace_ids),
          evidenceSpanIds
        });
        await loadIssueLinks();
      }
      setStateText(`created judge ${created.judge_id}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "judge draft action failed");
    }
  }

  async function createDatasetFromInvestigation() {
    if (!writeConfirmation || !selectedInvestigation || !window.confirm("Create dataset from investigation traces?")) return;
    const traceIds = evidenceTraceIds.length ? evidenceTraceIds : selectedImpact?.representative_trace_ids ?? [];
    if (!traceIds.length) {
      setStateText("dataset action needs evidence traces");
      return;
    }
    try {
      const dataset = await client.createDataset(
        projectId,
        `Investigation ${shortIdentifier(selectedInvestigation.investigation_run_id)}`,
        selectedInvestigation.natural_language_problem_nullable ?? "Investigation evidence dataset",
        selectedIssue?.issue_id
      );
      await Promise.all(traceIds.map((traceId) => client.addTraceToDataset(projectId, dataset.dataset_id, traceId, ["investigation"], selectedIssue?.issue_id)));
      await loadIssueLinks();
      setStateText(`created dataset ${dataset.dataset_id}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "dataset draft action failed");
    }
  }

  async function updateAffectedEntityStatus(
    affectedEntityId: string,
    status: AffectedEntity["status"]
  ) {
    if (!writeConfirmation) {
      setStateText("enable Confirm writes before remediation updates");
      return;
    }
    if (!window.confirm(`Mark affected entity ${status.replace("_", " ")}?`)) return;
    try {
      const updated = await client.updateAffectedEntity(projectId, affectedEntityId, {
        status,
        notesNullable: `Marked ${status.replace("_", " ")} from impact workspace.`
      });
      setAffectedEntities((current) =>
        current.map((entity) =>
          entity.affected_entity_id === updated.affected_entity_id ? updated : entity
        )
      );
      setStateText(`affected entity ${shortIdentifier(updated.affected_entity_id)} marked ${updated.status}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "affected entity update failed");
    }
  }

  async function notifyAffectedEntity(affectedEntityId: string, targetId: string) {
    if (!writeConfirmation) {
      setStateText("enable Confirm writes before remediation notifications");
      return;
    }
    if (!window.confirm("Queue remediation notification for this affected entity?")) return;
    try {
      const result = await client.notifyAffectedEntity(projectId, affectedEntityId, {
        targetId,
        deliveryMode: "preview",
        message: `Remediation follow-up for ${affectedEntityId}`,
        groupKey: `affected_entity:${affectedEntityId}`
      });
      const status = String(result.notification.delivery_status ?? result.notification.status ?? "queued");
      setStateText(`affected entity notification ${status}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "affected entity notification failed");
    }
  }

  async function createAffectedEntityReviewTask(affectedEntityId: string) {
    if (!writeConfirmation) {
      setStateText("enable Confirm writes before review task creation");
      return;
    }
    if (!window.confirm("Create a review task for this affected entity?")) return;
    try {
      const task = await client.createAffectedEntityReviewTask(projectId, affectedEntityId, {
        notesNullable: `Review affected entity ${affectedEntityId} from impact workspace.`
      });
      setStateText(`review task ${shortIdentifier(task.review_task_id)} created`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "affected entity review task failed");
    }
  }

  async function exportSelectedAffectedEntities(format: "json" | "csv") {
    if (connection !== "live") return;
    try {
      const bundle = await client.exportAffectedEntities(projectId, selectedIssue?.issue_id);
      const issuePart = selectedIssue ? shortIdentifier(selectedIssue.issue_id) : "project";
      if (format === "csv") {
        downloadTextFile(
          `affected-entities-${issuePart}.csv`,
          bundle.affected_entities_csv,
          "text/csv"
        );
      } else {
        downloadJsonFile(`affected-entities-${issuePart}.json`, bundle);
      }
      setStateText(`exported ${bundle.affected_entities.length} affected entities`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "affected entity export failed");
    }
  }

  return (
    <div className="issueGrid">
      <section className="panel issueList">
        <div className="toolbar">
          <button className="iconButton" onClick={() => void loadIssues()} aria-label="Refresh issues">
            <TimerReset size={16} />
          </button>
          <span className="systemNote">{stateText}</span>
        </div>

        <div className="issueCreate">
          <input value={issueTitle} onChange={(event) => setIssueTitle(event.target.value)} placeholder="Issue title" />
          <input value={issueDescription} onChange={(event) => setIssueDescription(event.target.value)} placeholder="Description" />
          <select value={seedTraceId} onChange={(event) => setSeedTraceId(event.target.value)}>
            <option value="">No seed trace</option>
            {traces.map((trace) => (
              <option key={trace.trace_id} value={trace.trace_id}>
                {trace.trace_id} · {trace.status}
              </option>
            ))}
          </select>
          <select value={seedSessionId} onChange={(event) => setSeedSessionId(event.target.value)}>
            <option value="">No seed session</option>
            {sessionIds.map((sessionId) => (
              <option key={sessionId} value={sessionId}>
                {sessionId}
              </option>
            ))}
          </select>
          <button onClick={() => void createManualIssue()}>
            <AlertTriangle size={15} />
            Create issue
          </button>
        </div>

        <div className="issueCreate secondaryCreate">
          <input value={screenshotTitle} onChange={(event) => setScreenshotTitle(event.target.value)} placeholder="Screenshot issue title" />
          <input value={screenshotPayloadId} onChange={(event) => setScreenshotPayloadId(event.target.value)} placeholder="Screenshot payload id" />
          <input value={screenshotText} onChange={(event) => setScreenshotText(event.target.value)} placeholder="Extracted screenshot text" />
          <input value={screenshotAttachmentPayloadId} onChange={(event) => setScreenshotAttachmentPayloadId(event.target.value)} placeholder="Attachment payload id" />
          <input value={screenshotAttachmentText} onChange={(event) => setScreenshotAttachmentText(event.target.value)} placeholder="Attachment text" />
          <button onClick={() => void createScreenshotIssue()}>
            <FileSearch size={15} />
            Screenshot intake
          </button>
          {screenshotResult ? (
            <p className="systemNote">
              {screenshotResult.candidate_seed_traces.length} candidate seed traces,
              {" "}
              {String(screenshotIntakeCounts.payloads ?? 0)} payload source(s)
            </p>
          ) : null}
        </div>

        <div className="issueCreate secondaryCreate">
          <input value={chatMessage} onChange={(event) => setChatMessage(event.target.value)} placeholder="ChatOps message" />
          <input
            value={chatMaxClassification}
            onChange={(event) => setChatMaxClassification(event.target.value)}
            placeholder="max classification"
          />
          <button onClick={() => void runChatopsIntake()}>
            <Network size={15} />
            ChatOps investigate
          </button>
          {chatopsResult ? (
            <p className="systemNote">
              {chatopsResult.response} · {chatopsResult.classification}
              {chatopsResult.redacted ? " · redacted" : ""}
            </p>
          ) : null}
        </div>

        <div className="issueRows">
          {issues.map((issue) => (
            <button
              className={issue.issue_id === selectedIssue?.issue_id ? "selectedIssue" : ""}
              key={issue.issue_id}
              onClick={() => {
                setSelectedIssueId(issue.issue_id);
                const run = investigations.find((item) => item.issue_id_nullable === issue.issue_id);
                setSelectedInvestigationId(run?.investigation_run_id ?? "");
              }}
            >
              <span className={`reviewStatus ${issue.status}`}>{issue.status}</span>
              <strong>{issue.title}</strong>
              <small>{issue.source_type} · {issue.seed_trace_id_nullable ?? "no seed"} · {issue.issue_id}</small>
            </button>
          ))}
          {!issues.length ? <div className="emptyState">No issues</div> : null}
        </div>
      </section>

      <section className="panel issueDetail">
        {selectedIssue ? (
          <>
            <div className="detailHeader">
              <div>
                <p className="sectionLabel">issue</p>
                <h3>{selectedIssue.title}</h3>
              </div>
              <span className={`reviewStatus ${selectedIssue.status}`}>{selectedIssue.status}</span>
            </div>
            <p className="entityDescription">{selectedIssue.description || selectedIssue.issue_id}</p>
            <div className="metricsRow issueMetrics">
              <Metric icon={<AlertTriangle />} label="Source" value={selectedIssue.source_type} />
              <Metric icon={<FileSearch />} label="Seed trace" value={selectedIssue.seed_trace_id_nullable ?? "none"} />
              <Metric icon={<Database />} label="Seed session" value={selectedIssue.seed_session_id_nullable ?? "none"} />
              <Metric icon={<Activity />} label="Updated" value={formatTime(selectedIssue.updated_at)} />
            </div>

            <div className="issueSections">
              <section className="issueSection">
                <h4>Linked artifacts</h4>
                <div className="sectionRows">
                  {issueLinks.map((link) => (
                    <div key={link.issue_link_id}>
                      <strong>{link.target_type} · {link.relation}</strong>
                      <span>{link.target_id}</span>
                      {link.evidence_trace_ids.length ? (
                        <span>traces: {link.evidence_trace_ids.join(", ")}</span>
                      ) : null}
                    </div>
                  ))}
                  {!issueLinks.length ? <p className="systemNote">No linked artifacts yet</p> : null}
                </div>
              </section>

              <section className="issueSection">
                <h4>Start investigation</h4>
                <input
                  value={investigationProblem}
                  onChange={(event) => setInvestigationProblem(event.target.value)}
                  placeholder="Problem statement"
                />
                <select value={filterStatus} onChange={(event) => setFilterStatus(event.target.value)}>
                  <option value="">Any status</option>
                  <option value="error">error</option>
                  <option value="ok">ok</option>
                  <option value="timeout">timeout</option>
                  <option value="incomplete">incomplete</option>
                </select>
                <button className="primaryButton" onClick={() => void startSelectedInvestigation()}>
                  <Play size={15} />
                  Run investigation
                </button>
                <p className="systemNote">Runs deterministic search first; local model assistance is attached when configured.</p>
              </section>

              <section className="issueSection">
                <h4>Investigation runs</h4>
                <div className="investigationRows">
                  {issueInvestigations.map((run) => (
                    <button
                      className={run.investigation_run_id === selectedInvestigation?.investigation_run_id ? "selectedInvestigation" : ""}
                      key={run.investigation_run_id}
                      onClick={() => setSelectedInvestigationId(run.investigation_run_id)}
                    >
                      <span className={`judgeStatus ${run.status}`}>{run.status}</span>
                      <strong>{run.natural_language_problem_nullable ?? run.investigation_run_id}</strong>
                      <small>{run.result.evidence_trace_ids ? String((run.result.evidence_trace_ids as unknown[]).length) : 0} evidence traces · {run.investigation_run_id}</small>
                    </button>
                  ))}
                  {!issueInvestigations.length ? <p className="systemNote">No investigations for this issue</p> : null}
                </div>
              </section>

              <section className="issueSection">
                <h4>Candidate search and cohort</h4>
                <dl className="reviewFacts compactFacts">
                  <div>
                    <dt>Query</dt>
                    <dd>{selectedInvestigation?.natural_language_problem_nullable ?? investigationProblem}</dd>
                  </div>
                  <div>
                    <dt>Filters</dt>
                    <dd>{JSON.stringify(selectedInvestigation?.filters ?? (filterStatus ? { status: filterStatus } : {}))}</dd>
                  </div>
                  <div>
                    <dt>Seed trace</dt>
                    <dd>{selectedInvestigation?.seed_trace_id_nullable ?? selectedIssue.seed_trace_id_nullable ?? "none"}</dd>
                  </div>
                  <div>
                    <dt>Seed session</dt>
                    <dd>{selectedInvestigation?.seed_session_id_nullable ?? selectedIssue.seed_session_id_nullable ?? "none"}</dd>
                  </div>
                </dl>
                <div className="sectionRows">
                  {evidenceTraceIds.map((traceId) => (
                    <div key={traceId}>
                      <strong>{traceId}</strong>
                      <span>matching trace cohort</span>
                    </div>
                  ))}
                  {!evidenceTraceIds.length ? <p className="systemNote">No evidence traces selected</p> : null}
                </div>
              </section>

              <section className="issueSection impactSection">
                <h4>Impact</h4>
                {selectedImpact ? (
                  <>
                    <div className="metricsRow issueMetrics">
                      <Metric icon={<FileSearch />} label="Recurrence" value={String(selectedImpact.matching_trace_count)} />
                      <Metric icon={<Database />} label="Sessions" value={String(selectedImpact.affected_session_count)} />
                      <Metric icon={<Shield />} label="Entities" value={String(selectedImpact.affected_entity_count)} />
                      <Metric icon={<CheckCircle2 />} label="Remediation" value={selectedIssue.status} />
                    </div>
                    <p className="entityDescription">{selectedImpact.generated_summary}</p>
                    <div className="sectionRows">
                      <div>
                        <strong>Representative traces</strong>
                        <span>{selectedImpact.representative_trace_ids.join(", ") || "none"}</span>
                        {selectedImpact.representative_trace_ids.slice(0, 5).map((traceId) => (
                          <button key={traceId} onClick={() => props.onOpenTrace(traceId)}>
                            <FileSearch size={15} />
                            Open {shortIdentifier(traceId)}
                          </button>
                        ))}
                      </div>
                      <div>
                        <strong>Task/workflow distribution</strong>
                        <span>{formatCounts(selectedImpact.task_type_distribution)}</span>
                      </div>
                      <div>
                        <strong>Business dimensions</strong>
                        <span>{formatNestedCounts(selectedImpact.dimension_distribution)}</span>
                      </div>
                      <div>
                        <strong>Deployment/code context</strong>
                        <span>{formatCounts(selectedImpact.deployment_distribution)}</span>
                      </div>
                      <ImpactAffectedEntityRows
                        canWrite={writeConfirmation}
                        entities={affectedEntities.length ? affectedEntities : selectedImpact.affected_entities}
                        notificationTargets={notificationTargets}
                        onOpenTrace={props.onOpenTrace}
                        onNotify={(affectedEntityId, targetId) =>
                          void notifyAffectedEntity(affectedEntityId, targetId)
                        }
                        onReview={(affectedEntityId) =>
                          void createAffectedEntityReviewTask(affectedEntityId)
                        }
                        onUpdateStatus={(affectedEntityId, status) =>
                          void updateAffectedEntityStatus(affectedEntityId, status)
                        }
                      />
                      <ImpactBehaviorDistributionRows
                        distribution={selectedImpact.behavior_distribution}
                        onOpenTrace={props.onOpenTrace}
                      />
                      <ImpactRootCauseRows
                        causes={selectedImpact.suspected_root_causes}
                        onOpenTrace={props.onOpenTrace}
                      />
                      <div>
                        <strong>Recommended next actions</strong>
                        <span>{stringsFromUnknown(selectedInvestigation?.result.recommended_next_actions).join("; ") || "none"}</span>
                      </div>
                      <div>
                        <strong>Export/share</strong>
                        <button onClick={() => downloadJsonFile(`impact-${selectedImpact.report_id}.json`, selectedImpact)}>
                          <Database size={15} />
                          Export report JSON
                        </button>
                        <button onClick={() => void exportSelectedAffectedEntities("json")}>
                          <Database size={15} />
                          Export entities JSON
                        </button>
                        <button onClick={() => void exportSelectedAffectedEntities("csv")}>
                          <Database size={15} />
                          Export entities CSV
                        </button>
                      </div>
                    </div>
                  </>
                ) : (
                  <p className="systemNote">No impact report selected</p>
                )}
              </section>

              <section className="issueSection">
                <h4>Agent context pack preview</h4>
                <button onClick={() => void createSelectedContextPack()}>
                  <Braces size={15} />
                  Build context pack
                </button>
                <div className="sectionRows">
                  {contextPacks.map((pack) => (
                    <button
                      key={pack.context_pack_id}
                      className={pack.context_pack_id === selectedContextPack?.context_pack_id ? "selectedInvestigation" : ""}
                      onClick={() => setSelectedContextPackId(pack.context_pack_id)}
                    >
                      <strong>{pack.context_pack_id}</strong>
                      <span>{pack.classification} · {pack.source_trace_ids.join(", ")}</span>
                    </button>
                  ))}
                  {!contextPacks.length ? <p className="systemNote">No context packs</p> : null}
                </div>
                {selectedContextPack ? (
                  <pre>{JSON.stringify(selectedContextPack.content, null, 2)}</pre>
                ) : null}
              </section>

              <section className="issueSection">
                <h4>Root cause and next actions</h4>
                {selectedInvestigation ? (
                  <>
                    <div className="sectionRows">
                      {recordsFrom(selectedInvestigation.result.suspected_root_causes).map((cause, index) => (
                        <div key={`${selectedInvestigation.investigation_run_id}-cause-${index}`}>
                          <strong>{String(cause.hypothesis ?? cause.title ?? "Candidate")}</strong>
                          <span>{JSON.stringify(cause.evidence_summary ?? cause)}</span>
                        </div>
                      ))}
                    </div>
                    <pre>{JSON.stringify({
                      recommended_next_actions: selectedInvestigation.result.recommended_next_actions ?? [],
                      review_task_ids: selectedInvestigation.result.review_task_ids ?? [],
                      model_assistance: selectedInvestigation.result.model_assistance ?? null
                    }, null, 2)}</pre>
                  </>
                ) : (
                  <p className="systemNote">Select or create an investigation</p>
                )}
              </section>

              <section className="issueSection">
                <h4>Draft behavior, judge, and dataset actions</h4>
                <label className="toggleLabel">
                  <input
                    checked={writeConfirmation}
                    onChange={(event) => setWriteConfirmation(event.target.checked)}
                    type="checkbox"
                  />
                  Confirm writes
                </label>
                <div className="sectionRows">
                  {behaviorDrafts.map((draft, index) => (
                    <div key={`behavior-draft-${index}`}>
                      <strong>{String(draft.name ?? "behavior draft")}</strong>
                      <span>{String(draft.description ?? "no description")}</span>
                      <button disabled={!writeConfirmation} onClick={() => void createBehaviorFromDraft(draft)}>
                        <GitBranch size={15} />
                        Create behavior
                      </button>
                    </div>
                  ))}
                  {rubricDrafts.map((draft, index) => (
                    <div key={`rubric-draft-${index}`}>
                      <strong>{String(draft.name ?? "rubric draft")}</strong>
                      <span>{String(draft.fail ?? "no fail criterion")}</span>
                      <button disabled={!writeConfirmation} onClick={() => void createJudgeFromDraft(draft)}>
                        <Braces size={15} />
                        Create judge
                      </button>
                    </div>
                  ))}
                  <div>
                    <strong>Investigation dataset</strong>
                    <span>{evidenceTraceIds.length} evidence traces</span>
                    <button disabled={!writeConfirmation || !evidenceTraceIds.length} onClick={() => void createDatasetFromInvestigation()}>
                      <Database size={15} />
                      Create dataset
                    </button>
                  </div>
                </div>
              </section>
            </div>
          </>
        ) : (
          <div className="emptyState">{stateText}</div>
        )}
      </section>
    </div>
  );
}

function ImpactAffectedEntityRows(props: {
  canWrite: boolean;
  entities: Array<AffectedEntity | Record<string, unknown>>;
  notificationTargets: NotificationTarget[];
  onOpenTrace: (traceId: string) => void;
  onNotify?: (affectedEntityId: string, targetId: string) => void;
  onReview?: (affectedEntityId: string) => void;
  onUpdateStatus?: (affectedEntityId: string, status: AffectedEntity["status"]) => void;
}) {
  if (!props.entities.length) {
    return (
      <div>
        <strong>Affected entities</strong>
        <span>none</span>
      </div>
    );
  }
  return (
    <>
      <div>
        <strong>Affected entities</strong>
        <span>{props.entities.length} entity records</span>
      </div>
      {props.entities.slice(0, 8).map((entity, index) => {
        const traceIds = stringsFromUnknown(entity.trace_ids);
        const entityType = String(entity.entity_type ?? "entity");
        const entityId = String(entity.entity_id ?? "unknown");
        const affectedEntityId =
          typeof entity.affected_entity_id === "string" ? entity.affected_entity_id : "";
        const status = affectedEntityStatus(entity.status);
        const notificationTarget = props.notificationTargets[0];
        return (
          <div key={`${entityType}-${entityId}-${index}`}>
            <strong>{entityType}: {entityId}</strong>
            <span>{status.replace("_", " ")} · {traceIds.length} traces</span>
            <TraceButtonRow traceIds={traceIds} onOpenTrace={props.onOpenTrace} />
            {affectedEntityId && props.onUpdateStatus ? (
              <span className="traceButtonRow">
                {affectedEntityActionStatuses.map((nextStatus) => (
                  <button
                    disabled={!props.canWrite || status === nextStatus}
                    key={`${affectedEntityId}-${nextStatus}`}
                    onClick={() => props.onUpdateStatus?.(affectedEntityId, nextStatus)}
                  >
                    {affectedEntityStatusLabel(nextStatus)}
                  </button>
                ))}
                {props.onReview ? (
                  <button
                    disabled={!props.canWrite}
                    onClick={() => props.onReview?.(affectedEntityId)}
                  >
                    <CheckCircle2 size={15} />
                    Review task
                  </button>
                ) : null}
                {notificationTarget ? (
                  <button
                    disabled={!props.canWrite}
                    onClick={() => props.onNotify?.(affectedEntityId, notificationTarget.target_id)}
                  >
                    Notify {notificationTarget.type}
                  </button>
                ) : null}
              </span>
            ) : (
              <small>Remediation actions load after the canonical affected-entity record is available.</small>
            )}
          </div>
        );
      })}
    </>
  );
}

function affectedEntityStatus(value: unknown): AffectedEntity["status"] {
  return affectedEntityStatuses.includes(value as AffectedEntity["status"])
    ? (value as AffectedEntity["status"])
    : "needs_review";
}

function affectedEntityStatusLabel(status: AffectedEntity["status"]) {
  if (status === "false_positive") return "False positive";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function ImpactBehaviorDistributionRows(props: {
  distribution: Record<string, unknown>;
  onOpenTrace: (traceId: string) => void;
}) {
  const entries = Object.values(props.distribution)
    .map((entry) => asRecord(entry))
    .filter((entry) => Object.keys(entry).length > 0);
  if (!entries.length) {
    return (
      <div>
        <strong>Known behavior labels</strong>
        <span>none</span>
      </div>
    );
  }
  return (
    <>
      <div>
        <strong>Known behavior labels</strong>
        <span>{entries.length} behavior labels in the cohort</span>
      </div>
      {entries.slice(0, 6).map((entry, index) => {
        const behaviorId = String(entry.behavior_id ?? `behavior-${index}`);
        const traceIds = stringsFromUnknown(entry.trace_ids);
        const evidenceSpanIds = stringsFromUnknown(entry.evidence_span_ids);
        return (
          <div key={`${behaviorId}-${index}`}>
            <strong>{String(entry.name ?? behaviorId)}</strong>
            <span>
              {entry.severity ? `${String(entry.severity)} · ` : ""}
              {String(entry.match_count ?? 0)} matches · {formatCounts(asRecord(entry.status_counts))}
            </span>
            <small>{evidenceSpanIds.length ? `spans ${evidenceSpanIds.join(", ")}` : "no cited spans"}</small>
            <TraceButtonRow traceIds={traceIds} onOpenTrace={props.onOpenTrace} />
          </div>
        );
      })}
    </>
  );
}

function ImpactRootCauseRows(props: {
  causes: Array<Record<string, unknown>>;
  onOpenTrace: (traceId: string) => void;
}) {
  if (!props.causes.length) {
    return (
      <div>
        <strong>Suspected root causes</strong>
        <span>none</span>
      </div>
    );
  }
  return (
    <>
      <div>
        <strong>Suspected root causes</strong>
        <span>{props.causes.length} candidates</span>
      </div>
      {props.causes.slice(0, 6).map((cause, index) => {
        const traceIds = stringsFromUnknown(cause.representative_trace_ids);
        const spanIds = stringsFromUnknown(cause.representative_span_ids);
        return (
          <div key={`${String(cause.candidate_id ?? "root-cause")}-${index}`}>
            <strong>{String(cause.hypothesis ?? cause.candidate_id ?? "candidate")}</strong>
            <span>{formatRootCauseEvidence(cause)}</span>
            <small>
              {String(cause.confidence_or_uncertainty ?? "uncertainty not recorded")}
              {spanIds.length ? ` · spans ${spanIds.join(", ")}` : ""}
            </small>
            <TraceButtonRow traceIds={traceIds} onOpenTrace={props.onOpenTrace} />
          </div>
        );
      })}
    </>
  );
}

function TraceButtonRow(props: {
  traceIds: string[];
  onOpenTrace: (traceId: string) => void;
}) {
  if (!props.traceIds.length) return null;
  return (
    <span className="traceButtonRow">
      {props.traceIds.slice(0, 6).map((traceId) => (
        <button key={traceId} onClick={() => props.onOpenTrace(traceId)}>
          <FileSearch size={14} />
          {shortIdentifier(traceId)}
        </button>
      ))}
    </span>
  );
}

function VersionUsageRows(props: {
  usage?: VersionUsageSummary;
  onOpenTrace: (traceId: string) => void;
}) {
  if (!props.usage) {
    return <span className="versionUsageSummary">Usage not loaded</span>;
  }
  const evalSummary = props.usage.eval_summary ?? {};
  const recentTraceIds = props.usage.recent_traces.map((trace) => trace.trace_id);
  const evalIds = stringsFromUnknown(evalSummary.eval_run_ids);
  return (
    <div className="versionUsageSummary">
      <span>
        Traces {props.usage.trace_count} · status {formatCounts(props.usage.trace_status_counts)}
      </span>
      <span>Eval usage {formatLinkedEvalSummary(evalSummary)}</span>
      {evalIds.length ? <small>Eval runs {evalIds.map(shortIdentifier).join(", ")}</small> : null}
      <TraceButtonRow traceIds={recentTraceIds} onOpenTrace={props.onOpenTrace} />
    </div>
  );
}

function AgentConfigDiffSummary(props: { comparison: AgentConfigCompareResult }) {
  const structured = props.comparison.structured_diff;
  const metadata = props.comparison.metadata_diff;
  const toolChanges = asRecord(structured.tool_changes);
  const changedSections = Object.entries(structured)
    .filter(([key, value]) => key.endsWith("_changes") && key !== "tool_changes" && Array.isArray(value) && value.length)
    .map(([key, value]) => `${key.replaceAll("_", " ")}: ${(value as unknown[]).length}`);
  return (
    <div className="diffSummaryRows">
      <strong>Structured change summary</strong>
      <span>Metadata changed {props.comparison.metadata_changed ? "yes" : "no"} · fields {formatStringList(stringsFromUnknown(metadata.changed_fields))}</span>
      <span>Content fields {formatStringList(stringsFromUnknown(structured.changed_fields))}</span>
      <span>Tools added {formatStringList(stringsFromUnknown(toolChanges.added))} · removed {formatStringList(stringsFromUnknown(toolChanges.removed))} · changed {formatStringList(stringsFromUnknown(toolChanges.changed))}</span>
      {changedSections.length ? <span>{changedSections.join(" · ")}</span> : null}
      <LinkedEvalDiffRows diff={props.comparison.linked_eval_result_diff} />
      <TagMovementRows events={props.comparison.tag_movement_history} />
    </div>
  );
}

function PromptRegistryWorkspace(props: {
  client: OpenAbmClient;
  connection: ConnectionState;
  projectId: string;
  onOpenTrace: (traceId: string) => void;
}) {
  const { client, connection, projectId, onOpenTrace } = props;
  const [prompts, setPrompts] = useState<PromptDefinition[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [newName, setNewName] = useState("Refund assistant");
  const [newDescription, setNewDescription] = useState("Customer support refund workflow prompt.");
  const [templateText, setTemplateText] = useState("Hi {{name}}, I can help with refund status.");
  const [schemaText, setSchemaText] = useState('{\"type\":\"object\",\"required\":[\"name\"]}');
  const [tag, setTag] = useState("prod");
  const [parentCommitId, setParentCommitId] = useState("");
  const [renderCommitId, setRenderCommitId] = useState("");
  const [renderVariables, setRenderVariables] = useState('{\"name\":\"OpenABM\"}');
  const [resolveSecretRefs, setResolveSecretRefs] = useState(false);
  const [rendered, setRendered] = useState("");
  const [renderSecretInterpolations, setRenderSecretInterpolations] = useState<Array<Record<string, unknown>>>([]);
  const [oldCommitId, setOldCommitId] = useState("");
  const [newCommitId, setNewCommitId] = useState("");
  const [diff, setDiff] = useState<PromptDiffResult | null>(null);
  const [stateText, setStateText] = useState("Prompt registry needs a live API");

  const selectedPrompt = prompts.find((prompt) => prompt.prompt_id === selectedId) ?? prompts[0] ?? null;
  const versions = selectedPrompt?.versions ?? [];

  async function loadPrompts() {
    if (connection !== "live") {
      setPrompts([]);
      setSelectedId("");
      setStateText("fixture mode");
      return;
    }
    try {
      const listed = await client.listPrompts(projectId);
      const hydrated = await Promise.all(listed.map((prompt) => client.getPrompt(projectId, prompt.prompt_id)));
      setPrompts(hydrated);
      setSelectedId((current) =>
        hydrated.some((prompt) => prompt.prompt_id === current)
          ? current
          : hydrated[0]?.prompt_id ?? ""
      );
      setStateText(`${hydrated.length} prompts`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "request failed");
    }
  }

  useEffect(() => {
    void loadPrompts();
  }, [client, connection, projectId]);

  useEffect(() => {
    const latest = versions[0]?.commit_id ?? "";
    setRenderCommitId((current) => current || latest);
    setNewCommitId((current) => current || latest);
    setOldCommitId((current) => current || versions[1]?.commit_id || latest);
    setParentCommitId((current) => current || latest);
  }, [selectedPrompt?.prompt_id, versions.length]);

  async function createPrompt() {
    if (connection !== "live" || !newName.trim()) return;
    try {
      const created = await client.createPrompt(projectId, newName.trim(), newDescription.trim());
      const hydrated = await client.getPrompt(projectId, created.prompt_id);
      setPrompts((current) => [hydrated, ...current]);
      setSelectedId(hydrated.prompt_id);
      setStateText(`created ${hydrated.name}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "prompt creation failed");
    }
  }

  async function commitVersion() {
    if (connection !== "live" || !selectedPrompt) return;
    let variablesSchema: Record<string, unknown>;
    try {
      variablesSchema = parseJsonObject(schemaText);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "invalid variables schema");
      return;
    }
    try {
      const version = await client.commitPromptVersion(projectId, selectedPrompt.prompt_id, {
        templateText,
        variablesSchema,
        parentCommitId,
        tag
      });
      const hydrated = await client.getPrompt(projectId, selectedPrompt.prompt_id);
      setPrompts((current) => current.map((prompt) => (prompt.prompt_id === hydrated.prompt_id ? hydrated : prompt)));
      setRenderCommitId(version.commit_id);
      setNewCommitId(version.commit_id);
      setParentCommitId(version.commit_id);
      setStateText(`committed ${version.commit_id}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "version commit failed");
    }
  }

  async function renderSelectedPrompt() {
    if (connection !== "live" || !selectedPrompt || !renderCommitId) return;
    let variables: Record<string, unknown>;
    try {
      variables = parseJsonObject(renderVariables);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "invalid render variables");
      return;
    }
    try {
      const result = await client.renderPrompt(
        projectId,
        selectedPrompt.prompt_id,
        renderCommitId,
        variables,
        resolveSecretRefs
      );
      setRendered(result.rendered);
      setRenderSecretInterpolations(result.secret_interpolations ?? []);
      setStateText("rendered prompt");
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "render failed");
    }
  }

  async function diffSelectedPrompt() {
    if (connection !== "live" || !selectedPrompt || !oldCommitId || !newCommitId) return;
    try {
      const result = await client.diffPromptVersions(projectId, selectedPrompt.prompt_id, oldCommitId, newCommitId);
      setDiff(result);
      setStateText("diff ready");
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "diff failed");
    }
  }

  return (
    <div className="promptGrid">
      <section className="panel promptList">
        <div className="toolbar">
          <button className="iconButton" onClick={() => void loadPrompts()} aria-label="Refresh prompts">
            <TimerReset size={16} />
          </button>
          <span className="systemNote">{stateText}</span>
        </div>
        <div className="createStrip">
          <input value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="Prompt name" />
          <input value={newDescription} onChange={(event) => setNewDescription(event.target.value)} placeholder="Description" />
          <button onClick={() => void createPrompt()}>
            <Split size={15} />
            Create prompt
          </button>
        </div>
        <div className="promptRows">
          {prompts.map((prompt) => (
            <button
              className={prompt.prompt_id === selectedPrompt?.prompt_id ? "selectedPrompt" : ""}
              key={prompt.prompt_id}
              onClick={() => {
                setSelectedId(prompt.prompt_id);
                setRendered("");
                setDiff(null);
              }}
            >
              <span className="judgeStatus active">{Object.keys(prompt.tags).length || 0} tags</span>
              <strong>{prompt.name}</strong>
              <small>{prompt.versions?.length ?? 0} versions · {prompt.prompt_id}</small>
            </button>
          ))}
          {!prompts.length ? <div className="emptyState">No prompts</div> : null}
        </div>
      </section>

      <section className="panel promptDetail">
        {selectedPrompt ? (
          <>
            <div className="detailHeader">
              <div>
                <p className="sectionLabel">prompt</p>
                <h3>{selectedPrompt.name}</h3>
              </div>
              <span className="judgeStatus active">{Object.keys(selectedPrompt.tags).join(", ") || "untagged"}</span>
            </div>
            <p className="entityDescription">{selectedPrompt.description ?? selectedPrompt.prompt_id}</p>
            <div className="metricsRow promptMetrics">
              <Metric icon={<Split />} label="Versions" value={String(versions.length)} />
              <Metric icon={<GitBranch />} label="Latest" value={versions[0]?.commit_id ?? "none"} />
              <Metric icon={<Shield />} label="Tags" value={formatTags(selectedPrompt.tags)} />
            </div>
            <div className="promptSections">
              <section className="promptSection">
                <h4>Commit version</h4>
                <label className="notesBox">
                  Template
                  <textarea value={templateText} onChange={(event) => setTemplateText(event.target.value)} />
                </label>
                <label className="notesBox">
                  Variables schema
                  <textarea value={schemaText} onChange={(event) => setSchemaText(event.target.value)} />
                </label>
                <div className="inlineControls">
                  <select value={parentCommitId} onChange={(event) => setParentCommitId(event.target.value)}>
                    <option value="">No parent</option>
                    {versions.map((version) => (
                      <option key={version.commit_id} value={version.commit_id}>{version.commit_id}</option>
                    ))}
                  </select>
                  <input value={tag} onChange={(event) => setTag(event.target.value)} placeholder="tag" />
                </div>
                <button className="primaryButton" onClick={() => void commitVersion()}>
                  <GitBranch size={15} />
                  Commit
                </button>
              </section>

              <section className="promptSection">
                <h4>Versions</h4>
                <div className="versionRows">
                  {versions.map((version) => (
                    <div className="versionUsageRow" key={version.prompt_version_id}>
                      <button
                        className="versionSelectButton"
                        onClick={() => {
                          setTemplateText(version.template_text);
                          setSchemaText(JSON.stringify(version.variables_schema));
                          setRenderCommitId(version.commit_id);
                          setNewCommitId(version.commit_id);
                        }}
                      >
                        <strong>{version.commit_id}</strong>
                        <span>{version.parent_commit_id ? `parent ${version.parent_commit_id}` : "root"}</span>
                        <span>Tags {formatStringList(version.active_tags ?? [])}</span>
                        <small>{formatTime(version.created_at)}</small>
                      </button>
                      <VersionUsageRows usage={version.usage_summary} onOpenTrace={onOpenTrace} />
                    </div>
                  ))}
                  {!versions.length ? <p className="systemNote">No versions yet</p> : null}
                </div>
              </section>

              <section className="promptSection">
                <h4>Render</h4>
                <div className="evalForm">
                  <label>
                    Commit
                    <select value={renderCommitId} onChange={(event) => setRenderCommitId(event.target.value)}>
                      <option value="">Select commit</option>
                      {versions.map((version) => (
                        <option key={version.commit_id} value={version.commit_id}>{version.commit_id}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Variables
                    <input value={renderVariables} onChange={(event) => setRenderVariables(event.target.value)} />
                  </label>
                  <label className="checkboxLabel">
                    <input
                      type="checkbox"
                      checked={resolveSecretRefs}
                      onChange={(event) => setResolveSecretRefs(event.target.checked)}
                    />
                    Resolve secret refs
                  </label>
                  <button onClick={() => void renderSelectedPrompt()}>
                    <Play size={15} />
                    Render
                  </button>
                </div>
                {rendered ? <pre>{rendered}</pre> : null}
                {renderSecretInterpolations.length ? (
                  <pre>{JSON.stringify(renderSecretInterpolations, null, 2)}</pre>
                ) : null}
              </section>

              <section className="promptSection">
                <h4>Diff</h4>
                <div className="evalForm">
                  <label>
                    Old
                    <select value={oldCommitId} onChange={(event) => setOldCommitId(event.target.value)}>
                      <option value="">Select old</option>
                      {versions.map((version) => (
                        <option key={version.commit_id} value={version.commit_id}>{version.commit_id}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    New
                    <select value={newCommitId} onChange={(event) => setNewCommitId(event.target.value)}>
                      <option value="">Select new</option>
                      {versions.map((version) => (
                        <option key={version.commit_id} value={version.commit_id}>{version.commit_id}</option>
                      ))}
                    </select>
                  </label>
                  <button onClick={() => void diffSelectedPrompt()}>
                    <FileSearch size={15} />
                    Diff
                  </button>
                </div>
                {diff ? <pre>{diff.text_diff || "No text changes"}</pre> : null}
                {diff ? <PromptDiffSummary diff={diff} /> : null}
              </section>
            </div>
          </>
        ) : (
          <div className="emptyState">{stateText}</div>
        )}
      </section>
    </div>
  );
}

function BehaviorWorkspace(props: {
  client: OpenAbmClient;
  connection: ConnectionState;
  projectId: string;
  onOpenTrace: (traceId: string) => void;
}) {
  const { client, connection, projectId } = props;
  const [behaviors, setBehaviors] = useState<BehaviorDefinition[]>([]);
  const [matches, setMatches] = useState<BehaviorMatch[]>([]);
  const [reviewTasks, setReviewTasks] = useState<ReviewTask[]>([]);
  const [automations, setAutomations] = useState<AutomationDefinition[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [name, setName] = useState("wrong_tool_for_refund");
  const [description, setDescription] = useState("Refund workflow uses an unrelated order lookup.");
  const [severity, setSeverity] = useState("high");
  const [detectorType, setDetectorType] = useState("rule");
  const [ruleField, setRuleField] = useState("attributes.tool.name");
  const [ruleOp, setRuleOp] = useState("eq");
  const [ruleValue, setRuleValue] = useState("order_lookup");
  const [filterStatus, setFilterStatus] = useState("error");
  const [query, setQuery] = useState("");
  const [backtest, setBacktest] = useState<BehaviorBacktestResult | null>(null);
  const [stateText, setStateText] = useState("Behavior monitoring needs a live API");

  const selectedBehavior = behaviors.find((behavior) => behavior.behavior_id === selectedId) ?? behaviors[0] ?? null;
  const matchStatusCounts = countLabels(matches.map((match) => match.status));
  const reviewLabelCounts = countLabels(reviewTasks.map((task) => behaviorReviewLabel(task)));
  const relatedAutomations = selectedBehavior
    ? automations.filter((automation) => automationReferencesBehavior(automation, selectedBehavior))
    : [];
  const latestMatch = matches[0] ?? null;

  async function loadBehaviors() {
    if (connection !== "live") {
      setBehaviors([]);
      setMatches([]);
      setReviewTasks([]);
      setAutomations([]);
      setSelectedId("");
      setBacktest(null);
      setStateText("fixture mode");
      return;
    }
    try {
      const loaded = await client.listBehaviors(projectId);
      setBehaviors(loaded);
      setSelectedId((current) =>
        loaded.some((behavior) => behavior.behavior_id === current)
          ? current
          : loaded[0]?.behavior_id ?? ""
      );
      setStateText(`${loaded.length} behaviors`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "request failed");
    }
  }

  useEffect(() => {
    void loadBehaviors();
  }, [client, connection, projectId]);

  async function loadBehaviorDetail(behavior: BehaviorDefinition | null = selectedBehavior) {
    if (connection !== "live" || !behavior) {
      setMatches([]);
      setReviewTasks([]);
      setAutomations([]);
      return;
    }
    try {
      const [loadedMatches, loadedReviews, loadedAutomations] = await Promise.all([
        client.listBehaviorMatches(projectId, { behaviorId: behavior.behavior_id }),
        client.listReviewTasks(projectId, { taskType: "behavior_candidate" }),
        client.listAutomations(projectId)
      ]);
      setMatches(loadedMatches);
      setReviewTasks(
        loadedReviews.filter(
          (task) =>
            task.source_entity_type === "behavior" &&
            task.source_entity_id === behavior.behavior_id
        )
      );
      setAutomations(loadedAutomations);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "behavior detail refresh failed");
    }
  }

  useEffect(() => {
    void loadBehaviorDetail();
  }, [client, connection, projectId, selectedBehavior?.behavior_id]);

  async function createBehavior() {
    if (connection !== "live" || !name.trim()) return;
    const detector =
      detectorType === "manual_label"
        ? { type: "manual_label", labels: [name.trim()] }
        : {
            type: "rule",
            scope: "span",
            conditions: {
              combine: "all",
              items: [{ field: ruleField.trim(), op: ruleOp, value: ruleValue.trim() }]
            }
          };
    try {
      const created = await client.createBehavior(projectId, {
        name: name.trim(),
        description: description.trim(),
        severity,
        detector
      });
      setBehaviors((current) => [created, ...current]);
      setSelectedId(created.behavior_id);
      setBacktest(null);
      setMatches([]);
      setReviewTasks([]);
      setStateText(`created ${created.name}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "behavior creation failed");
    }
  }

  async function runBacktest() {
    if (connection !== "live" || !selectedBehavior) return;
    try {
      const result = await client.backtestBehavior(projectId, selectedBehavior.behavior_id, {
        status: filterStatus || undefined,
        query,
        limit: 100,
        sampleLimit: 10
      });
      setBacktest(result);
      setStateText(`backtest ${result.status}: ${result.positive_count}/${result.trace_count} positives`);
      void loadBehaviorDetail(selectedBehavior);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "backtest failed");
    }
  }

  async function updateBehaviorReviewTask(
    task: ReviewTask,
    status: ReviewTask["status"],
    decision: string
  ) {
    if (connection !== "live") return;
    try {
      const updated = await client.updateReviewTask(projectId, task.review_task_id, {
        status,
        decision,
        notes: `Behavior detail decision: ${decision}`
      });
      setReviewTasks((current) =>
        current.map((item) => (item.review_task_id === updated.review_task_id ? updated : item))
      );
      setStateText(`review ${updated.status}: ${updated.review_task_id}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "review update failed");
    }
  }

  return (
    <div className="behaviorGrid">
      <section className="panel behaviorList">
        <div className="toolbar">
          <button className="iconButton" onClick={() => void loadBehaviors()} aria-label="Refresh behaviors">
            <TimerReset size={16} />
          </button>
          <span className="systemNote">{stateText}</span>
        </div>
        <div className="behaviorCreate">
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Behavior name" />
          <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Description" />
          <div className="inlineControls">
            <select value={severity} onChange={(event) => setSeverity(event.target.value)}>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="critical">critical</option>
            </select>
            <select value={detectorType} onChange={(event) => setDetectorType(event.target.value)}>
              <option value="rule">rule</option>
              <option value="manual_label">manual label</option>
            </select>
          </div>
          {detectorType === "rule" ? (
            <div className="ruleControls">
              <input value={ruleField} onChange={(event) => setRuleField(event.target.value)} placeholder="field" />
              <select value={ruleOp} onChange={(event) => setRuleOp(event.target.value)}>
                <option value="eq">eq</option>
                <option value="neq">neq</option>
                <option value="contains">contains</option>
                <option value="exists">exists</option>
              </select>
              <input value={ruleValue} onChange={(event) => setRuleValue(event.target.value)} placeholder="value" />
            </div>
          ) : null}
          <button onClick={() => void createBehavior()}>
            <GitBranch size={15} />
            Create behavior
          </button>
        </div>
        <div className="behaviorRows">
          {behaviors.map((behavior) => (
            <button
              className={behavior.behavior_id === selectedBehavior?.behavior_id ? "selectedBehavior" : ""}
              key={behavior.behavior_id}
              onClick={() => {
                setSelectedId(behavior.behavior_id);
                setBacktest(null);
              }}
            >
              <span className={`severityBadge ${behavior.severity}`}>{behavior.severity}</span>
              <strong>{behavior.name}</strong>
              <small>{String(behavior.detector.type ?? "detector")} · {behavior.status}</small>
            </button>
          ))}
          {!behaviors.length ? <div className="emptyState">No behaviors</div> : null}
        </div>
      </section>

      <section className="panel behaviorDetail">
        {selectedBehavior ? (
          <>
            <div className="detailHeader">
              <div>
                <p className="sectionLabel">behavior</p>
                <h3>{selectedBehavior.name}</h3>
              </div>
              <span className={`severityBadge ${selectedBehavior.severity}`}>{selectedBehavior.severity}</span>
            </div>
            <p className="entityDescription">{selectedBehavior.description ?? selectedBehavior.behavior_id}</p>
            <div className="metricsRow behaviorMetrics">
              <Metric icon={<GitBranch />} label="Detector" value={String(selectedBehavior.detector.type ?? "unknown")} />
              <Metric icon={<Shield />} label="Matches" value={String(matches.length)} />
              <Metric icon={<CheckCircle2 />} label="Reviews" value={String(reviewTasks.length)} />
              <Metric icon={<Activity />} label="Backtest" value={backtest ? `${backtest.positive_count}/${backtest.trace_count}` : "not run"} />
            </div>
            <div className="behaviorSections">
              <section className="behaviorSection">
                <h4>Detector</h4>
                <pre>{JSON.stringify(selectedBehavior.detector, null, 2)}</pre>
              </section>
              <section className="behaviorSection">
                <h4>Trend</h4>
                <dl className="reviewFacts compactFacts">
                  <div>
                    <dt>Status</dt>
                    <dd>{selectedBehavior.status}</dd>
                  </div>
                  <div>
                    <dt>Match labels</dt>
                    <dd>{formatCounts(matchStatusCounts)}</dd>
                  </div>
                  <div>
                    <dt>Review labels</dt>
                    <dd>{formatCounts(reviewLabelCounts)}</dd>
                  </div>
                  <div>
                    <dt>Latest match</dt>
                    <dd>{latestMatch ? formatTime(latestMatch.created_at) : "none"}</dd>
                  </div>
                </dl>
              </section>
              <section className="behaviorSection">
                <h4>Backtest</h4>
                <div className="evalForm">
                  <label>
                    Trace status
                    <select value={filterStatus} onChange={(event) => setFilterStatus(event.target.value)}>
                      <option value="">Any</option>
                      <option value="ok">ok</option>
                      <option value="error">error</option>
                      <option value="incomplete">incomplete</option>
                      <option value="timeout">timeout</option>
                    </select>
                  </label>
                  <label>
                    Query
                    <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="optional text search" />
                  </label>
                  <button className="primaryButton" onClick={() => void runBacktest()}>
                    <Play size={15} />
                    Run backtest
                  </button>
                </div>
                {backtest ? (
                  <div className="backtestSummary">
                    <strong>{backtest.status}</strong>
                    <span>{backtest.positive_count} positives · {backtest.negative_count} negatives · {formatRate(backtest.detection_rate)}</span>
                    {backtest.review_task ? <span>Review task: {backtest.review_task.review_task_id}</span> : null}
                    {backtest.persisted_behavior_matches?.length ? <span>{backtest.persisted_behavior_matches.length} persisted matches</span> : null}
                    {backtest.unsupported_reason ? <span>{backtest.unsupported_reason}</span> : null}
                  </div>
                ) : null}
              </section>
              <section className="behaviorSection">
                <h4>Matched traces</h4>
                <div className="exampleRows">
                  {matches.slice(0, 12).map((match) => (
                    <div key={match.behavior_match_id}>
                      <strong>{match.trace_id}</strong>
                      <span>{match.status} · {match.span_id ?? "trace-level"} · {formatTime(match.created_at)}</span>
                      <small>{match.evidence_span_ids.join(", ") || "no cited spans"}</small>
                      <button onClick={() => props.onOpenTrace(match.trace_id)}>
                        <FileSearch size={14} />
                        Open trace
                      </button>
                    </div>
                  ))}
                  {!matches.length ? <p className="systemNote">No persisted matches</p> : null}
                </div>
              </section>
              <section className="behaviorSection">
                <h4>False-positive review labels</h4>
                <div className="sectionRows">
                  {reviewTasks.map((task) => (
                    <div key={task.review_task_id}>
                      <strong>{behaviorReviewLabel(task)}</strong>
                      <span>{task.review_task_id} · {task.status} · {formatTime(task.updated_at)}</span>
                      <span>{task.decision_nullable ?? "no decision"}</span>
                      <small>{task.evidence_ids.join(", ") || "no evidence ids"}</small>
                      {task.status === "open" || task.status === "needs_more_evidence" ? (
                        <span className="reviewActionRow">
                          <button onClick={() => void updateBehaviorReviewTask(task, "accepted", "accepted_behavior_label")}>
                            <CheckCircle2 size={14} />
                            Accept
                          </button>
                          <button onClick={() => void updateBehaviorReviewTask(task, "rejected", "rejected_behavior_label")}>
                            <XCircle size={14} />
                            Reject
                          </button>
                          <button onClick={() => void updateBehaviorReviewTask(task, "needs_more_evidence", "needs_more_evidence")}>
                            <AlertTriangle size={14} />
                            Need evidence
                          </button>
                        </span>
                      ) : null}
                    </div>
                  ))}
                  {!reviewTasks.length ? <p className="systemNote">No behavior review labels</p> : null}
                </div>
              </section>
              <section className="behaviorSection">
                <h4>Actions and automations</h4>
                <div className="sectionRows">
                  {relatedAutomations.map((automation) => (
                    <div key={automation.automation_id}>
                      <strong>{automation.name}</strong>
                      <span>{automation.status} · {automation.actions.length} actions</span>
                      <small>{automation.automation_id}</small>
                    </div>
                  ))}
                  {backtest?.review_task ? (
                    <div>
                      <strong>{backtest.review_task.task_type}</strong>
                      <span>{backtest.review_task.status} · {backtest.review_task.review_task_id}</span>
                      <small>{backtest.review_task.evidence_ids.join(", ") || "no evidence ids"}</small>
                    </div>
                  ) : null}
                  {!relatedAutomations.length && !backtest?.review_task ? <p className="systemNote">No linked actions</p> : null}
                </div>
              </section>
              <section className="behaviorSection positiveExamples">
                <h4>Positive examples</h4>
                <div className="exampleRows">
                  {(backtest?.positive_examples ?? []).map((example) => (
                    <div key={example.trace_id}>
                      <strong>{example.trace_id}</strong>
                      <span>{example.reason}</span>
                      <small>{example.evidence_span_ids.join(", ") || "no cited spans"}</small>
                    </div>
                  ))}
                  {backtest && !backtest.positive_examples.length ? <p className="systemNote">No positives</p> : null}
                  {!backtest ? <p className="systemNote">Run a backtest to populate examples</p> : null}
                </div>
              </section>
              <section className="behaviorSection positiveExamples">
                <h4>Negative examples</h4>
                <div className="exampleRows">
                  {(backtest?.negative_examples ?? []).map((example) => (
                    <div key={example.trace_id}>
                      <strong>{example.trace_id}</strong>
                      <span>{example.reason}</span>
                      <small>{example.evidence_span_ids.join(", ") || "no cited spans"}</small>
                    </div>
                  ))}
                  {backtest && !backtest.negative_examples.length ? <p className="systemNote">No negatives</p> : null}
                  {!backtest ? <p className="systemNote">Run a backtest to populate examples</p> : null}
                </div>
              </section>
            </div>
          </>
        ) : (
          <div className="emptyState">{stateText}</div>
        )}
      </section>
    </div>
  );
}

function AutomationWorkspace(props: {
  client: OpenAbmClient;
  connection: ConnectionState;
  projectId: string;
  traces: TraceEnvelope[];
}) {
  const { client, connection, projectId, traces } = props;
  const [targets, setTargets] = useState<NotificationTarget[]>([]);
  const [automations, setAutomations] = useState<AutomationDefinition[]>([]);
  const [runHistory, setRunHistory] = useState<AutomationRun[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [targetName, setTargetName] = useState("Local preview");
  const [targetType, setTargetType] = useState<NotificationTarget["type"]>("webhook");
  const [secretRefs, setSecretRefs] = useState("secret_webhook_url");
  const [automationName, setAutomationName] = useState("Review refund traces");
  const [triggerType, setTriggerType] = useState("trace_completed");
  const [conditionField, setConditionField] = useState("trace.status");
  const [conditionOp, setConditionOp] = useState("eq");
  const [conditionValue, setConditionValue] = useState("error");
  const [actionType, setActionType] = useState("create_review_task");
  const [notificationMessage, setNotificationMessage] = useState("Trace needs review");
  const [cooldownSeconds, setCooldownSeconds] = useState("0");
  const [cooldownKey, setCooldownKey] = useState("automation_id + project_id");
  const [retryAttempts, setRetryAttempts] = useState("1");
  const [onFailure, setOnFailure] = useState("stop");
  const [previewStatus, setPreviewStatus] = useState("");
  const [previewQuery, setPreviewQuery] = useState("");
  const [preview, setPreview] = useState<AutomationPreviewResult | null>(null);
  const [runTraceId, setRunTraceId] = useState("");
  const [idempotencyKey, setIdempotencyKey] = useState(`web-${Date.now()}`);
  const [runResult, setRunResult] = useState<AutomationRun | null>(null);
  const [stateText, setStateText] = useState("Automations need a live API");

  const selectedAutomation = automations.find((automation) => automation.automation_id === selectedId) ?? automations[0] ?? null;
  const selectedTarget = targets[0] ?? null;
  const draftConditions = automationDraftConditions(conditionField, conditionOp, conditionValue);
  const draftActions = automationDraftActions(
    actionType,
    selectedTarget?.target_id,
    notificationMessage,
    Number.parseInt(retryAttempts, 10),
    onFailure
  );
  const deadLetteredActions = automationDeadLetteredActions(runHistory, runResult);

  async function loadAutomations() {
    if (connection !== "live") {
      setTargets([]);
      setAutomations([]);
      setRunHistory([]);
      setSelectedId("");
      setPreview(null);
      setRunResult(null);
      setStateText("fixture mode");
      return;
    }
    try {
      const [loadedTargets, loadedAutomations] = await Promise.all([
        client.listNotificationTargets(projectId),
        client.listAutomations(projectId)
      ]);
      setTargets(loadedTargets);
      setAutomations(loadedAutomations);
      setSelectedId((current) =>
        loadedAutomations.some((automation) => automation.automation_id === current)
          ? current
          : loadedAutomations[0]?.automation_id ?? ""
      );
      setStateText(`${loadedAutomations.length} automations · ${loadedTargets.length} targets`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "automation refresh failed");
    }
  }

  useEffect(() => {
    void loadAutomations();
  }, [client, connection, projectId]);

  async function loadRunHistory(automation: AutomationDefinition | null = selectedAutomation) {
    if (connection !== "live" || !automation) {
      setRunHistory([]);
      return;
    }
    try {
      const runs = await client.listAutomationRuns(projectId, automation.automation_id);
      setRunHistory(runs);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "automation history unavailable");
    }
  }

  useEffect(() => {
    void loadRunHistory();
  }, [client, connection, projectId, selectedAutomation?.automation_id]);

  async function createTarget() {
    if (connection !== "live" || !targetName.trim()) return;
    const refs = secretRefs.split(",").map((item) => item.trim()).filter(Boolean);
    try {
      const created = await client.createNotificationTarget(projectId, {
        type: targetType,
        displayName: targetName.trim(),
        configSecretRefs: refs,
        status: refs.length ? "active" : "paused"
      });
      setTargets((current) => [created, ...current.filter((target) => target.target_id !== created.target_id)]);
      setStateText(`created target ${created.display_name}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "target creation failed");
    }
  }

  async function createAutomation() {
    if (connection !== "live" || !automationName.trim()) return;
    const seconds = Number.parseInt(cooldownSeconds, 10);
    if ((actionType === "send_notification" || actionType === "review_and_notification") && !selectedTarget) {
      setStateText("Create a notification target before adding notification actions");
      return;
    }
    try {
      const created = await client.createAutomation(projectId, {
        name: automationName.trim(),
        trigger: { type: triggerType },
        conditions: draftConditions,
        actions: draftActions,
        cooldown: Number.isFinite(seconds) && seconds > 0
          ? { seconds, key: cooldownKey.trim() || "automation_id + project_id" }
          : null,
        status: "active"
      });
      setAutomations((current) => [created, ...current.filter((automation) => automation.automation_id !== created.automation_id)]);
      setSelectedId(created.automation_id);
      setRunResult(null);
      setRunHistory([]);
      setPreview(null);
      setStateText(`created ${created.name}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "automation creation failed");
    }
  }

  async function previewMatchingTraces() {
    if (connection !== "live" || !selectedAutomation) return;
    try {
      const result = await client.previewAutomationMatches(projectId, selectedAutomation.automation_id, {
        status: previewStatus || undefined,
        query: previewQuery,
        limit: 100
      });
      setPreview(result);
      setStateText(`preview ${result.match_count}/${result.trace_count} matches`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "preview failed");
    }
  }

  async function runAutomation() {
    if (connection !== "live" || !selectedAutomation) return;
    try {
      const result = await client.runAutomation(projectId, selectedAutomation.automation_id, {
        traceId: runTraceId || undefined,
        idempotencyKey: idempotencyKey.trim() || undefined
      });
      setRunResult(result);
      setRunHistory((current) => [
        result,
        ...current.filter((run) => run.automation_run_id !== result.automation_run_id)
      ]);
      setIdempotencyKey(`web-${Date.now()}`);
      setStateText(result.duplicate ? `duplicate ${result.status}` : `run ${result.status}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "automation run failed");
    }
  }

  return (
    <div className="automationGrid">
      <section className="panel automationList">
        <div className="toolbar">
          <button className="iconButton" onClick={() => void loadAutomations()} aria-label="Refresh automations">
            <TimerReset size={16} />
          </button>
          <span className="systemNote">{stateText}</span>
        </div>
        <div className="automationCreate">
          <input value={targetName} onChange={(event) => setTargetName(event.target.value)} placeholder="Target name" />
          <div className="inlineControls">
            <select value={targetType} onChange={(event) => setTargetType(event.target.value as NotificationTarget["type"])}>
              <option value="webhook">webhook</option>
              <option value="chat">chat</option>
              <option value="email">email</option>
              <option value="issue_tracker">issue tracker</option>
              <option value="custom">custom</option>
            </select>
            <input value={secretRefs} onChange={(event) => setSecretRefs(event.target.value)} placeholder="secret refs" />
          </div>
          <button onClick={() => void createTarget()}>
            <KeyRound size={15} />
            Create target
          </button>
        </div>
        <div className="automationCreate secondaryCreate">
          <input value={automationName} onChange={(event) => setAutomationName(event.target.value)} placeholder="Automation name" />
          <div className="inlineControls">
            <select value={triggerType} onChange={(event) => setTriggerType(event.target.value)}>
              <option value="trace_completed">trace completed</option>
              <option value="trace_failed">trace failed</option>
              <option value="manual_test">manual test</option>
            </select>
            <select value={conditionField} onChange={(event) => setConditionField(event.target.value)}>
              <option value="">No condition</option>
              <option value="trace.status">trace status</option>
              <option value="trace.environment">trace environment</option>
              <option value="trace.trace_id">trace id</option>
              <option value="attributes.openabm.environment">attribute environment</option>
            </select>
          </div>
          <div className="ruleControls">
            <select value={conditionOp} onChange={(event) => setConditionOp(event.target.value)}>
              <option value="eq">eq</option>
              <option value="neq">neq</option>
              <option value="contains">contains</option>
              <option value="exists">exists</option>
            </select>
            <input value={conditionValue} onChange={(event) => setConditionValue(event.target.value)} placeholder="condition value" />
            <select value={previewStatus} onChange={(event) => setPreviewStatus(event.target.value)}>
              <option value="">Preview any</option>
              <option value="error">error</option>
              <option value="ok">ok</option>
              <option value="timeout">timeout</option>
              <option value="incomplete">incomplete</option>
            </select>
          </div>
          <div className="inlineControls">
            <select value={actionType} onChange={(event) => setActionType(event.target.value)}>
              <option value="create_review_task">create review task</option>
              <option value="send_notification">send notification</option>
              <option value="review_and_notification">review and notification</option>
            </select>
            <select value={onFailure} onChange={(event) => setOnFailure(event.target.value)}>
              <option value="stop">stop on failure</option>
              <option value="continue">continue on failure</option>
              <option value="compensate">compensate on failure</option>
            </select>
          </div>
          <input value={notificationMessage} onChange={(event) => setNotificationMessage(event.target.value)} placeholder="Notification message" />
          <div className="inlineControls">
            <input value={cooldownSeconds} onChange={(event) => setCooldownSeconds(event.target.value)} placeholder="cooldown seconds" />
            <input value={cooldownKey} onChange={(event) => setCooldownKey(event.target.value)} placeholder="cooldown key" />
          </div>
          <input value={retryAttempts} onChange={(event) => setRetryAttempts(event.target.value)} placeholder="retry attempts" />
          <div className="actionPreview">
            <strong>Action list</strong>
            <pre>{JSON.stringify({ trigger: { type: triggerType }, conditions: draftConditions, actions: draftActions }, null, 2)}</pre>
          </div>
          <button onClick={() => void createAutomation()}>
            <Play size={15} />
            Create automation
          </button>
        </div>
        <div className="automationRows">
          {automations.map((automation) => (
            <button
              className={automation.automation_id === selectedAutomation?.automation_id ? "selectedAutomation" : ""}
              key={automation.automation_id}
              onClick={() => {
                setSelectedId(automation.automation_id);
                setRunResult(null);
              }}
            >
              <span className={`judgeStatus ${automation.status}`}>{automation.status}</span>
              <strong>{automation.name}</strong>
              <small>{automation.actions.length} actions · {automation.automation_id}</small>
            </button>
          ))}
          {!automations.length ? <div className="emptyState">No automations</div> : null}
        </div>
      </section>

      <section className="panel automationDetail">
        {selectedAutomation ? (
          <>
            <div className="detailHeader">
              <div>
                <p className="sectionLabel">automation</p>
                <h3>{selectedAutomation.name}</h3>
              </div>
              <span className={`judgeStatus ${selectedAutomation.status}`}>{selectedAutomation.status}</span>
            </div>
            <div className="metricsRow automationMetrics">
              <Metric icon={<Play />} label="Trigger" value={String(selectedAutomation.trigger.type ?? "unknown")} />
              <Metric icon={<CheckCircle2 />} label="Actions" value={String(selectedAutomation.actions.length)} />
              <Metric icon={<TimerReset />} label="Runs" value={String(runHistory.length)} />
              <Metric icon={<AlertTriangle />} label="Dead letters" value={String(deadLetteredActions.length)} />
            </div>
            <div className="automationSections">
              <section className="automationSection">
                <h4>Definition</h4>
                <pre>{JSON.stringify({
                  trigger: selectedAutomation.trigger,
                  conditions: selectedAutomation.conditions,
                  actions: selectedAutomation.actions,
                  cooldown: selectedAutomation.cooldown
                }, null, 2)}</pre>
              </section>

              <section className="automationSection">
                <h4>Preview matching traces</h4>
                <div className="evalForm">
                  <label>
                    Trace status
                    <select value={previewStatus} onChange={(event) => setPreviewStatus(event.target.value)}>
                      <option value="">Any</option>
                      <option value="ok">ok</option>
                      <option value="error">error</option>
                      <option value="timeout">timeout</option>
                      <option value="incomplete">incomplete</option>
                    </select>
                  </label>
                  <label>
                    Query
                    <input value={previewQuery} onChange={(event) => setPreviewQuery(event.target.value)} placeholder="optional text search" />
                  </label>
                  <button className="primaryButton" onClick={() => void previewMatchingTraces()}>
                    <FileSearch size={15} />
                    Preview
                  </button>
                </div>
                {preview ? (
                  <div className="sectionRows">
                    <div>
                      <strong>{preview.match_count}/{preview.trace_count} matches</strong>
                      <span>{preview.automation_id}</span>
                    </div>
                    {preview.matches.slice(0, 8).map((match) => (
                      <div key={match.trace_id}>
                        <strong>{match.trace_id}</strong>
                        <span>{match.status ?? "unknown"} · {match.session_id ?? "no session"} · {String(match.condition_result.passed ?? "unknown")}</span>
                      </div>
                    ))}
                    {!preview.matches.length ? <p className="systemNote">No matching traces</p> : null}
                  </div>
                ) : null}
              </section>

              <section className="automationSection">
                <h4>Test run</h4>
                <select value={runTraceId} onChange={(event) => setRunTraceId(event.target.value)}>
                  <option value="">No trace trigger</option>
                  {traces.map((trace) => (
                    <option key={trace.trace_id} value={trace.trace_id}>
                      {trace.trace_id} · {trace.status}
                    </option>
                  ))}
                </select>
                <input value={idempotencyKey} onChange={(event) => setIdempotencyKey(event.target.value)} placeholder="idempotency key" />
                <button className="primaryButton" onClick={() => void runAutomation()}>
                  <Play size={15} />
                  Run
                </button>
                {runResult ? (
                  <div className={`automationResult ${runResult.status}`}>
                    <strong>{runResult.duplicate ? "duplicate" : runResult.status}</strong>
                    <span>{runResult.action_results.length} action results</span>
                    <span>{String(runResult.condition_result.passed ?? "condition unknown")}</span>
                    <pre>{JSON.stringify(runResult, null, 2)}</pre>
                  </div>
                ) : null}
              </section>

              <section className="automationSection">
                <h4>Run history</h4>
                <div className="sectionRows">
                  {runHistory.map((run) => (
                    <div key={run.automation_run_id}>
                      <strong>{run.status}</strong>
                      <span>{run.trigger_entity_id ?? "manual"} · {formatTime(run.started_at)} · {run.action_results.length} actions</span>
                      <small>{run.automation_run_id}</small>
                    </div>
                  ))}
                  {!runHistory.length ? <p className="systemNote">No runs recorded</p> : null}
                </div>
              </section>

              <section className="automationSection">
                <h4>Dead-lettered actions</h4>
                <div className="sectionRows">
                  {deadLetteredActions.map((item) => (
                    <div key={`${item.runId}-${item.index}`}>
                      <strong>{automationActionType(item.action)}</strong>
                      <span>{item.runId} · {automationActionReason(item.action)}</span>
                      <small>{JSON.stringify(item.action)}</small>
                    </div>
                  ))}
                  {!deadLetteredActions.length ? <p className="systemNote">No dead-lettered actions</p> : null}
                </div>
              </section>

              <section className="automationSection">
                <h4>Notification targets</h4>
                <div className="sectionRows">
                  {targets.map((target) => (
                    <div key={target.target_id}>
                      <strong>{target.display_name}</strong>
                      <span>{target.type} · {target.status} · {target.config_secret_refs.join(", ") || "no secrets"}</span>
                    </div>
                  ))}
                  {!targets.length ? <p className="systemNote">No targets</p> : null}
                </div>
              </section>
            </div>
          </>
        ) : (
          <div className="emptyState">{stateText}</div>
        )}
      </section>
    </div>
  );
}

function PromptDiffSummary(props: { diff: PromptDiffResult }) {
  const messageDiff = asRecord(props.diff.message_level_diff);
  const messageChanges = recordsFrom(messageDiff.changes);
  return (
    <div className="diffSummaryRows">
      <strong>Diff summary</strong>
      <span>Variables schema changed {props.diff.variables_schema_changed ? "yes" : "no"}</span>
      <span>
        Messages {String(messageDiff.status ?? "unknown")} · count delta {formatSignedInteger(numberFromUnknown(messageDiff.message_count_delta))} · changed {String(messageDiff.changed_message_count ?? 0)}
      </span>
      {messageChanges.slice(0, 4).map((change, index) => (
        <small key={`${String(change.index ?? index)}-${String(change.change_type ?? "change")}`}>
          {String(change.change_type ?? "changed")} message {String(change.index ?? index)}
        </small>
      ))}
      <LinkedEvalDiffRows diff={props.diff.linked_eval_result_diff} />
      <TagMovementRows events={props.diff.tag_movement_history} />
    </div>
  );
}

function LinkedEvalDiffRows(props: { diff: Record<string, unknown> }) {
  const oldSummary = asRecord(props.diff.old);
  const newSummary = asRecord(props.diff.new);
  return (
    <div className="linkedEvalRows">
      <strong>Linked evals</strong>
      <span>Pass {formatSignedPercent(numberFromUnknown(props.diff.pass_rate_delta))} · invalid outputs {formatSignedInteger(numberFromUnknown(props.diff.invalid_output_count_delta))} · runs {formatSignedInteger(numberFromUnknown(props.diff.run_count_delta))}</span>
      <span>Old {formatLinkedEvalSummary(oldSummary)}</span>
      <span>New {formatLinkedEvalSummary(newSummary)}</span>
    </div>
  );
}

function TagMovementRows(props: { events: Array<Record<string, unknown>> }) {
  return (
    <div className="tagMovementRows">
      <strong>Tag movement</strong>
      {props.events.slice(0, 6).map((event, index) => (
        <span
          key={[
            String(event.tag ?? "tag"),
            String(event.previous_commit_id ?? "none"),
            String(event.new_commit_id ?? "none"),
            String(event.created_at ?? index),
            String(index)
          ].join("-")}
        >
          {String(event.tag ?? "tag")} {shortIdentifier(String(event.previous_commit_id ?? "none"))}
          {" -> "}
          {shortIdentifier(String(event.new_commit_id ?? "none"))}
        </span>
      ))}
      {!props.events.length ? <span>No tag movements</span> : null}
    </div>
  );
}

function DatasetEvalWorkspace(props: {
  client: OpenAbmClient;
  connection: ConnectionState;
  projectId: string;
  onOpenTrace: (traceId: string) => void;
}) {
  const { client, connection, projectId } = props;
  const [datasets, setDatasets] = useState<DatasetDefinition[]>([]);
  const [examples, setExamples] = useState<DatasetExample[]>([]);
  const [evalRuns, setEvalRuns] = useState<EvalRun[]>([]);
  const [evalAnalytics, setEvalAnalytics] = useState<EvalAnalytics | null>(null);
  const [evalResults, setEvalResults] = useState<EvalResult[]>([]);
  const [comparisonBaselineResults, setComparisonBaselineResults] = useState<EvalResult[]>([]);
  const [comparisonCandidateResults, setComparisonCandidateResults] = useState<EvalResult[]>([]);
  const [judges, setJudges] = useState<JudgeDefinition[]>([]);
  const [promptOptions, setPromptOptions] = useState<PromptDefinition[]>([]);
  const [agentConfigOptions, setAgentConfigOptions] = useState<AgentConfigDefinition[]>([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState("");
  const [selectedEvalRunId, setSelectedEvalRunId] = useState("");
  const [selectedJudgeId, setSelectedJudgeId] = useState("");
  const [selectedPromptVersionId, setSelectedPromptVersionId] = useState("");
  const [selectedAgentConfigVersionId, setSelectedAgentConfigVersionId] = useState("");
  const [deploymentContextId, setDeploymentContextId] = useState("");
  const [toolVersionIdsText, setToolVersionIdsText] = useState("");
  const [newDatasetName, setNewDatasetName] = useState("");
  const [newDatasetDescription, setNewDatasetDescription] = useState("");
  const [traceId, setTraceId] = useState("");
  const [labelsText, setLabelsText] = useState("");
  const [baselineId, setBaselineId] = useState("");
  const [candidateId, setCandidateId] = useState("");
  const [comparison, setComparison] = useState<EvalComparison | null>(null);
  const [stateText, setStateText] = useState("Datasets and evals need a live API");

  const selectedDataset = datasets.find((dataset) => dataset.dataset_id === selectedDatasetId) ?? datasets[0] ?? null;
  const selectedRun = evalRuns.find((run) => run.eval_run_id === selectedEvalRunId) ?? evalRuns[0] ?? null;
  const datasetRuns = selectedDataset
    ? evalRuns.filter((run) => run.dataset_version_id === selectedDataset.latest_version_id)
    : evalRuns;
  const promptVersionOptions = promptOptions.flatMap((prompt) =>
    (prompt.versions ?? []).map((version) => ({ prompt, version }))
  );
  const agentConfigVersionOptions = agentConfigOptions.flatMap((config) =>
    (config.versions ?? []).map((version) => ({ config, version }))
  );
  const topPromptAnalytics = evalAnalytics?.by_prompt_version[0];
  const topConfigAnalytics = evalAnalytics?.by_agent_config_version[0];
  const topDeploymentAnalytics = evalAnalytics?.by_deployment_context[0];

  async function loadWorkspace() {
    if (connection !== "live") {
      setDatasets([]);
      setExamples([]);
      setEvalRuns([]);
      setEvalAnalytics(null);
      setEvalResults([]);
      setComparisonBaselineResults([]);
      setComparisonCandidateResults([]);
      setJudges([]);
      setPromptOptions([]);
      setAgentConfigOptions([]);
      setStateText("fixture mode");
      return;
    }
    try {
      const [
        loadedDatasets,
        loadedRuns,
        loadedJudges,
        listedPrompts,
        listedConfigs,
        analytics
      ] = await Promise.all([
        client.listDatasets(projectId),
        client.listEvalRuns(projectId),
        client.listJudges(projectId),
        client.listPrompts(projectId),
        client.listAgentConfigs(projectId),
        client.getEvalAnalytics(projectId)
      ]);
      const [hydratedPrompts, hydratedConfigs] = await Promise.all([
        Promise.all(listedPrompts.map((prompt) => client.getPrompt(projectId, prompt.prompt_id))),
        Promise.all(
          listedConfigs.map((config) => client.getAgentConfig(projectId, config.agent_config_id))
        )
      ]);
      setDatasets(loadedDatasets);
      setEvalRuns(loadedRuns);
      setEvalAnalytics(analytics);
      setJudges(loadedJudges);
      setPromptOptions(hydratedPrompts);
      setAgentConfigOptions(hydratedConfigs);
      setSelectedDatasetId((current) =>
        loadedDatasets.some((dataset) => dataset.dataset_id === current)
          ? current
          : loadedDatasets[0]?.dataset_id ?? ""
      );
      setSelectedEvalRunId((current) =>
        loadedRuns.some((run) => run.eval_run_id === current)
          ? current
          : loadedRuns[0]?.eval_run_id ?? ""
      );
      setSelectedJudgeId((current) =>
        loadedJudges.some((judge) => judge.judge_id === current)
          ? current
          : loadedJudges[0]?.judge_id ?? ""
      );
      setSelectedPromptVersionId((current) =>
        hydratedPrompts.some((prompt) =>
          (prompt.versions ?? []).some((version) => version.prompt_version_id === current)
        )
          ? current
          : ""
      );
      setSelectedAgentConfigVersionId((current) =>
        hydratedConfigs.some((config) =>
          (config.versions ?? []).some((version) => version.agent_config_version_id === current)
        )
          ? current
          : ""
      );
      setStateText(`${loadedDatasets.length} datasets · ${loadedRuns.length} evals`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "request failed");
    }
  }

  useEffect(() => {
    void loadWorkspace();
  }, [client, connection, projectId]);

  useEffect(() => {
    let cancelled = false;
    async function loadDatasetDetail() {
      if (connection !== "live" || !selectedDataset) {
        setExamples([]);
        return;
      }
      try {
        const loaded = await client.listDatasetExamples(projectId, selectedDataset.dataset_id);
        if (!cancelled) setExamples(loaded);
      } catch (error) {
        if (!cancelled) setStateText(error instanceof Error ? error.message : "examples unavailable");
      }
    }
    void loadDatasetDetail();
    return () => {
      cancelled = true;
    };
  }, [client, connection, projectId, selectedDataset?.dataset_id]);

  useEffect(() => {
    let cancelled = false;
    async function loadResults() {
      if (connection !== "live" || !selectedRun) {
        setEvalResults([]);
        return;
      }
      try {
        const loaded = await client.listEvalResults(projectId, selectedRun.eval_run_id);
        if (!cancelled) setEvalResults(loaded);
      } catch (error) {
        if (!cancelled) setStateText(error instanceof Error ? error.message : "eval results unavailable");
      }
    }
    void loadResults();
    return () => {
      cancelled = true;
    };
  }, [client, connection, projectId, selectedRun?.eval_run_id]);

  async function createDataset() {
    if (connection !== "live" || !newDatasetName.trim()) return;
    try {
      const created = await client.createDataset(projectId, newDatasetName.trim(), newDatasetDescription.trim());
      setDatasets((current) => [created, ...current]);
      setSelectedDatasetId(created.dataset_id);
      setNewDatasetName("");
      setNewDatasetDescription("");
      setStateText(`created ${created.name}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "dataset creation failed");
    }
  }

  async function addTraceExample() {
    if (connection !== "live" || !selectedDataset || !traceId.trim()) return;
    try {
      const labels = labelsText.split(",").map((label) => label.trim()).filter(Boolean);
      const example = await client.addTraceToDataset(projectId, selectedDataset.dataset_id, traceId.trim(), labels);
      setExamples((current) => [example, ...current]);
      setTraceId("");
      setLabelsText("");
      setStateText(`added trace ${example.source_trace_id}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "add trace failed");
    }
  }

  async function runSelectedEval() {
    if (connection !== "live" || !selectedDataset || !selectedJudgeId) return;
    try {
      const toolVersionIds = toolVersionIdsText
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      const runtimeContext: Record<string, unknown> = {};
      if (deploymentContextId.trim()) {
        runtimeContext.deployment_context_id = deploymentContextId.trim();
      }
      if (toolVersionIds.length) {
        runtimeContext.tool_version_ids = toolVersionIds;
      }
      const run = await client.runEval(
        projectId,
        selectedDataset.latest_version_id,
        [selectedJudgeId],
        {
          baselineEvalRunId: baselineId || undefined,
          promptVersionId: selectedPromptVersionId || undefined,
          agentConfigVersionId: selectedAgentConfigVersionId || undefined,
          runtimeContext
        }
      );
      setEvalRuns((current) => [run, ...current]);
      setSelectedEvalRunId(run.eval_run_id);
      setCandidateId(run.eval_run_id);
      setComparison(null);
      setStateText(`eval completed: ${run.eval_run_id}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "eval run failed");
    }
  }

  async function compareRuns() {
    if (connection !== "live" || !baselineId || !candidateId) return;
    try {
      const [result, baselineResults, candidateResults] = await Promise.all([
        client.compareEvalRuns(projectId, baselineId, candidateId),
        client.listEvalResults(projectId, baselineId),
        client.listEvalResults(projectId, candidateId)
      ]);
      setComparison(result);
      setComparisonBaselineResults(baselineResults);
      setComparisonCandidateResults(candidateResults);
      setStateText("comparison ready");
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "compare failed");
    }
  }

  return (
    <div className="datasetGrid">
      <section className="panel datasetList">
        <div className="toolbar">
          <button className="iconButton" onClick={() => void loadWorkspace()} aria-label="Refresh datasets and evals">
            <TimerReset size={16} />
          </button>
          <span className="systemNote">{stateText}</span>
        </div>
        <div className="createStrip">
          <input value={newDatasetName} onChange={(event) => setNewDatasetName(event.target.value)} placeholder="Dataset name" />
          <input value={newDatasetDescription} onChange={(event) => setNewDatasetDescription(event.target.value)} placeholder="Description" />
          <button onClick={() => void createDataset()}>
            <Database size={15} />
            Create
          </button>
        </div>
        <div className="datasetRows">
          {datasets.map((dataset) => (
            <button
              className={dataset.dataset_id === selectedDataset?.dataset_id ? "selectedDataset" : ""}
              key={dataset.dataset_id}
              onClick={() => setSelectedDatasetId(dataset.dataset_id)}
            >
              <span className={`judgeStatus ${dataset.status}`}>{dataset.status}</span>
              <strong>{dataset.name}</strong>
              <small>{dataset.latest_version_id}</small>
            </button>
          ))}
          {!datasets.length ? <div className="emptyState">No datasets</div> : null}
        </div>
      </section>

      <section className="panel datasetDetail">
        {selectedDataset ? (
          <>
            <div className="detailHeader">
              <div>
                <p className="sectionLabel">dataset</p>
                <h3>{selectedDataset.name}</h3>
              </div>
              <span className={`judgeStatus ${selectedDataset.status}`}>{selectedDataset.status}</span>
            </div>
            <p className="entityDescription">{selectedDataset.description ?? selectedDataset.dataset_id}</p>
            <div className="metricsRow datasetMetrics">
              <Metric icon={<Database />} label="Examples" value={String(examples.length)} />
              <Metric icon={<Play />} label="Eval runs" value={String(datasetRuns.length)} />
              <Metric icon={<GitBranch />} label="Version" value={selectedDataset.latest_version_id} />
              <Metric icon={<Split />} label="Analyzed runs" value={String(evalAnalytics?.run_count ?? 0)} />
            </div>
            <div className="datasetSections">
              <section className="datasetSection">
                <h4>Examples</h4>
                <div className="exampleAdd">
                  <input value={traceId} onChange={(event) => setTraceId(event.target.value)} placeholder="trace_id" />
                  <input value={labelsText} onChange={(event) => setLabelsText(event.target.value)} placeholder="labels, comma separated" />
                  <button onClick={() => void addTraceExample()}>
                    <FileSearch size={15} />
                    Add trace
                  </button>
                </div>
                <div className="exampleRows">
                  {examples.map((example) => (
                    <div key={example.dataset_example_id}>
                      <strong>{example.source_trace_id}</strong>
                      <span>{example.labels.join(", ") || "no labels"}</span>
                      <small>{example.dataset_example_id}</small>
                    </div>
                  ))}
                  {!examples.length ? <p className="systemNote">No examples yet</p> : null}
                </div>
              </section>

              <section className="datasetSection">
                <h4>Run eval</h4>
                <div className="evalForm">
                  <label>
                    Judge
                    <select value={selectedJudgeId} onChange={(event) => setSelectedJudgeId(event.target.value)}>
                      {judges.map((judge) => (
                        <option key={judge.judge_id} value={judge.judge_id}>{judge.name}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Baseline
                    <select value={baselineId} onChange={(event) => {
                      setBaselineId(event.target.value);
                      setComparison(null);
                    }}>
                      <option value="">None</option>
                      {datasetRuns.map((run) => (
                        <option key={run.eval_run_id} value={run.eval_run_id}>{run.eval_run_id}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Prompt version
                    <select value={selectedPromptVersionId} onChange={(event) => setSelectedPromptVersionId(event.target.value)}>
                      <option value="">None</option>
                      {promptVersionOptions.map(({ prompt, version }) => (
                        <option key={version.prompt_version_id} value={version.prompt_version_id}>
                          {prompt.name} · {shortIdentifier(version.commit_id)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Runtime config
                    <select value={selectedAgentConfigVersionId} onChange={(event) => setSelectedAgentConfigVersionId(event.target.value)}>
                      <option value="">None</option>
                      {agentConfigVersionOptions.map(({ config, version }) => (
                        <option key={version.agent_config_version_id} value={version.agent_config_version_id}>
                          {config.name} · v{version.version}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Deployment
                    <input value={deploymentContextId} onChange={(event) => setDeploymentContextId(event.target.value)} placeholder="deployment_context_id" />
                  </label>
                  <label>
                    Tool versions
                    <input value={toolVersionIdsText} onChange={(event) => setToolVersionIdsText(event.target.value)} placeholder="tool_v1, retriever_v2" />
                  </label>
                  <button className="primaryButton" onClick={() => void runSelectedEval()}>
                    <Play size={15} />
                    Run
                  </button>
                </div>
              </section>

              <section className="datasetSection evalHistory">
                <h4>Eval history</h4>
                <div className="exampleRows">
                  <div>
                    <strong>Prompt versions</strong>
                    <span>{formatEvalAnalyticsGroup(topPromptAnalytics)}</span>
                  </div>
                  <div>
                    <strong>Runtime configs</strong>
                    <span>{formatEvalAnalyticsGroup(topConfigAnalytics)}</span>
                  </div>
                  <div>
                    <strong>Deployments</strong>
                    <span>{formatEvalAnalyticsGroup(topDeploymentAnalytics)}</span>
                  </div>
                </div>
                <EvalTrendRows
                  interpretation={evalAnalytics?.trend_interpretation ?? null}
                  trend={evalAnalytics?.trend ?? []}
                />
                <div className="evalRows">
                  {datasetRuns.map((run) => (
                    <button
                      className={run.eval_run_id === selectedRun?.eval_run_id ? "selectedEval" : ""}
                      key={run.eval_run_id}
                      onClick={() => {
                        setSelectedEvalRunId(run.eval_run_id);
                        setCandidateId(run.eval_run_id);
                        setComparison(null);
                      }}
                    >
                      <span className={`judgeStatus ${run.status}`}>{run.status}</span>
                      <strong>{run.eval_run_id}</strong>
                      <small>{formatEvalSummary(run.summary)}</small>
                    </button>
                  ))}
                  {!datasetRuns.length ? <p className="systemNote">No eval runs for this dataset</p> : null}
                </div>
              </section>

              <section className="datasetSection evalResults">
                <h4>Selected run</h4>
                {selectedRun ? (
                  <>
                    <dl className="reviewFacts">
                      <div>
                        <dt>Summary</dt>
                        <dd>{formatEvalSummary(selectedRun.summary)}</dd>
                      </div>
                      <div>
                        <dt>Judges</dt>
                        <dd>{selectedRun.judges.map((judge) => String(judge.name ?? judge.judge_id ?? judge.judge_type)).join(", ")}</dd>
                      </div>
                      <div>
                        <dt>Prompt</dt>
                        <dd>{selectedRun.prompt_version_id ?? "none"}</dd>
                      </div>
                      <div>
                        <dt>Runtime config</dt>
                        <dd>{selectedRun.agent_config_version_id ?? "none"}</dd>
                      </div>
                      <div>
                        <dt>Runtime context</dt>
                        <dd>{formatEvalRuntimeContext(selectedRun.runtime_context)}</dd>
                      </div>
                    </dl>
                    <div className="resultRows">
                      {evalResults.map((result) => (
                        <div key={result.eval_result_id}>
                          <strong>{result.dataset_example_id}</strong>
                          <span>{result.status} · {result.scores.map(formatScore).join(", ") || "no scores"}</span>
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="systemNote">No eval selected</p>
                )}
              </section>

              <section className="datasetSection">
                <h4>Compare</h4>
                <div className="evalForm">
                  <label>
                    Baseline
                    <select value={baselineId} onChange={(event) => {
                      setBaselineId(event.target.value);
                      setComparison(null);
                    }}>
                      <option value="">Select baseline</option>
                      {datasetRuns.map((run) => (
                        <option key={run.eval_run_id} value={run.eval_run_id}>{run.eval_run_id}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Candidate
                    <select value={candidateId} onChange={(event) => {
                      setCandidateId(event.target.value);
                      setComparison(null);
                    }}>
                      <option value="">Select candidate</option>
                      {datasetRuns.map((run) => (
                        <option key={run.eval_run_id} value={run.eval_run_id}>{run.eval_run_id}</option>
                      ))}
                    </select>
                  </label>
                  <button onClick={() => void compareRuns()}>
                    <Split size={15} />
                    Compare
                  </button>
                </div>
                {comparison ? (
                  <div className="comparisonBox">
                    <strong>Pass delta {formatSignedPercent(comparison.pass_rate_delta)}</strong>
                    <span>Score delta {formatSignedNumber(comparison.avg_score_delta)} · invalid outputs {formatSignedInteger(comparison.invalid_judge_output_delta)}</span>
                    <span>Cost {formatCurrencyDelta(comparison.cost_delta)} · latency {formatDurationDelta(comparison.latency_delta)} · tokens {formatIntegerDelta(comparison.token_delta)}</span>
                    <span>Fixed {comparison.fixed_failures.length} · new {comparison.new_failures.length} · unchanged {comparison.unchanged_failures.length}</span>
                    <span>{formatEvalProvenanceComparison(comparison.provenance_comparison)}</span>
                    <span>Baseline {formatEvalSummary(comparison.baseline_summary)}</span>
                    <span>Candidate {formatEvalSummary(comparison.candidate_summary)}</span>
                    <EvalBehaviorShiftRows
                      shift={comparison.behavior_distribution_shift}
                      onOpenTrace={props.onOpenTrace}
                    />
                    <EvalHistoryRows runs={comparison.historical_runs} />
                    <EvalFailureRows
                      title="New failures"
                      exampleIds={comparison.new_failures}
                      examples={examples}
                      baselineResults={comparisonBaselineResults}
                      candidateResults={comparisonCandidateResults}
                      onOpenTrace={props.onOpenTrace}
                    />
                    <EvalFailureRows
                      title="Fixed failures"
                      exampleIds={comparison.fixed_failures}
                      examples={examples}
                      baselineResults={comparisonBaselineResults}
                      candidateResults={comparisonCandidateResults}
                      onOpenTrace={props.onOpenTrace}
                    />
                    <EvalFailureRows
                      title="Unchanged failures"
                      exampleIds={comparison.unchanged_failures}
                      examples={examples}
                      baselineResults={comparisonBaselineResults}
                      candidateResults={comparisonCandidateResults}
                      onOpenTrace={props.onOpenTrace}
                    />
                  </div>
                ) : null}
              </section>
            </div>
          </>
        ) : (
          <div className="emptyState">{stateText}</div>
        )}
      </section>
    </div>
  );
}

function EvalBehaviorShiftRows(props: {
  shift: EvalComparison["behavior_distribution_shift"];
  onOpenTrace: (traceId: string) => void;
}) {
  const deltas = props.shift.deltas ?? [];
  return (
    <div className="comparisonShiftRows">
      <strong>Behavior shift</strong>
      {deltas.map((delta) => {
        const traceIds = [...delta.baseline_trace_ids, ...delta.candidate_trace_ids];
        return (
          <div key={delta.behavior_id}>
            <div className="comparisonShiftHeader">
              <strong>{delta.name || delta.behavior_id}</strong>
              {delta.severity ? (
                <span className={`severityBadge ${delta.severity}`}>{delta.severity}</span>
              ) : null}
            </div>
            <span>
              Baseline {delta.baseline_match_count} · candidate {delta.candidate_match_count} · delta {formatSignedInteger(delta.match_count_delta)}
            </span>
            <span>Status delta {formatCounts(delta.status_count_delta)}</span>
            {traceIds.length ? (
              <div className="traceButtonRow">
                {traceIds.map((traceId) => (
                  <button key={traceId} onClick={() => props.onOpenTrace(traceId)}>
                    <FileSearch size={14} />
                    {shortIdentifier(traceId)}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        );
      })}
      {!deltas.length ? <span>No labeled behavior changes</span> : null}
    </div>
  );
}

function EvalTrendRows(props: {
  interpretation?: EvalAnalytics["trend_interpretation"] | null;
  trend: EvalAnalytics["trend"];
}) {
  const rows = props.trend.slice(-6).reverse();
  return (
    <div className="comparisonShiftRows">
      <strong>Trend</strong>
      {props.interpretation ? (
        <span>
          {props.interpretation.status.replaceAll("_", " ")} · {props.interpretation.summary}
        </span>
      ) : null}
      {rows.map((run) => (
        <div key={run.eval_run_id}>
          <div className="comparisonShiftHeader">
            <strong>{shortIdentifier(run.eval_run_id)}</strong>
            <span className={`judgeStatus ${run.status}`}>{run.status}</span>
          </div>
          <span>
            Pass {formatPercent(run.pass_rate)} ({formatSignedPercent(run.pass_rate_delta)}) · invalid {run.invalid_output_count} ({formatSignedInteger(run.invalid_output_delta)})
          </span>
          <small>{formatEvalTrendRuntime(run)}</small>
        </div>
      ))}
      {!rows.length ? <span>No trend data yet</span> : null}
    </div>
  );
}

function EvalHistoryRows(props: { runs: EvalComparison["historical_runs"] }) {
  return (
    <div className="comparisonShiftRows">
      <strong>Run history</strong>
      {props.runs.map((run) => (
        <div key={run.eval_run_id}>
          <div className="comparisonShiftHeader">
            <strong>{shortIdentifier(run.eval_run_id)}</strong>
            <span className="statusBadge">{run.role}</span>
          </div>
          <span>
            Pass {formatPercent(run.pass_rate)} · score {formatNullableNumber(run.avg_score)} · invalid {run.invalid_output_count}
          </span>
          <span>
            Dataset {shortIdentifier(run.dataset_version_id)} · matched {formatStringList(run.matched_on)}
          </span>
          <small>{formatEvalHistoryRuntime(run)}</small>
        </div>
      ))}
      {!props.runs.length ? <span>No related historical runs</span> : null}
    </div>
  );
}

function EvalFailureRows(props: {
  title: string;
  exampleIds: string[];
  examples: DatasetExample[];
  baselineResults: EvalResult[];
  candidateResults: EvalResult[];
  onOpenTrace: (traceId: string) => void;
}) {
  const baselineByExample = new Map(
    props.baselineResults.map((result) => [result.dataset_example_id, result])
  );
  const candidateByExample = new Map(
    props.candidateResults.map((result) => [result.dataset_example_id, result])
  );
  const exampleById = new Map(props.examples.map((example) => [example.dataset_example_id, example]));

  return (
    <div className="comparisonFailureRows">
      <strong>{props.title}</strong>
      {props.exampleIds.map((exampleId) => {
        const baseline = baselineByExample.get(exampleId) ?? null;
        const candidate = candidateByExample.get(exampleId) ?? null;
        const example = exampleById.get(exampleId) ?? null;
        const traceId = example?.source_trace_id ?? candidate?.offline_trace_id ?? baseline?.offline_trace_id ?? "";
        return (
          <div key={exampleId}>
            <strong>{exampleId}</strong>
            <span>Baseline {formatEvalResult(baseline)}</span>
            <span>Candidate {formatEvalResult(candidate)}</span>
            <small>{traceId || "no source trace"}</small>
            {traceId ? (
              <button onClick={() => props.onOpenTrace(traceId)}>
                <FileSearch size={14} />
                Open trace
              </button>
            ) : null}
          </div>
        );
      })}
      {!props.exampleIds.length ? <span>No examples</span> : null}
    </div>
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
  const [traceOptions, setTraceOptions] = useState<TraceEnvelope[]>([]);
  const [testTraceId, setTestTraceId] = useState("");
  const [testScore, setTestScore] = useState<ScoreResult | null>(null);
  const [editorName, setEditorName] = useState("Refund wrong-tool rubric");
  const [editorDescription, setEditorDescription] = useState("Flags refund traces where the agent used an unrelated order lookup.");
  const [editorRubric, setEditorRubric] = useState('{\n  "fail": "The trace shows wrong or insufficient tool use.",\n  "pass": "The trace uses appropriate tools and evidence.",\n  "unsure": "The trace lacks enough evidence to decide."\n}');
  const [editorFailureModes, setEditorFailureModes] = useState("wrong_tool_for_refund");
  const [editorGoldenExamples, setEditorGoldenExamples] = useState("[]");
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
      setTraceOptions([]);
      setTestTraceId("");
      setTestScore(null);
      setStatusText("fixture mode");
      return;
    }
    try {
      const [loaded, loadedTraces] = await Promise.all([
        client.listJudges(projectId),
        client.listTraces(projectId)
      ]);
      setJudges(loaded);
      setTraceOptions(loadedTraces);
      setTestTraceId((current) =>
        loadedTraces.some((trace) => trace.trace_id === current)
          ? current
          : loadedTraces[0]?.trace_id ?? ""
      );
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

  useEffect(() => {
    if (!selectedJudge) return;
    setEditorName(selectedJudge.name);
    setEditorDescription(selectedJudge.description ?? "");
    const definition = latestJudgeVersion(selectedJudge)?.definition ?? {};
    const rubric = asRecord(definition.rubric);
    if (Object.keys(rubric).length) setEditorRubric(JSON.stringify(rubric, null, 2));
    const failureModes = Array.isArray(definition.failure_modes)
      ? definition.failure_modes.map(String).join(", ")
      : "";
    if (failureModes) setEditorFailureModes(failureModes);
    if (definition.golden_examples) setEditorGoldenExamples(JSON.stringify(definition.golden_examples, null, 2));
  }, [selectedJudge?.judge_id, selectedJudge?.versions?.length]);

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

  function editorDefinition() {
    return {
      judge_type: "rubric_judge",
      rubric: parseJsonObject(editorRubric),
      failure_modes: editorFailureModes
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
      require_span_citations: true,
      golden_examples: JSON.parse(editorGoldenExamples) as unknown
    };
  }

  async function createDraftFromEditor() {
    if (connection !== "live") return;
    try {
      const created = await client.createJudgeDraft(projectId, {
        name: editorName,
        description: editorDescription,
        judgeType: "rubric_judge",
        definition: editorDefinition()
      });
      setJudges((current) => [created, ...current.filter((judge) => judge.judge_id !== created.judge_id)]);
      setSelectedId(created.judge_id);
      setTestScore(null);
      setStatusText(`created ${created.name}`);
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : "judge draft creation failed");
    }
  }

  async function commitEditorVersion() {
    if (!selectedJudge || connection !== "live") return;
    try {
      const version = await client.commitJudgeVersion(projectId, selectedJudge.judge_id, editorDefinition());
      const freshJudge = await client.getJudge(projectId, selectedJudge.judge_id);
      setJudges((current) =>
        current.map((judge) => (judge.judge_id === freshJudge.judge_id ? freshJudge : judge))
      );
      setStatusText(`committed judge version ${version.version}`);
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : "judge version commit failed");
    }
  }

  async function runEditorTest() {
    if (!selectedJudge || !testTraceId || connection !== "live") return;
    try {
      const freshJudge = await client.getJudge(projectId, selectedJudge.judge_id);
      const payload = runnableJudgePayload(freshJudge);
      if (!payload) {
        setStatusText("selected judge has no runnable rubric version");
        return;
      }
      setStatusText(`testing ${freshJudge.name}`);
      const score = await client.runRubricJudge(projectId, testTraceId, payload);
      setTestScore(score);
      setReport(await client.getJudgeCalibrationReport(projectId, freshJudge.judge_id));
      setStatusText(`test returned ${formatScore(asRecord(score))}`);
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : "judge test failed");
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

              <section className="judgeSection judgeEditor">
                <h4>Editor</h4>
                <div className="policyGrid">
                  <label>
                    Name
                    <input value={editorName} onChange={(event) => setEditorName(event.target.value)} />
                  </label>
                  <label>
                    Description
                    <input value={editorDescription} onChange={(event) => setEditorDescription(event.target.value)} />
                  </label>
                </div>
                <label className="notesBox">
                  Rubric JSON
                  <textarea value={editorRubric} onChange={(event) => setEditorRubric(event.target.value)} spellCheck={false} />
                </label>
                <label className="notesBox">
                  Failure modes
                  <input value={editorFailureModes} onChange={(event) => setEditorFailureModes(event.target.value)} />
                </label>
                <label className="notesBox">
                  Golden examples JSON
                  <textarea value={editorGoldenExamples} onChange={(event) => setEditorGoldenExamples(event.target.value)} spellCheck={false} />
                </label>
                <div className="actionStrip">
                  <button onClick={() => void createDraftFromEditor()}>
                    <FileSearch size={15} />
                    Create draft
                  </button>
                  <button onClick={() => void commitEditorVersion()} disabled={!selectedJudge}>
                    <CheckCircle2 size={15} />
                    Commit version
                  </button>
                </div>
              </section>

              <section className="judgeSection">
                <h4>Output schema and test</h4>
                <pre>{JSON.stringify(rubricOutputSchemaPreview(), null, 2)}</pre>
                <div className="policyGrid">
                  <label>
                    Test trace
                    <select value={testTraceId} onChange={(event) => setTestTraceId(event.target.value)}>
                      <option value="">Select trace</option>
                      {traceOptions.map((trace) => (
                        <option key={trace.trace_id} value={trace.trace_id}>
                          {trace.trace_id} · {trace.status}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <button className="primaryButton" onClick={() => void runEditorTest()} disabled={!selectedJudge || !testTraceId}>
                  <Play size={15} />
                  Run test
                </button>
                {testScore ? (
                  <div className="promotionResult promoted">
                    <strong>{formatScore(asRecord(testScore))}</strong>
                    <span>{testScore.status} · evidence {testScore.evidence_span_ids.join(", ") || "none"}</span>
                  </div>
                ) : <p className="systemNote">No test result yet</p>}
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
  similarResult: SimilarTraceSearchResult | null;
  client: OpenAbmClient;
  connection: ConnectionState;
  projectId: string;
  onQueryChange: (value: string) => void;
  onStatusChange: (value: string) => void;
  onSearch: () => void;
  onApplySavedSearch: (savedSearch: SavedSearch) => void;
  onSelectTrace: (traceId: string) => void;
  onCheckSimilarity: () => void;
  onOpenPrompts: () => void;
  onOpenConfigs: () => void;
}) {
  const { traces, detail } = props;
  const [detailMode, setDetailMode] = useState<TraceDetailMode>("timeline");
  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([]);
  const [datasets, setDatasets] = useState<DatasetDefinition[]>([]);
  const [savedSearchName, setSavedSearchName] = useState("Current trace search");
  const [selectedSavedSearchId, setSelectedSavedSearchId] = useState("");
  const [datasetName, setDatasetName] = useState("Trace review set");
  const [selectedDatasetId, setSelectedDatasetId] = useState("");
  const [traceListState, setTraceListState] = useState("Trace list ready");
  const [scoresByTrace, setScoresByTrace] = useState<Record<string, ScoreResult[]>>({});
  const [behaviorMatchesByTrace, setBehaviorMatchesByTrace] = useState<Record<string, BehaviorMatch[]>>({});
  const [datasetMembershipByTrace, setDatasetMembershipByTrace] = useState<Record<string, DatasetMembership[]>>({});
  const [behaviorDefinitions, setBehaviorDefinitions] = useState<BehaviorDefinition[]>([]);
  const [promptDefinitions, setPromptDefinitions] = useState<PromptDefinition[]>([]);
  const [agentConfigDefinitions, setAgentConfigDefinitions] = useState<AgentConfigDefinition[]>([]);
  const [labelBehaviorId, setLabelBehaviorId] = useState("");
  const [judgeDefinitions, setJudgeDefinitions] = useState<JudgeDefinition[]>([]);
  const [selectedJudgeId, setSelectedJudgeId] = useState("");
  const [assertionText, setAssertionText] = useState('{\n  "forbidden_tools": []\n}');
  const [assertionResult, setAssertionResult] = useState<TraceAssertionResult | null>(null);
  const [selectedSpanId, setSelectedSpanId] = useState("");
  const selectedSpan = detail?.spans.find((span) => span.span_id === selectedSpanId) ?? detail?.spans[0] ?? null;
  const selectedSavedSearch = savedSearches.find((item) => item.saved_search_id === selectedSavedSearchId) ?? null;
  const selectedDataset = datasets.find((dataset) => dataset.dataset_id === selectedDatasetId) ?? datasets[0] ?? null;
  const selectedJudge = judgeDefinitions.find((judge) => judge.judge_id === selectedJudgeId) ?? judgeDefinitions[0] ?? null;

  async function loadTraceListTools() {
    if (props.connection !== "live") {
      setSavedSearches([]);
      setDatasets([]);
      setScoresByTrace({});
      setBehaviorMatchesByTrace({});
      setDatasetMembershipByTrace({});
      setBehaviorDefinitions([]);
      setPromptDefinitions([]);
      setAgentConfigDefinitions([]);
      setLabelBehaviorId("");
      setJudgeDefinitions([]);
      setSelectedJudgeId("");
      setAssertionResult(null);
      setTraceListState("fixture mode");
      return;
    }
    try {
      const [
        loadedSearches,
        loadedDatasets,
        loadedScores,
        loadedBehaviorMatches,
        loadedBehaviors,
        loadedJudges,
        listedPrompts,
        listedConfigs
      ] = await Promise.all([
        props.client.listSavedSearches(props.projectId),
        props.client.listDatasets(props.projectId),
        props.client.listScores(props.projectId),
        props.client.listBehaviorMatches(props.projectId),
        props.client.listBehaviors(props.projectId),
        props.client.listJudges(props.projectId),
        props.client.listPrompts(props.projectId),
        props.client.listAgentConfigs(props.projectId)
      ]);
      const [hydratedPrompts, hydratedConfigs] = await Promise.all([
        Promise.all(listedPrompts.map((prompt) => props.client.getPrompt(props.projectId, prompt.prompt_id))),
        Promise.all(
          listedConfigs.map((config) => props.client.getAgentConfig(props.projectId, config.agent_config_id))
        )
      ]);
      const datasetExamples = await Promise.all(
        loadedDatasets.map(async (dataset) => ({
          dataset,
          examples: await props.client.listDatasetExamples(props.projectId, dataset.dataset_id)
        }))
      );
      setSavedSearches(loadedSearches);
      setDatasets(loadedDatasets);
      setScoresByTrace(groupByTraceId(loadedScores));
      setBehaviorMatchesByTrace(groupByTraceId(loadedBehaviorMatches));
      setDatasetMembershipByTrace(groupDatasetMembership(datasetExamples));
      setBehaviorDefinitions(loadedBehaviors);
      setPromptDefinitions(hydratedPrompts);
      setAgentConfigDefinitions(hydratedConfigs);
      setJudgeDefinitions(loadedJudges);
      setLabelBehaviorId((current) =>
        loadedBehaviors.some((behavior) => behavior.behavior_id === current)
          ? current
          : loadedBehaviors[0]?.behavior_id ?? ""
      );
      setSelectedJudgeId((current) =>
        loadedJudges.some((judge) => judge.judge_id === current)
          ? current
          : loadedJudges[0]?.judge_id ?? ""
      );
      setSelectedSavedSearchId((current) =>
        loadedSearches.some((search) => search.saved_search_id === current)
          ? current
          : loadedSearches[0]?.saved_search_id ?? ""
      );
      setSelectedDatasetId((current) =>
        loadedDatasets.some((dataset) => dataset.dataset_id === current)
          ? current
          : loadedDatasets[0]?.dataset_id ?? ""
      );
      setTraceListState(
        `${loadedSearches.length} saved searches · ${loadedDatasets.length} datasets · ${loadedScores.length} scores · ${loadedBehaviorMatches.length} behavior matches`
      );
    } catch (error) {
      setTraceListState(error instanceof Error ? error.message : "trace list tools failed");
    }
  }

  useEffect(() => {
    void loadTraceListTools();
  }, [props.client, props.connection, props.projectId]);

  useEffect(() => {
    setSelectedSpanId(detail?.spans[0]?.span_id ?? "");
    setAssertionResult(null);
  }, [detail?.trace.trace_id]);

  async function createSavedSearch() {
    if (props.connection !== "live" || !savedSearchName.trim()) return;
    const queryObject = {
      filters: props.status ? { status: props.status } : {},
      full_text_query: props.query || null
    };
    try {
      const created = await props.client.createSavedSearch(props.projectId, savedSearchName.trim(), queryObject);
      setSavedSearches((current) => [created, ...current.filter((search) => search.saved_search_id !== created.saved_search_id)]);
      setSelectedSavedSearchId(created.saved_search_id);
      setTraceListState(`saved ${created.name}`);
    } catch (error) {
      setTraceListState(error instanceof Error ? error.message : "saved search creation failed");
    }
  }

  async function createDatasetForTraceList() {
    if (props.connection !== "live" || !datasetName.trim()) return null;
    try {
      const created = await props.client.createDataset(props.projectId, datasetName.trim(), "Created from trace list bulk action.");
      setDatasets((current) => [created, ...current.filter((dataset) => dataset.dataset_id !== created.dataset_id)]);
      setSelectedDatasetId(created.dataset_id);
      setTraceListState(`created ${created.name}`);
      return created;
    } catch (error) {
      setTraceListState(error instanceof Error ? error.message : "dataset creation failed");
      return null;
    }
  }

  async function addVisibleTracesToDataset() {
    if (props.connection !== "live" || !traces.length) return;
    const dataset = selectedDataset ?? (await createDatasetForTraceList());
    if (!dataset) return;
    try {
      const examples = await Promise.all(
        traces.map((trace) => props.client.addTraceToDataset(props.projectId, dataset.dataset_id, trace.trace_id, ["trace_list_bulk"]))
      );
      setTraceListState(`added ${examples.length} traces to ${dataset.name}`);
    } catch (error) {
      setTraceListState(error instanceof Error ? error.message : "bulk dataset action failed");
    }
  }

  async function addSelectedTraceToDataset() {
    if (props.connection !== "live" || !detail) return;
    const dataset = selectedDataset ?? (await createDatasetForTraceList());
    if (!dataset) return;
    try {
      const example = await props.client.addTraceToDataset(
        props.projectId,
        dataset.dataset_id,
        detail.trace.trace_id,
        ["trace_detail"]
      );
      setDatasetMembershipByTrace((current) => ({
        ...current,
        [detail.trace.trace_id]: [
          {
            dataset_id: dataset.dataset_id,
            dataset_name: dataset.name,
            dataset_example_id: example.dataset_example_id,
            labels: example.labels
          },
          ...(current[detail.trace.trace_id] ?? []).filter(
            (membership) => membership.dataset_example_id !== example.dataset_example_id
          )
        ]
      }));
      setTraceListState(`added ${detail.trace.trace_id} to ${dataset.name}`);
    } catch (error) {
      setTraceListState(error instanceof Error ? error.message : "trace add failed");
    }
  }

  async function labelSelectedTraceBehavior() {
    if (props.connection !== "live" || !detail || !labelBehaviorId) return;
    try {
      const result = await props.client.labelTraceBehavior(
        props.projectId,
        detail.trace.trace_id,
        labelBehaviorId,
        selectedSpan?.span_id
      );
      setBehaviorMatchesByTrace((current) => ({
        ...current,
        [detail.trace.trace_id]: [
          result.behavior_match,
          ...(current[detail.trace.trace_id] ?? []).filter(
            (match) =>
              !(
                match.behavior_id === result.behavior_match.behavior_id &&
                match.status === result.behavior_match.status
              )
          )
        ]
      }));
      setTraceListState(`labeled ${detail.trace.trace_id} with ${result.behavior_match.behavior_id}`);
    } catch (error) {
      setTraceListState(error instanceof Error ? error.message : "behavior label failed");
    }
  }

  async function runSelectedJudge() {
    if (props.connection !== "live" || !detail || !selectedJudge) return;
    try {
      const judge = await props.client.getJudge(props.projectId, selectedJudge.judge_id);
      const payload = runnableJudgePayload(judge);
      if (!payload) {
        setTraceListState("selected judge has no runnable rubric version");
        return;
      }
      setTraceListState(`running judge ${judge.name}`);
      const score = await props.client.runRubricJudge(props.projectId, detail.trace.trace_id, payload);
      setScoresByTrace((current) => ({
        ...current,
        [detail.trace.trace_id]: [
          score,
          ...(current[detail.trace.trace_id] ?? []).filter((item) => item.score_id !== score.score_id)
        ]
      }));
      setTraceListState(`judge ${judge.name} returned ${formatScore(asRecord(score))}`);
    } catch (error) {
      setTraceListState(error instanceof Error ? error.message : "judge run failed");
    }
  }

  async function runAssertionCheck() {
    if (props.connection !== "live" || !detail) return;
    try {
      const assertions = parseJsonObject(assertionText);
      const result = await props.client.checkTraceAssertions(
        props.projectId,
        detail.trace.trace_id,
        assertions
      );
      setAssertionResult(result);
      setTraceListState(`deterministic check ${result.status}`);
    } catch (error) {
      setTraceListState(error instanceof Error ? error.message : "deterministic check failed");
    }
  }

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
        <div className="traceListActions">
          <div className="savedSearchControls">
            <input value={savedSearchName} onChange={(event) => setSavedSearchName(event.target.value)} placeholder="Saved search name" />
            <button onClick={() => void createSavedSearch()}>
              <FileSearch size={15} />
              Save
            </button>
            <select value={selectedSavedSearchId} onChange={(event) => setSelectedSavedSearchId(event.target.value)}>
              <option value="">Select saved search</option>
              {savedSearches.map((savedSearch) => (
                <option key={savedSearch.saved_search_id} value={savedSearch.saved_search_id}>
                  {savedSearch.name}
                </option>
              ))}
            </select>
            <button onClick={() => selectedSavedSearch ? props.onApplySavedSearch(selectedSavedSearch) : undefined}>
              <Search size={15} />
              Apply
            </button>
          </div>
          <div className="savedSearchControls">
            <input value={datasetName} onChange={(event) => setDatasetName(event.target.value)} placeholder="Dataset name" />
            <button onClick={() => void createDatasetForTraceList()}>
              <Database size={15} />
              New dataset
            </button>
            <select value={selectedDataset?.dataset_id ?? ""} onChange={(event) => setSelectedDatasetId(event.target.value)}>
              <option value="">Select dataset</option>
              {datasets.map((dataset) => (
                <option key={dataset.dataset_id} value={dataset.dataset_id}>
                  {dataset.name}
                </option>
              ))}
            </select>
            <button onClick={() => void addVisibleTracesToDataset()}>
              <CheckCircle2 size={15} />
              Add visible
            </button>
          </div>
          <p className="systemNote">{traceListState}</p>
        </div>
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>Trace</th>
                <th>Latency</th>
                <th>Tokens</th>
                <th>Cost</th>
                <th>Badges</th>
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
                  <td>{traceLatency(trace)}</td>
                  <td>{traceTokenSummary(trace, scoresByTrace[trace.trace_id] ?? [])}</td>
                  <td>{traceCostSummary(trace, scoresByTrace[trace.trace_id] ?? [])}</td>
                  <td>
                    <TraceBadges
                      badges={traceBadges(
                        trace,
                        scoresByTrace[trace.trace_id] ?? [],
                        behaviorMatchesByTrace[trace.trace_id] ?? []
                      )}
                    />
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
            <TraceRuntimeProvenance
              trace={detail.trace}
              prompts={promptDefinitions}
              agentConfigs={agentConfigDefinitions}
              onOpenPrompts={props.onOpenPrompts}
              onOpenConfigs={props.onOpenConfigs}
            />
            <div className="traceModeTabs" role="tablist" aria-label="Trace detail modes">
              {traceModeLabels.map((mode) => (
                <button
                  key={mode.value}
                  className={detailMode === mode.value ? "active" : ""}
                  onClick={() => setDetailMode(mode.value)}
                  role="tab"
                  aria-selected={detailMode === mode.value}
                >
                  {mode.label}
                </button>
              ))}
            </div>
            <TraceModeView
              detail={detail}
              mode={detailMode}
              selectedSpanId={selectedSpan?.span_id ?? ""}
              onSelectSpan={setSelectedSpanId}
            />
            <Inspector span={selectedSpan} />
            <TraceEvidencePanel
              trace={detail.trace}
              scores={scoresByTrace[detail.trace.trace_id] ?? []}
              behaviorMatches={behaviorMatchesByTrace[detail.trace.trace_id] ?? []}
              datasetMemberships={datasetMembershipByTrace[detail.trace.trace_id] ?? []}
              similarResult={props.similarResult}
              assertionResult={assertionResult}
            />
            <div className="actionStrip">
              <button onClick={props.onCheckSimilarity}>
                <Search size={15} />
                Similar
              </button>
              <select
                value={selectedJudge?.judge_id ?? ""}
                onChange={(event) => setSelectedJudgeId(event.target.value)}
                aria-label="Rubric judge"
              >
                <option value="">Select judge</option>
                {judgeDefinitions.map((judge) => (
                  <option key={judge.judge_id} value={judge.judge_id}>
                    {judge.name}
                  </option>
                ))}
              </select>
              <button onClick={() => void runSelectedJudge()} disabled={!selectedJudge}>
                <Braces size={15} />
                Run judge
              </button>
              <select
                value={labelBehaviorId}
                onChange={(event) => setLabelBehaviorId(event.target.value)}
                aria-label="Behavior label"
              >
                <option value="">Select behavior</option>
                {behaviorDefinitions.map((behavior) => (
                  <option key={behavior.behavior_id} value={behavior.behavior_id}>
                    {behavior.name}
                  </option>
                ))}
              </select>
              <button onClick={() => void labelSelectedTraceBehavior()} disabled={!labelBehaviorId}>
                <GitBranch size={15} />
                Label behavior
              </button>
              <button onClick={() => void runAssertionCheck()}>
                <Braces size={15} />
                Deterministic check
              </button>
              <button onClick={() => void addSelectedTraceToDataset()}>
                <Database size={15} />
                Add trace
              </button>
            </div>
            <label className="assertionBox">
              Assertions JSON
              <textarea value={assertionText} onChange={(event) => setAssertionText(event.target.value)} spellCheck={false} />
            </label>
            <p className="systemNote">{props.similarState}</p>
          </>
        ) : (
          <div className="emptyState">No trace selected</div>
        )}
      </section>
    </div>
  );
}

const traceModeLabels: Array<{ value: TraceDetailMode; label: string }> = [
  { value: "tree", label: "Span tree" },
  { value: "timeline", label: "Timeline" },
  { value: "conversation", label: "Conversation" },
  { value: "tools", label: "Tools" },
  { value: "code", label: "Code/error" }
];

function TraceRuntimeProvenance(props: {
  trace: TraceEnvelope;
  prompts: PromptDefinition[];
  agentConfigs: AgentConfigDefinition[];
  onOpenPrompts: () => void;
  onOpenConfigs: () => void;
}) {
  const promptMatch = findPromptVersion(props.prompts, props.trace.prompt_version_id);
  const configMatch = findAgentConfigVersion(
    props.agentConfigs,
    props.trace.agent_config_version_id,
  );
  return (
    <div className="runtimeProvenancePanel">
      <div>
        <strong>Prompt version</strong>
        <span>{formatPromptVersionLink(promptMatch, props.trace.prompt_version_id)}</span>
        <button onClick={props.onOpenPrompts}>
          <Split size={14} />
          Registry
        </button>
      </div>
      <div>
        <strong>Runtime config</strong>
        <span>{formatAgentConfigVersionLink(configMatch, props.trace.agent_config_version_id)}</span>
        <button onClick={props.onOpenConfigs}>
          <KeyRound size={14} />
          Configs
        </button>
      </div>
      <div>
        <strong>Deployment</strong>
        <span>{props.trace.deployment_context_id ?? "none"}</span>
      </div>
      <div>
        <strong>Tool versions</strong>
        <span>{formatStringList(props.trace.tool_version_ids)}</span>
      </div>
    </div>
  );
}

function TraceModeView(props: {
  detail: TraceDetail;
  mode: TraceDetailMode;
  selectedSpanId: string;
  onSelectSpan: (spanId: string) => void;
}) {
  const { detail, mode, selectedSpanId, onSelectSpan } = props;
  if (mode === "tree") return <SpanTree detail={detail} selectedSpanId={selectedSpanId} onSelectSpan={onSelectSpan} />;
  if (mode === "conversation") return <ConversationView detail={detail} selectedSpanId={selectedSpanId} onSelectSpan={onSelectSpan} />;
  if (mode === "tools") return <ToolSequenceView detail={detail} selectedSpanId={selectedSpanId} onSelectSpan={onSelectSpan} />;
  if (mode === "code") return <CodeErrorView detail={detail} selectedSpanId={selectedSpanId} onSelectSpan={onSelectSpan} />;
  return <Timeline rows={detail.reconstruction.timeline_rows} selectedSpanId={selectedSpanId} onSelectSpan={onSelectSpan} />;
}

function SpanTree(props: { detail: TraceDetail; selectedSpanId: string; onSelectSpan: (spanId: string) => void }) {
  const { detail, selectedSpanId, onSelectSpan } = props;
  const roots = detail.reconstruction.span_tree.length ? detail.reconstruction.span_tree : buildSpanTree(detail.spans);
  return (
    <div className="traceModePanel spanTreePanel">
      {roots.map((node) => (
        <SpanTreeNodeView
          key={node.span.span_id}
          node={node}
          depth={0}
          detail={detail}
          selectedSpanId={selectedSpanId}
          onSelectSpan={onSelectSpan}
        />
      ))}
      {detail.reconstruction.missing_parent_group.map((node) => (
        <SpanTreeNodeView
          key={node.span.span_id}
          node={node}
          depth={0}
          detail={detail}
          selectedSpanId={selectedSpanId}
          onSelectSpan={onSelectSpan}
          missing
        />
      ))}
      {!roots.length && !detail.reconstruction.missing_parent_group.length ? (
        <p className="systemNote">No span tree available</p>
      ) : null}
    </div>
  );
}

function SpanTreeNodeView(props: {
  node: SpanNode;
  depth: number;
  detail: TraceDetail;
  selectedSpanId: string;
  onSelectSpan: (spanId: string) => void;
  missing?: boolean;
}) {
  const { node, depth, detail, selectedSpanId, onSelectSpan, missing } = props;
  const payloadState = detail.reconstruction.payload_availability[node.span.span_id] ?? node.payload_state;
  return (
    <div className="spanTreeNode" style={{ marginLeft: `${Math.min(depth * 18, 72)}px` }}>
      <button
        className={`spanTreeCard ${selectedSpanId === node.span.span_id ? "selectedSpanCard" : ""}`}
        onClick={() => onSelectSpan(node.span.span_id)}
      >
        <span className={`dot ${node.span.status}`} />
        <div>
          <strong>{node.span.name}</strong>
          <small>
            {node.span.span_type} · {node.span.status} · input {payloadState?.input ?? "unknown"} · output {payloadState?.output ?? "unknown"}
            {missing ? " · missing parent" : ""}
          </small>
        </div>
      </button>
      {node.children.map((child) => (
        <SpanTreeNodeView
          key={child.span.span_id}
          node={child}
          depth={depth + 1}
          detail={detail}
          selectedSpanId={selectedSpanId}
          onSelectSpan={onSelectSpan}
        />
      ))}
    </div>
  );
}

function Timeline(props: { rows: TimelineRow[]; selectedSpanId: string; onSelectSpan: (spanId: string) => void }) {
  const { rows, selectedSpanId, onSelectSpan } = props;
  return (
    <div className="traceModePanel timeline">
      {rows.map((row) => (
        <button
          className={`timelineRow ${selectedSpanId === row.span_id ? "selectedSpanCard" : ""}`}
          key={row.span_id}
          onClick={() => onSelectSpan(row.span_id)}
        >
          <span className={`dot ${row.status}`} />
          <div>
            <strong>{row.name}</strong>
            <small>{row.span_type} · {formatTime(row.started_at)}</small>
          </div>
        </button>
      ))}
    </div>
  );
}

function ConversationView(props: { detail: TraceDetail; selectedSpanId: string; onSelectSpan: (spanId: string) => void }) {
  const { detail, selectedSpanId, onSelectSpan } = props;
  const rows = conversationRows(detail);
  return (
    <div className="traceModePanel conversationRows">
      {rows.map((row, index) => (
        <button
          className={`conversationRow ${row.role} ${selectedSpanId === row.spanId ? "selectedSpanCard" : ""}`}
          key={`${row.spanId}-${row.role}-${index}`}
          onClick={() => onSelectSpan(row.spanId)}
        >
          <span>{row.role}</span>
          <div>
            <strong>{row.title}</strong>
            <p>{row.text}</p>
            <small>{row.redactionState} · {row.spanType}</small>
          </div>
        </button>
      ))}
      {!rows.length ? <p className="systemNote">No conversation payloads captured</p> : null}
      {detail.spans.flatMap((span) => span.events).length ? (
        <div className="inlineAnnotations">
          {detail.spans.flatMap((span) =>
            span.events.map((event) => (
              <div key={`${span.span_id}-${event.name}-${event.time}`}>
                <strong>{event.name}</strong>
                <span>{JSON.stringify(event.attributes)}</span>
              </div>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}

function ToolSequenceView(props: { detail: TraceDetail; selectedSpanId: string; onSelectSpan: (spanId: string) => void }) {
  const { detail, selectedSpanId, onSelectSpan } = props;
  const tools = detail.spans.filter((span) => span.span_type === "tool" || Boolean(span.attributes["tool.name"]));
  return (
    <div className="traceModePanel toolSequence">
      {tools.map((span, index) => (
        <button
          className={`toolStep ${selectedSpanId === span.span_id ? "selectedSpanCard" : ""}`}
          key={span.span_id}
          onClick={() => onSelectSpan(span.span_id)}
        >
          <span>{index + 1}</span>
          <div>
            <strong>{String(span.attributes["tool.name"] ?? span.name)}</strong>
            <small>{span.status} · {formatTime(span.started_at)} · {span.span_id}</small>
            <dl>
              <div>
                <dt>Input</dt>
                <dd>{payloadText(span.input)}</dd>
              </div>
              <div>
                <dt>Output</dt>
                <dd>{payloadText(span.output)}</dd>
              </div>
            </dl>
          </div>
        </button>
      ))}
      {!tools.length ? <p className="systemNote">No tool calls captured</p> : null}
    </div>
  );
}

function CodeErrorView(props: { detail: TraceDetail; selectedSpanId: string; onSelectSpan: (spanId: string) => void }) {
  const { detail, selectedSpanId, onSelectSpan } = props;
  const rows = detail.spans.filter(hasCodeOrErrorContext);
  const deployment = Object.fromEntries(
    Object.entries(detail.trace.attributes).filter(([key]) =>
      key.startsWith("deployment.") || key.startsWith("code.") || key.startsWith("service.")
    )
  );
  return (
    <div className="traceModePanel codeErrorRows">
      {Object.keys(deployment).length ? (
        <div className="codeContextBlock">
          <strong>Deployment and code context</strong>
          <pre>{JSON.stringify(deployment, null, 2)}</pre>
        </div>
      ) : null}
      {rows.map((span) => (
        <button
          className={`codeErrorRow ${selectedSpanId === span.span_id ? "selectedSpanCard" : ""}`}
          key={span.span_id}
          onClick={() => onSelectSpan(span.span_id)}
        >
          <div>
            <strong>{span.name}</strong>
            <small>{span.span_type} · {span.status} · {span.span_id}</small>
          </div>
          <pre>{JSON.stringify(codeErrorAttributes(span), null, 2)}</pre>
        </button>
      ))}
      {!rows.length && !Object.keys(deployment).length ? (
        <p className="systemNote">No code or error context captured for this trace</p>
      ) : null}
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
      <dl className="reviewFacts inspectorFacts">
        <div>
          <dt>Span</dt>
          <dd>{span.span_id}</dd>
        </div>
        <div>
          <dt>Parent</dt>
          <dd>{span.parent_span_id ?? "root"}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{span.status}</dd>
        </div>
        <div>
          <dt>Latency</dt>
          <dd>{spanLatency(span)}</dd>
        </div>
      </dl>
      <div className="payloadGrid">
        <PayloadViewer title="Input payload" payload={span.input} />
        <PayloadViewer title="Output payload" payload={span.output} />
      </div>
      <div className="inspectorSections">
        <section>
          <h4>Events</h4>
          {span.events.length ? (
            <div className="eventRows">
              {span.events.map((event) => (
                <div key={`${event.name}-${event.time}`}>
                  <strong>{event.name}</strong>
                  <small>{formatTime(event.time)}</small>
                  <pre>{JSON.stringify(event.attributes, null, 2)}</pre>
                </div>
              ))}
            </div>
          ) : (
            <p className="systemNote">No events captured</p>
          )}
        </section>
        <section>
          <h4>Attributes</h4>
          <pre>{JSON.stringify(span.attributes, null, 2)}</pre>
        </section>
      </div>
    </div>
  );
}

function PayloadViewer({ title, payload }: { title: string; payload: SpanEnvelope["input"] }) {
  return (
    <section className="payloadViewer">
      <div>
        <h4>{title}</h4>
        <span>{payload?.redaction_state ?? payload?.mode ?? "none"}</span>
      </div>
      <pre>{payloadText(payload)}</pre>
    </section>
  );
}

function TraceEvidencePanel(props: {
  trace: TraceEnvelope;
  scores: ScoreResult[];
  behaviorMatches: BehaviorMatch[];
  datasetMemberships: DatasetMembership[];
  similarResult: SimilarTraceSearchResult | null;
  assertionResult: TraceAssertionResult | null;
}) {
  const { trace, scores, behaviorMatches, datasetMemberships, similarResult, assertionResult } = props;
  return (
    <div className="traceEvidencePanel">
      <section>
        <h4>Scores</h4>
        <div className="evidenceRows">
          {scores.map((score) => (
            <div key={score.score_id}>
              <strong>{formatScore(asRecord(score))}</strong>
              <span>{score.status} · {score.judge_id} · evidence {score.evidence_span_ids.join(", ") || "none"}</span>
            </div>
          ))}
          {!scores.length ? <p className="systemNote">No scores persisted for {trace.trace_id}</p> : null}
        </div>
      </section>
      <section>
        <h4>Behavior matches</h4>
        <div className="evidenceRows">
          {behaviorMatches.map((match) => (
            <div key={match.behavior_match_id}>
              <strong>{match.behavior_id}</strong>
              <span>{match.status} · evidence {match.evidence_span_ids.join(", ") || "none"}</span>
            </div>
          ))}
          {!behaviorMatches.length ? <p className="systemNote">No behavior matches persisted</p> : null}
        </div>
      </section>
      <section>
        <h4>Dataset membership</h4>
        <div className="evidenceRows">
          {datasetMemberships.map((membership) => (
            <div key={membership.dataset_example_id}>
              <strong>{membership.dataset_name}</strong>
              <span>{membership.labels.join(", ") || "unlabeled"} · {membership.dataset_example_id}</span>
            </div>
          ))}
          {!datasetMemberships.length ? <p className="systemNote">No dataset examples linked yet</p> : null}
        </div>
      </section>
      <section>
        <h4>Similar traces</h4>
        <div className="evidenceRows">
          {similarResult?.disabled ? <p className="systemNote">{similarResult.reason ?? "similarity disabled"}</p> : null}
          {similarResult && !similarResult.disabled ? (
            <p className="systemNote">{similarResult.representation_version ?? "unknown representation"}</p>
          ) : null}
          {similarResult?.data.map((match) => (
            <div key={match.trace_id}>
              <strong>{match.trace_id}</strong>
              <span>{formatRate(match.similarity_score)} similar · evidence {match.evidence_span_ids.join(", ") || "none"}</span>
              <small>{match.rationale}</small>
            </div>
          ))}
          {similarResult && !similarResult.disabled && !similarResult.data.length ? (
            <p className="systemNote">No similar traces returned</p>
          ) : null}
          {!similarResult ? <p className="systemNote">Similarity not run for {trace.trace_id}</p> : null}
        </div>
      </section>
      <section>
        <h4>Deterministic check</h4>
        <div className="evidenceRows">
          {assertionResult ? (
            <div>
              <strong>{assertionResult.status}</strong>
              <span>{assertionResult.failures.length} failures</span>
              <pre>{JSON.stringify(assertionResult, null, 2)}</pre>
            </div>
          ) : (
            <p className="systemNote">No assertion check run</p>
          )}
        </div>
      </section>
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
    automations: { label: "Automations", value: "ready", detail: "Targets, definitions, runs, cooldowns, and retries are API-backed" },
    datasets: { label: "Evals", value: "ready", detail: "Eval runs can link prompt and runtime config versions" },
    prompts: { label: "Prompts", value: "ready", detail: "Versions, tags, render, and diff are API-backed" },
    configs: { label: "Configs", value: "ready", detail: "Runtime config versions and comparisons are API-backed" },
    mcp: { label: "MCP", value: "53 tools", detail: "Tools and JSON resources are routed" },
    ops: { label: "Ops", value: "ready", detail: "Health, export, retention, and tombstones are wired" }
  };
  return summaries[view];
}

function scaffoldRows(view: ViewKey) {
  const shared = {
    judges: [
      { icon: <Braces />, title: "Judge registry", status: "drafts and immutable versions available", phase: "Phase 4" },
      { icon: <Shield />, title: "Rubric judge provider", status: "local model-backed and review-gated", phase: "Phase 4" },
      { icon: <KeyRound />, title: "Code judge sandbox", status: "policy-guarded dev isolation", phase: "Phase 4" }
    ],
    behaviors: [
      { icon: <GitBranch />, title: "Manual labels", status: "schema and API surface available", phase: "Phase 6" },
      { icon: <Braces />, title: "Rule detectors", status: "condition grammar available", phase: "Phase 6" },
      { icon: <Network />, title: "Cluster discovery", status: "embedding grouping and review examples ready", phase: "Phase 6" }
    ],
    automations: [
      { icon: <Play />, title: "Definitions", status: "trigger, condition, action, and cooldown records available", phase: "Phase 6" },
      { icon: <KeyRound />, title: "Notification targets", status: "secret-ref based targets available", phase: "Phase 6" },
      { icon: <TimerReset />, title: "Runs", status: "idempotency, cooldown, retry, and dead-letter checks available", phase: "Phase 6" }
    ],
    datasets: [
      { icon: <Database />, title: "Dataset provenance", status: "schema and storage tables available", phase: "Phase 5" },
      { icon: <Play />, title: "Eval runner", status: "judge, prompt, and config selection available", phase: "Phase 5" },
      { icon: <CheckCircle2 />, title: "Baseline comparison", status: "quality and provenance deltas available", phase: "Phase 5" }
    ],
    prompts: [
      { icon: <Split />, title: "Prompt commit IDs", status: "available", phase: "Phase 7" },
      { icon: <FileSearch />, title: "Prompt diff", status: "available", phase: "Phase 7" },
      { icon: <Shield />, title: "Secret interpolation", status: "explicit audited refs", phase: "Phase 7" }
    ],
    configs: [
      { icon: <KeyRound />, title: "Config versions", status: "immutable commits available", phase: "Phase 7" },
      { icon: <FileSearch />, title: "Config compare", status: "content diffs available", phase: "Phase 7" },
      { icon: <Network />, title: "Runtime bundles", status: "model/tool/retrieval payloads supported", phase: "Phase 7" }
    ],
    mcp: [
      { icon: <Network />, title: "Tool contracts", status: "all required names registered", phase: "Phase 7" },
      { icon: <FileSearch />, title: "API-backed handlers", status: "judges, evals, docs, prompts, configs, automations routed", phase: "Phase 7" },
      { icon: <Shield />, title: "Write confirmations", status: "confirmed flag and audit metadata enforced", phase: "Phase 7" }
    ],
    ops: [
      { icon: <Activity />, title: "Health and readiness", status: "available", phase: "Phase 8" },
      { icon: <Shield />, title: "API key scopes and audit", status: "local scopes and audit available", phase: "Phase 8" },
      { icon: <Database />, title: "Retention/export/delete", status: "policy, manifest, and tombstone paths available", phase: "Phase 8" }
    ],
    traces: [],
    issues: [
      { icon: <AlertTriangle />, title: "Issue intake", status: "API and storage available", phase: "Spec v2" },
      { icon: <FileSearch />, title: "Deterministic investigation", status: "structured search and impact reporting available", phase: "Spec v2" },
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

type TraceBadge = {
  key: string;
  label: string;
  tone: "behavior" | "score" | "attribute";
};

type DatasetMembership = {
  dataset_id: string;
  dataset_name: string;
  dataset_example_id: string;
  labels: string[];
};

function TraceBadges({ badges }: { badges: TraceBadge[] }) {
  if (!badges.length) return <span className="traceBadge muted">none</span>;
  const visible = badges.slice(0, 5);
  const hiddenCount = badges.length - visible.length;
  return (
    <div className="traceBadges">
      {visible.map((badge) => (
        <span className={`traceBadge ${badge.tone}`} key={badge.key}>
          {badge.label}
        </span>
      ))}
      {hiddenCount > 0 ? <span className="traceBadge muted">+{hiddenCount}</span> : null}
    </div>
  );
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

function buildSpanTree(spans: SpanEnvelope[]): SpanNode[] {
  const nodes = new Map<string, SpanNode>();
  for (const span of spans) {
    nodes.set(span.span_id, {
      span,
      children: [],
      payload_state: {
        input: span.input?.redaction_state ?? span.input?.mode ?? "unknown",
        output: span.output?.redaction_state ?? span.output?.mode ?? "unknown"
      }
    });
  }
  const roots: SpanNode[] = [];
  for (const node of nodes.values()) {
    const parent = node.span.parent_span_id ? nodes.get(node.span.parent_span_id) : null;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  return roots;
}

function conversationRows(detail: TraceDetail) {
  return detail.spans.flatMap((span) => {
    const rows: Array<{
      role: "user" | "assistant" | "tool" | "system";
      title: string;
      text: string;
      redactionState: string;
      spanType: string;
      spanId: string;
    }> = [];
    if (span.input) {
      rows.push({
        role: span.span_type === "tool" ? "tool" : "user",
        title: span.span_type === "tool" ? `${span.name} call` : `${span.name} input`,
        text: payloadText(span.input),
        redactionState: span.input.redaction_state ?? span.input.mode,
        spanType: span.span_type,
        spanId: span.span_id
      });
    }
    if (span.output) {
      rows.push({
        role: span.span_type === "tool" ? "tool" : "assistant",
        title: span.span_type === "tool" ? `${span.name} output` : `${span.name} output`,
        text: payloadText(span.output),
        redactionState: span.output.redaction_state ?? span.output.mode,
        spanType: span.span_type,
        spanId: span.span_id
      });
    }
    return rows;
  });
}

function payloadText(payload: SpanEnvelope["input"]) {
  if (!payload) return "none";
  if (payload.value == null) return `${payload.mode}${payload.payload_id ? ` · ${payload.payload_id}` : ""}`;
  return typeof payload.value === "string" ? payload.value : JSON.stringify(payload.value);
}

function hasCodeOrErrorContext(span: SpanEnvelope) {
  if (span.status === "error") return true;
  if (span.events.some((event) => event.name.toLowerCase().includes("error"))) return true;
  return Object.keys(span.attributes).some(
    (key) =>
      key.startsWith("error.") ||
      key.startsWith("exception.") ||
      key.startsWith("code.") ||
      key.startsWith("deployment.") ||
      key.startsWith("stack.") ||
      key === "function.name" ||
      key === "tool.name"
  );
}

function codeErrorAttributes(span: SpanEnvelope) {
  const attributes = Object.fromEntries(
    Object.entries(span.attributes).filter(([key]) =>
      key.startsWith("error.") ||
      key.startsWith("exception.") ||
      key.startsWith("code.") ||
      key.startsWith("deployment.") ||
      key.startsWith("stack.") ||
      key === "function.name" ||
      key === "tool.name"
    )
  );
  return {
    attributes,
    events: span.events.filter((event) => event.name.toLowerCase().includes("error")),
    input_redaction: span.input?.redaction_state ?? span.input?.mode ?? null,
    output_redaction: span.output?.redaction_state ?? span.output?.mode ?? null
  };
}

function behaviorReviewLabel(task: ReviewTask) {
  if (task.status === "rejected") return "false_positive";
  if (task.status === "accepted") return "accepted_positive";
  return task.status;
}

function automationDraftConditions(field: string, op: string, value: string) {
  if (!field.trim()) return { combine: "all", items: [] };
  const item: Record<string, unknown> = { field: field.trim(), op };
  if (op !== "exists") item.value = value.trim();
  return { combine: "all", items: [item] };
}

function automationDraftActions(
  actionType: string,
  targetId: string | undefined,
  message: string,
  retryAttempts: number,
  onFailure: string
) {
  const attempts = Number.isFinite(retryAttempts) && retryAttempts > 1 ? retryAttempts : null;
  const failureBehavior = onFailure === "stop" ? null : onFailure;
  const withPolicy = (action: Record<string, unknown>) => ({
    ...action,
    ...(attempts ? { retry: { attempts } } : {}),
    ...(failureBehavior ? { on_failure: failureBehavior } : {})
  });
  const reviewAction = withPolicy({ type: "create_review_task", task_type: "behavior_candidate" });
  const notificationAction = withPolicy({
    type: "send_notification",
    target_id: targetId,
    message
  });
  if (actionType === "send_notification") return [notificationAction];
  if (actionType === "review_and_notification") return [reviewAction, notificationAction];
  return [reviewAction];
}

function automationDeadLetteredActions(runHistory: AutomationRun[], runResult: AutomationRun | null) {
  const runs = [
    ...(runResult ? [runResult] : []),
    ...runHistory.filter((run) => run.automation_run_id !== runResult?.automation_run_id)
  ];
  return runs.flatMap((run) =>
    run.action_results
      .map((action, index) => ({ runId: run.automation_run_id, index, action }))
      .filter((item) => item.action.status === "dead_lettered" || item.action.dead_lettered === true)
  );
}

function automationActionType(action: Record<string, unknown>) {
  return String(action.type ?? asRecord(action.action).type ?? "action");
}

function automationActionReason(action: Record<string, unknown>) {
  return String(action.reason ?? action.original_status ?? action.status ?? "dead_lettered");
}

function automationReferencesBehavior(automation: AutomationDefinition, behavior: BehaviorDefinition) {
  const haystack = JSON.stringify({
    trigger: automation.trigger,
    conditions: automation.conditions,
    actions: automation.actions
  }).toLowerCase();
  return [behavior.behavior_id, behavior.name]
    .filter((value) => value.trim().length > 0)
    .some((value) => haystack.includes(value.toLowerCase()));
}

function groupByTraceId<T extends { trace_id: string }>(items: T[]) {
  return items.reduce<Record<string, T[]>>((grouped, item) => {
    grouped[item.trace_id] = [...(grouped[item.trace_id] ?? []), item];
    return grouped;
  }, {});
}

function groupDatasetMembership(items: Array<{ dataset: DatasetDefinition; examples: DatasetExample[] }>) {
  return items.reduce<Record<string, DatasetMembership[]>>((grouped, item) => {
    for (const example of item.examples) {
      grouped[example.source_trace_id] = [
        ...(grouped[example.source_trace_id] ?? []),
        {
          dataset_id: item.dataset.dataset_id,
          dataset_name: item.dataset.name,
          dataset_example_id: example.dataset_example_id,
          labels: example.labels
        }
      ];
    }
    return grouped;
  }, {});
}

function runnableJudgePayload(judge: JudgeDefinition): Record<string, unknown> | null {
  const version = latestJudgeVersion(judge);
  const definition = version?.definition ?? {};
  const judgeType = String(definition.judge_type ?? judge.judge_type);
  if (judgeType !== "rubric_judge") return null;
  if (!definition.rubric) return null;
  return {
    ...definition,
    judge_id: judge.judge_id,
    judge_version_id: version?.judge_version_id ?? null,
    judge_type: judgeType,
    name: judge.name,
    description: judge.description
  };
}

function rubricOutputSchemaPreview() {
  return {
    required: ["verdict", "score", "confidence", "reasoning", "evidence_span_ids"],
    verdict: ["pass", "fail", "unsure"],
    score: "number 0..1",
    confidence: "number 0..1",
    reasoning: "string",
    evidence_span_ids: "captured span ids",
    failure_mode: "string or null"
  };
}

function latestJudgeVersion(judge: JudgeDefinition) {
  return [...(judge.versions ?? [])].sort((left, right) => right.version - left.version)[0] ?? null;
}

function traceLatency(trace: TraceEnvelope) {
  const explicitMs = firstNumber(trace.attributes, ["duration_ms", "latency_ms", "trace.duration_ms", "trace.latency_ms"]);
  if (explicitMs != null) return formatDuration(explicitMs);
  if (!trace.ended_at) return "running";
  const started = Date.parse(trace.started_at);
  const ended = Date.parse(trace.ended_at);
  if (Number.isNaN(started) || Number.isNaN(ended) || ended < started) return "unknown";
  return formatDuration(ended - started);
}

function spanLatency(span: SpanEnvelope) {
  const explicitMs = firstNumber(span.attributes, ["duration_ms", "latency_ms", "span.duration_ms", "span.latency_ms"]);
  if (explicitMs != null) return formatDuration(explicitMs);
  if (!span.ended_at) return "running";
  const started = Date.parse(span.started_at);
  const ended = Date.parse(span.ended_at);
  if (Number.isNaN(started) || Number.isNaN(ended) || ended < started) return "unknown";
  return formatDuration(ended - started);
}

function traceTokenSummary(trace: TraceEnvelope, scores: ScoreResult[]) {
  const traceTokens = firstNumber(trace.attributes, [
    "usage.total_tokens",
    "total_tokens",
    "tokens.total",
    "tokens.total_tokens",
    "llm.total_tokens",
    "model.usage.total_tokens",
    "openai.usage.total_tokens"
  ]);
  if (traceTokens != null) return formatCompactNumber(traceTokens);
  const scoreTokens = scores
    .map((score) => firstNumber(score.cost ?? {}, ["usage.total_tokens", "total_tokens", "tokens.total", "tokens.total_tokens"]))
    .filter((value): value is number => value != null);
  if (!scoreTokens.length) return "none";
  return formatCompactNumber(scoreTokens.reduce((sum, value) => sum + value, 0));
}

function traceCostSummary(trace: TraceEnvelope, scores: ScoreResult[]) {
  const traceCost = firstNumber(trace.attributes, [
    "cost.estimated_usd",
    "cost.total_usd",
    "cost.usd",
    "usage.cost_usd",
    "cost_usd",
    "openabm.cost_usd"
  ]);
  if (traceCost != null) return formatUsd(traceCost);
  const scoreCosts = scores
    .map((score) => firstNumber(score.cost ?? {}, ["cost.estimated_usd", "cost.total_usd", "cost.usd", "usage.cost_usd", "cost_usd"]))
    .filter((value): value is number => value != null);
  if (!scoreCosts.length) return "none";
  return formatUsd(scoreCosts.reduce((sum, value) => sum + value, 0));
}

function traceBadges(trace: TraceEnvelope, scores: ScoreResult[], behaviorMatches: BehaviorMatch[]): TraceBadge[] {
  const badges: TraceBadge[] = [];
  const behaviorIds = new Set<string>([
    ...explicitStringList(trace.attributes, ["openabm.behavior_ids", "behavior_ids", "behavior.id", "behavior_id"]),
    ...behaviorMatches.map((match) => match.behavior_id)
  ]);
  for (const behaviorId of behaviorIds) {
    badges.push({
      key: `behavior-${behaviorId}`,
      label: `behavior ${shortIdentifier(behaviorId)}`,
      tone: "behavior"
    });
  }

  const scoreVerdicts = countLabels([
    ...explicitStringList(trace.attributes, ["openabm.score_verdicts", "score.verdict", "score_verdict"]),
    ...scores.map(scoreBadgeLabel)
  ]);
  for (const [verdict, count] of Object.entries(scoreVerdicts)) {
    badges.push({
      key: `score-${verdict}`,
      label: `score ${shortIdentifier(verdict)}${count > 1 ? ` x${count}` : ""}`,
      tone: "score"
    });
  }

  return badges;
}

function scoreBadgeLabel(score: ScoreResult) {
  const value = asRecord(score.value);
  return String(value.verdict ?? score.status ?? "score");
}

function explicitStringList(record: Record<string, unknown>, keys: string[]) {
  return keys.flatMap((key) => stringsFromUnknown(attributeValue(record, key)));
}

function stringsFromUnknown(value: unknown): string[] {
  if (Array.isArray(value)) return value.flatMap(stringsFromUnknown);
  if (typeof value === "string" && value.trim()) return [value.trim()];
  if (typeof value === "number" || typeof value === "boolean") return [String(value)];
  return [];
}

function countLabels(values: string[]) {
  return values.reduce<Record<string, number>>((counts, value) => {
    const label = value.trim();
    if (label) counts[label] = (counts[label] ?? 0) + 1;
    return counts;
  }, {});
}

function firstNumber(record: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = numberFromUnknown(attributeValue(record, key));
    if (value != null) return value;
  }
  return null;
}

function attributeValue(record: Record<string, unknown>, path: string): unknown {
  if (Object.prototype.hasOwnProperty.call(record, path)) return record[path];
  return path.split(".").reduce<unknown>((current, part) => {
    const currentRecord = asRecord(current);
    return Object.prototype.hasOwnProperty.call(currentRecord, part) ? currentRecord[part] : undefined;
  }, record);
}

function numberFromUnknown(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function formatDuration(ms: number) {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) {
    const seconds = ms / 1000;
    return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} s`;
  }
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

function formatCompactNumber(value: number) {
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function formatUsd(value: number) {
  if (value === 0) return "$0";
  return `$${value < 0.01 ? value.toFixed(4) : value.toFixed(2)}`;
}

function shortIdentifier(value: string) {
  return value.length > 24 ? `${value.slice(0, 14)}...${value.slice(-5)}` : value;
}

function formatCounts(counts: Record<string, unknown>) {
  const entries = Object.entries(counts).filter(([, value]) => Number(value) !== 0);
  return entries.map(([key, value]) => `${key}: ${String(value)}`).join(", ") || "none";
}

function formatStringList(values: string[]) {
  return values.length ? values.map(shortIdentifier).join(", ") : "none";
}

function formatLinkedEvalSummary(summary: Record<string, unknown>) {
  const runCount = summary.run_count ?? 0;
  const passRate = numberFromUnknown(summary.avg_pass_rate);
  const invalid = summary.invalid_output_count ?? 0;
  const ids = stringsFromUnknown(summary.eval_run_ids).map(shortIdentifier);
  const parts = [
    `${String(runCount)} runs`,
    passRate == null ? null : `${Math.round(passRate * 1000) / 10}% pass`,
    `${String(invalid)} invalid`,
    ids.length ? ids.join(", ") : null
  ].filter(Boolean);
  return parts.join(" · ");
}

function formatRootCauseEvidence(cause: Record<string, unknown>) {
  const evidence = asRecord(cause.evidence_summary);
  const failingMetric = asRecord(cause.failing_cohort_metric);
  const baselineMetric = asRecord(cause.baseline_cohort_metric);
  const lift = asRecord(cause.lift_or_delta);
  const parts = [
    formatImpactEvidenceSummary(evidence),
    Object.keys(failingMetric).length
      ? `failing ${String(failingMetric.count ?? 0)} / ${formatRate(numberFromUnknown(failingMetric.rate))}`
      : null,
    Object.keys(baselineMetric).length
      ? `baseline ${String(baselineMetric.count ?? 0)} / ${formatRate(numberFromUnknown(baselineMetric.rate))}`
      : null,
    Object.keys(lift).length
      ? `delta ${formatSignedPercent(numberFromUnknown(lift.rate_delta))}${lift.lift == null ? "" : ` · lift ${String(lift.lift)}x`}`
      : null
  ].filter(Boolean);
  return parts.join(" · ") || "no evidence summary";
}

function formatImpactEvidenceSummary(evidence: Record<string, unknown>) {
  if (!Object.keys(evidence).length) return "no evidence summary";
  if (evidence.behavior_distribution) {
    const behaviorCount = Object.keys(asRecord(evidence.behavior_distribution)).length;
    return `${behaviorCount} behavior labels`;
  }
  if (evidence.runtime_provenance_distribution) {
    return `runtime ${formatNestedCounts(asRecord(evidence.runtime_provenance_distribution))}`;
  }
  return Object.entries(evidence)
    .slice(0, 5)
    .map(([key, value]) => {
      const record = asRecord(value);
      if (Object.keys(record).length) return `${key}: ${formatNestedCounts(record)}`;
      const values = stringsFromUnknown(value);
      return `${key}: ${values.length ? values.join(", ") : String(value)}`;
    })
    .join("; ");
}

function formatNestedCounts(counts: Record<string, unknown>) {
  const entries = Object.entries(counts);
  if (!entries.length) return "none";
  return entries
    .map(([key, value]) => {
      const nested = asRecord(value);
      return Object.keys(nested).length ? `${key}: ${formatCounts(nested)}` : `${key}: ${String(value)}`;
    })
    .join("; ");
}

function downloadJsonFile(filename: string, value: unknown) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function downloadTextFile(filename: string, value: string, type: string) {
  const blob = new Blob([value], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
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

function recordsFrom(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.map((item) => asRecord(item)).filter((item) => Object.keys(item).length > 0)
    : [];
}

function investigationImpact(run: InvestigationRun | null): ImpactReport | null {
  if (!run?.result?.impact_report) return null;
  return run.result.impact_report;
}

function formatEvalSummary(summary: Record<string, unknown>) {
  const total = summary.total_examples ?? summary.count ?? summary.example_count;
  const passRate = summary.pass_rate;
  const invalid = summary.invalid_output_count ?? summary.invalid_judge_outputs;
  const verdictCounts = formatCounts(asRecord(summary.score_verdict_counts));
  const resultCounts = formatCounts(asRecord(summary.result_status_counts));
  const parts = [
    total == null ? null : `${String(total)} examples`,
    typeof passRate === "number" ? `${Math.round(passRate * 1000) / 10}% pass` : null,
    verdictCounts === "none" ? null : verdictCounts,
    resultCounts === "none" ? null : resultCounts,
    invalid == null ? null : `${String(invalid)} invalid`
  ].filter(Boolean);
  return parts.join(" · ") || "summary pending";
}

function formatEvalRuntimeContext(context: Record<string, unknown>) {
  const deployment = context.deployment_context_id
    ? `deploy ${String(context.deployment_context_id)}`
    : null;
  const toolVersions = Array.isArray(context.tool_version_ids)
    ? `tools ${context.tool_version_ids.map((value) => String(value)).join(", ")}`
    : null;
  return [deployment, toolVersions].filter(Boolean).join(" · ") || "none";
}

function formatEvalAnalyticsGroup(group: EvalAnalytics["by_prompt_version"][number] | undefined) {
  if (!group) return "No historical runs";
  const passRate =
    typeof group.avg_pass_rate === "number"
      ? `${Math.round(group.avg_pass_rate * 1000) / 10}% pass`
      : "pass pending";
  const invalidRate =
    typeof group.invalid_output_rate === "number"
      ? `${Math.round(group.invalid_output_rate * 1000) / 10}% invalid`
      : "invalid pending";
  return `${shortIdentifier(group.key)} · ${group.run_count} runs · ${passRate} · ${invalidRate}`;
}

function formatEvalProvenanceComparison(value: Record<string, unknown>) {
  const changed = Array.isArray(value.changed_fields)
    ? value.changed_fields.map((field) => String(field))
    : [];
  const contextKeys = Array.isArray(value.changed_runtime_context_keys)
    ? value.changed_runtime_context_keys.map((key) => String(key))
    : [];
  const parts = [
    changed.length ? `changed ${changed.join(", ")}` : "no provenance changes",
    contextKeys.length ? `context ${contextKeys.join(", ")}` : null
  ].filter(Boolean);
  return `Provenance: ${parts.join(" · ")}`;
}

function formatScore(score: Record<string, unknown>) {
  const nestedValue = asRecord(score.value);
  const verdict = nestedValue.verdict ?? score.verdict ?? score.status ?? "score";
  const value = nestedValue.score ?? score.score;
  const failureMode = score.failure_mode ? ` · ${String(score.failure_mode)}` : "";
  return value == null
    ? `${String(verdict)}${failureMode}`
    : `${String(verdict)} ${String(value)}${failureMode}`;
}

function formatEvalResult(result: EvalResult | null) {
  if (!result) return "missing";
  return `${result.status} · ${result.scores.map(formatScore).join(", ") || "no scores"}`;
}

function formatSignedPercent(value: number | null | undefined) {
  if (value == null) return "none";
  const rounded = Math.round(value * 1000) / 10;
  return `${rounded > 0 ? "+" : ""}${rounded}%`;
}

function formatPercent(value: number | null | undefined) {
  if (value == null) return "none";
  return `${Math.round(value * 1000) / 10}%`;
}

function formatSignedNumber(value: number | null | undefined) {
  if (value == null) return "none";
  const rounded = Math.round(value * 1000) / 1000;
  return `${rounded > 0 ? "+" : ""}${rounded}`;
}

function formatNullableNumber(value: number | null | undefined) {
  if (value == null) return "none";
  return String(Math.round(value * 1000) / 1000);
}

function formatEvalHistoryRuntime(run: EvalComparison["historical_runs"][number]) {
  const parts = [
    run.prompt_version_id ? `prompt ${shortIdentifier(run.prompt_version_id)}` : null,
    run.agent_config_version_id ? `config ${shortIdentifier(run.agent_config_version_id)}` : null,
    run.deployment_context_id ? `deploy ${shortIdentifier(run.deployment_context_id)}` : null,
    run.completed_at ? `completed ${formatTime(run.completed_at)}` : `created ${formatTime(run.created_at)}`
  ].filter(Boolean);
  return parts.join(" · ");
}

function formatEvalTrendRuntime(run: EvalAnalytics["trend"][number]) {
  const parts = [
    `#${run.sequence_index}`,
    run.total_examples ? `${run.total_examples} examples` : "no examples",
    run.prompt_version_id ? `prompt ${shortIdentifier(run.prompt_version_id)}` : null,
    run.agent_config_version_id ? `config ${shortIdentifier(run.agent_config_version_id)}` : null,
    run.deployment_context_id ? `deploy ${shortIdentifier(run.deployment_context_id)}` : null,
    run.completed_at ? `completed ${formatTime(run.completed_at)}` : `created ${formatTime(run.created_at)}`
  ].filter(Boolean);
  return parts.join(" · ");
}

function formatSignedInteger(value: number | null | undefined) {
  if (value == null) return "none";
  return `${value > 0 ? "+" : ""}${value}`;
}

function formatIntegerDelta(value: number | null | undefined) {
  return formatSignedInteger(value);
}

function formatCurrencyDelta(value: number | null | undefined) {
  if (value == null) return "none";
  if (value === 0) return "$0";
  return `${value > 0 ? "+" : "-"}${formatUsd(Math.abs(value))}`;
}

function formatDurationDelta(value: number | null | undefined) {
  if (value == null) return "none";
  if (value === 0) return "0 ms";
  return `${value > 0 ? "+" : "-"}${formatDuration(Math.abs(value))}`;
}

function parseJsonObject(value: string): Record<string, unknown> {
  const parsed = JSON.parse(value) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Expected a JSON object");
  }
  return parsed as Record<string, unknown>;
}

function findPromptVersion(
  prompts: PromptDefinition[],
  promptVersionId: string | null
): { prompt: PromptDefinition; version: PromptVersion } | null {
  if (!promptVersionId) return null;
  for (const prompt of prompts) {
    for (const version of prompt.versions ?? []) {
      if (version.prompt_version_id === promptVersionId) return { prompt, version };
    }
  }
  return null;
}

function findAgentConfigVersion(
  configs: AgentConfigDefinition[],
  agentConfigVersionId: string | null
): { config: AgentConfigDefinition; version: AgentConfigVersion } | null {
  if (!agentConfigVersionId) return null;
  for (const config of configs) {
    for (const version of config.versions ?? []) {
      if (version.agent_config_version_id === agentConfigVersionId) {
        return { config, version };
      }
    }
  }
  return null;
}

function formatPromptVersionLink(
  match: { prompt: PromptDefinition; version: PromptVersion } | null,
  promptVersionId: string | null
) {
  if (!promptVersionId) return "none";
  if (!match) return promptVersionId;
  const tags = formatStringList(match.version.active_tags ?? []);
  return `${match.prompt.name} · ${shortIdentifier(match.version.commit_id)} · tags ${tags}`;
}

function formatAgentConfigVersionLink(
  match: { config: AgentConfigDefinition; version: AgentConfigVersion } | null,
  agentConfigVersionId: string | null
) {
  if (!agentConfigVersionId) return "none";
  if (!match) return agentConfigVersionId;
  const tags = formatStringList(match.version.active_tags ?? []);
  return `${match.config.name} · v${match.version.version} · ${shortIdentifier(match.version.commit_id)} · tags ${tags}`;
}

function formatTags(tags: Record<string, string>) {
  const entries = Object.entries(tags);
  return entries.map(([key, value]) => `${key}: ${value}`).join(", ") || "none";
}

function formatConfigContent(content: Record<string, unknown>) {
  const model = content.model ? `model ${String(content.model)}` : null;
  const tools = Array.isArray(content.tools) ? `${content.tools.length} tools` : null;
  const workflow = content.workflow ? `workflow ${String(content.workflow)}` : null;
  return [model, tools, workflow].filter(Boolean).join(" · ") || JSON.stringify(content);
}

function countMetricLines(metricsText: string) {
  return metricsText
    .split("\n")
    .filter((line) => line.trim() && !line.startsWith("#")).length;
}

function formatRetentionRules(rules: Array<Record<string, unknown>>) {
  return rules
    .map((rule) => {
      const entity = rule.entity ? String(rule.entity) : "entity";
      const ttl = rule.ttl_days == null ? "no ttl" : `${String(rule.ttl_days)}d`;
      return `${entity} ${ttl}`;
    })
    .join(", ") || "no rules";
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
    automations: "Automations",
    datasets: "Datasets and evals",
    prompts: "Prompt registry",
    configs: "Agent configs",
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
