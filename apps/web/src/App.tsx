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
  AgentConfigCompareResult,
  AgentConfigDefinition,
  BehaviorBacktestResult,
  BehaviorDefinition,
  ChatOpsInvestigationResult,
  ClassificationResult,
  DataClassificationPolicy,
  DatasetDefinition,
  DatasetExample,
  EvalComparison,
  EvalResult,
  EvalRun,
  HealthStatus,
  ImpactReport,
  InvestigationRun,
  IssueDefinition,
  JudgeCalibrationReport,
  JudgeDefinition,
  JudgePromotionResult,
  Project,
  ProjectExportBundle,
  PromptDefinition,
  PromptDiffResult,
  RetentionApplyResult,
  RetentionPolicy,
  ReviewTask,
  ScreenshotIssueResult,
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
  | "configs"
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
            onQueryChange={setQuery}
            onStatusChange={setStatus}
            onSearch={() => void refreshTraces()}
            onSelectTrace={setSelectedTraceId}
            onCheckSimilarity={() => void checkSimilarity()}
          />
        ) : activeView === "issues" ? (
          <IssueInvestigationWorkspace client={client} connection={connection} projectId={projectId} traces={traces} />
        ) : activeView === "reviews" ? (
          <ReviewQueue client={client} connection={connection} projectId={projectId} />
        ) : activeView === "judges" ? (
          <JudgeWorkspace client={client} connection={connection} projectId={projectId} />
        ) : activeView === "datasets" ? (
          <DatasetEvalWorkspace client={client} connection={connection} projectId={projectId} />
        ) : activeView === "behaviors" ? (
          <BehaviorWorkspace client={client} connection={connection} projectId={projectId} />
        ) : activeView === "prompts" ? (
          <PromptRegistryWorkspace client={client} connection={connection} projectId={projectId} />
        ) : activeView === "configs" ? (
          <AgentConfigWorkspace client={client} connection={connection} projectId={projectId} />
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
}) {
  const { client, connection, projectId } = props;
  const [configs, setConfigs] = useState<AgentConfigDefinition[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [name, setName] = useState("Refund runtime");
  const [configType, setConfigType] = useState("runtime");
  const [contentText, setContentText] = useState(
    JSON.stringify({ model: "qwen3.5-9b-mlx", tools: ["trace_search"], context_window: 262144 }, null, 2)
  );
  const [metadataText, setMetadataText] = useState(JSON.stringify({ source: "web-ui" }, null, 2));
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
      const version = await client.commitAgentConfigVersion(projectId, selectedConfig.agent_config_id, content, metadata);
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
                <button className="primaryButton" onClick={() => void commitConfigVersion()}>
                  <GitBranch size={15} />
                  Commit
                </button>
              </section>

              <section className="configSection">
                <h4>Versions</h4>
                <div className="versionRows">
                  {versions.map((version) => (
                    <button
                      key={version.agent_config_version_id}
                      onClick={() => {
                        setContentText(JSON.stringify(version.content, null, 2));
                        setMetadataText(JSON.stringify(version.metadata, null, 2));
                        setNewCommitId(version.commit_id);
                      }}
                    >
                      <strong>v{version.version} · {version.commit_id}</strong>
                      <span>{formatConfigContent(version.content)}</span>
                      <small>{formatTime(version.created_at)}</small>
                    </button>
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

  async function loadOps() {
    if (connection !== "live") {
      setHealth(null);
      setReady(null);
      setMetricsText("");
      setRetentionPolicies([]);
      setClassificationPolicies([]);
      setStateText("fixture mode");
      return;
    }
    try {
      const [healthStatus, readyStatus, metrics, retention, classifications] = await Promise.all([
        client.getHealth(),
        client.getReady(),
        client.getMetricsText(),
        client.listRetentionPolicies(projectId),
        client.listDataClassificationPolicies(projectId)
      ]);
      setHealth(healthStatus);
      setReady(readyStatus);
      setMetricsText(metrics || "No counters emitted yet");
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
            </dl>
          </section>

          <section className="opsSection">
            <h4>Metrics</h4>
            <pre>{metricsText || "No metrics loaded"}</pre>
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
}) {
  const { client, connection, projectId, traces } = props;
  const [issues, setIssues] = useState<IssueDefinition[]>([]);
  const [investigations, setInvestigations] = useState<InvestigationRun[]>([]);
  const [impactReports, setImpactReports] = useState<ImpactReport[]>([]);
  const [selectedIssueId, setSelectedIssueId] = useState("");
  const [selectedInvestigationId, setSelectedInvestigationId] = useState("");
  const [issueTitle, setIssueTitle] = useState("Refund workflow uses the wrong tool");
  const [issueDescription, setIssueDescription] = useState("Customer refund path appears to route through order lookup.");
  const [seedTraceId, setSeedTraceId] = useState("");
  const [screenshotTitle, setScreenshotTitle] = useState("Screenshot shows refund failure");
  const [screenshotPayloadId, setScreenshotPayloadId] = useState("payload_screenshot_1");
  const [screenshotText, setScreenshotText] = useState("damaged order refund");
  const [screenshotResult, setScreenshotResult] = useState<ScreenshotIssueResult | null>(null);
  const [chatMessage, setChatMessage] = useState("Investigate damaged order refund failures");
  const [chatopsResult, setChatopsResult] = useState<ChatOpsInvestigationResult | null>(null);
  const [investigationProblem, setInvestigationProblem] = useState("refund failure");
  const [filterStatus, setFilterStatus] = useState("error");
  const [stateText, setStateText] = useState("Issues need a live API");

  const selectedIssue = issues.find((issue) => issue.issue_id === selectedIssueId) ?? issues[0] ?? null;
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

  async function loadIssues() {
    if (connection !== "live") {
      setIssues([]);
      setInvestigations([]);
      setImpactReports([]);
      setStateText("fixture mode");
      return;
    }
    try {
      const [loadedIssues, loadedInvestigations, loadedReports] = await Promise.all([
        client.listIssues(projectId),
        client.listInvestigations(projectId),
        client.listImpactReports(projectId)
      ]);
      setIssues(loadedIssues);
      setInvestigations(loadedInvestigations);
      setImpactReports(loadedReports);
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
      setStateText(`${loadedIssues.length} issues · ${loadedInvestigations.length} investigations`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "issue refresh failed");
    }
  }

  useEffect(() => {
    void loadIssues();
  }, [client, connection, projectId]);

  async function createManualIssue() {
    if (connection !== "live" || !issueTitle.trim()) return;
    try {
      const created = await client.createIssue(projectId, {
        title: issueTitle.trim(),
        description: issueDescription.trim(),
        seedTraceId: seedTraceId || undefined
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
        extractedText: screenshotText.trim()
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
      const result = await client.chatopsInvestigate(projectId, chatMessage.trim(), seedTraceId || undefined);
      setChatopsResult(result);
      setIssues((current) => [result.issue, ...current.filter((issue) => issue.issue_id !== result.issue.issue_id)]);
      setInvestigations((current) => [
        result.investigation_run,
        ...current.filter((run) => run.investigation_run_id !== result.investigation_run.investigation_run_id)
      ]);
      setSelectedIssueId(result.issue.issue_id);
      setSelectedInvestigationId(result.investigation_run.investigation_run_id);
      setStateText("ChatOps artifacts created");
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "ChatOps intake failed");
    }
  }

  async function startSelectedInvestigation() {
    if (connection !== "live") return;
    const issueSeed = selectedIssue?.seed_trace_id_nullable || seedTraceId || undefined;
    try {
      const run = await client.startInvestigation(projectId, {
        issueId: selectedIssue?.issue_id,
        seedTraceId: issueSeed,
        problem: investigationProblem.trim() || selectedIssue?.title,
        filters: filterStatus ? { status: filterStatus } : {}
      });
      setInvestigations((current) => [run, ...current.filter((item) => item.investigation_run_id !== run.investigation_run_id)]);
      const impact = investigationImpact(run);
      if (impact) {
        setImpactReports((current) => [impact, ...current.filter((report) => report.report_id !== impact.report_id)]);
      }
      setSelectedInvestigationId(run.investigation_run_id);
      setStateText(`investigation ${run.status}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "investigation failed");
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
          <button onClick={() => void createManualIssue()}>
            <AlertTriangle size={15} />
            Create issue
          </button>
        </div>

        <div className="issueCreate secondaryCreate">
          <input value={screenshotTitle} onChange={(event) => setScreenshotTitle(event.target.value)} placeholder="Screenshot issue title" />
          <input value={screenshotPayloadId} onChange={(event) => setScreenshotPayloadId(event.target.value)} placeholder="Screenshot payload id" />
          <input value={screenshotText} onChange={(event) => setScreenshotText(event.target.value)} placeholder="Extracted screenshot text" />
          <button onClick={() => void createScreenshotIssue()}>
            <FileSearch size={15} />
            Screenshot intake
          </button>
          {screenshotResult ? (
            <p className="systemNote">{screenshotResult.candidate_seed_traces.length} candidate seed traces</p>
          ) : null}
        </div>

        <div className="issueCreate secondaryCreate">
          <input value={chatMessage} onChange={(event) => setChatMessage(event.target.value)} placeholder="ChatOps message" />
          <button onClick={() => void runChatopsIntake()}>
            <Network size={15} />
            ChatOps investigate
          </button>
          {chatopsResult ? <p className="systemNote">{chatopsResult.response}</p> : null}
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
              <Metric icon={<Activity />} label="Updated" value={formatTime(selectedIssue.updated_at)} />
            </div>

            <div className="issueSections">
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

              <section className="issueSection impactSection">
                <h4>Impact</h4>
                {selectedImpact ? (
                  <>
                    <div className="metricsRow issueMetrics">
                      <Metric icon={<FileSearch />} label="Traces" value={String(selectedImpact.matching_trace_count)} />
                      <Metric icon={<Database />} label="Sessions" value={String(selectedImpact.affected_session_count)} />
                      <Metric icon={<Shield />} label="Entities" value={String(selectedImpact.affected_entity_count)} />
                    </div>
                    <p className="entityDescription">{selectedImpact.generated_summary}</p>
                    <div className="sectionRows">
                      <div>
                        <strong>Representative traces</strong>
                        <span>{selectedImpact.representative_trace_ids.join(", ") || "none"}</span>
                      </div>
                      <div>
                        <strong>Task types</strong>
                        <span>{formatCounts(selectedImpact.task_type_distribution)}</span>
                      </div>
                      <div>
                        <strong>Dimensions</strong>
                        <span>{Object.keys(selectedImpact.dimension_distribution).join(", ") || "none"}</span>
                      </div>
                    </div>
                  </>
                ) : (
                  <p className="systemNote">No impact report selected</p>
                )}
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
            </div>
          </>
        ) : (
          <div className="emptyState">{stateText}</div>
        )}
      </section>
    </div>
  );
}

function PromptRegistryWorkspace(props: {
  client: OpenAbmClient;
  connection: ConnectionState;
  projectId: string;
}) {
  const { client, connection, projectId } = props;
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
  const [rendered, setRendered] = useState("");
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
      const result = await client.renderPrompt(projectId, selectedPrompt.prompt_id, renderCommitId, variables);
      setRendered(result.rendered);
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
                    <button
                      key={version.prompt_version_id}
                      onClick={() => {
                        setTemplateText(version.template_text);
                        setSchemaText(JSON.stringify(version.variables_schema));
                        setRenderCommitId(version.commit_id);
                        setNewCommitId(version.commit_id);
                      }}
                    >
                      <strong>{version.commit_id}</strong>
                      <span>{version.parent_commit_id ? `parent ${version.parent_commit_id}` : "root"}</span>
                      <small>{formatTime(version.created_at)}</small>
                    </button>
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
                  <button onClick={() => void renderSelectedPrompt()}>
                    <Play size={15} />
                    Render
                  </button>
                </div>
                {rendered ? <pre>{rendered}</pre> : null}
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
}) {
  const { client, connection, projectId } = props;
  const [behaviors, setBehaviors] = useState<BehaviorDefinition[]>([]);
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

  async function loadBehaviors() {
    if (connection !== "live") {
      setBehaviors([]);
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
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "backtest failed");
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
              <Metric icon={<Shield />} label="Status" value={selectedBehavior.status} />
              <Metric icon={<Activity />} label="Backtest" value={backtest ? `${backtest.positive_count}/${backtest.trace_count}` : "not run"} />
            </div>
            <div className="behaviorSections">
              <section className="behaviorSection">
                <h4>Detector</h4>
                <pre>{JSON.stringify(selectedBehavior.detector, null, 2)}</pre>
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
                    {backtest.unsupported_reason ? <span>{backtest.unsupported_reason}</span> : null}
                  </div>
                ) : null}
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
            </div>
          </>
        ) : (
          <div className="emptyState">{stateText}</div>
        )}
      </section>
    </div>
  );
}

function DatasetEvalWorkspace(props: {
  client: OpenAbmClient;
  connection: ConnectionState;
  projectId: string;
}) {
  const { client, connection, projectId } = props;
  const [datasets, setDatasets] = useState<DatasetDefinition[]>([]);
  const [examples, setExamples] = useState<DatasetExample[]>([]);
  const [evalRuns, setEvalRuns] = useState<EvalRun[]>([]);
  const [evalResults, setEvalResults] = useState<EvalResult[]>([]);
  const [judges, setJudges] = useState<JudgeDefinition[]>([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState("");
  const [selectedEvalRunId, setSelectedEvalRunId] = useState("");
  const [selectedJudgeId, setSelectedJudgeId] = useState("");
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

  async function loadWorkspace() {
    if (connection !== "live") {
      setDatasets([]);
      setExamples([]);
      setEvalRuns([]);
      setEvalResults([]);
      setJudges([]);
      setStateText("fixture mode");
      return;
    }
    try {
      const [loadedDatasets, loadedRuns, loadedJudges] = await Promise.all([
        client.listDatasets(projectId),
        client.listEvalRuns(projectId),
        client.listJudges(projectId)
      ]);
      setDatasets(loadedDatasets);
      setEvalRuns(loadedRuns);
      setJudges(loadedJudges);
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
      const run = await client.runEval(
        projectId,
        selectedDataset.latest_version_id,
        [selectedJudgeId],
        baselineId || undefined
      );
      setEvalRuns((current) => [run, ...current]);
      setSelectedEvalRunId(run.eval_run_id);
      setStateText(`eval completed: ${run.eval_run_id}`);
    } catch (error) {
      setStateText(error instanceof Error ? error.message : "eval run failed");
    }
  }

  async function compareRuns() {
    if (connection !== "live" || !baselineId || !candidateId) return;
    try {
      const result = await client.compareEvalRuns(projectId, baselineId, candidateId);
      setComparison(result);
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
                    <select value={baselineId} onChange={(event) => setBaselineId(event.target.value)}>
                      <option value="">None</option>
                      {datasetRuns.map((run) => (
                        <option key={run.eval_run_id} value={run.eval_run_id}>{run.eval_run_id}</option>
                      ))}
                    </select>
                  </label>
                  <button className="primaryButton" onClick={() => void runSelectedEval()}>
                    <Play size={15} />
                    Run
                  </button>
                </div>
              </section>

              <section className="datasetSection evalHistory">
                <h4>Eval history</h4>
                <div className="evalRows">
                  {datasetRuns.map((run) => (
                    <button
                      className={run.eval_run_id === selectedRun?.eval_run_id ? "selectedEval" : ""}
                      key={run.eval_run_id}
                      onClick={() => {
                        setSelectedEvalRunId(run.eval_run_id);
                        setCandidateId(run.eval_run_id);
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
                    <select value={baselineId} onChange={(event) => setBaselineId(event.target.value)}>
                      <option value="">Select baseline</option>
                      {datasetRuns.map((run) => (
                        <option key={run.eval_run_id} value={run.eval_run_id}>{run.eval_run_id}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Candidate
                    <select value={candidateId} onChange={(event) => setCandidateId(event.target.value)}>
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
                    <strong>Pass delta {formatSigned(comparison.pass_rate_delta)}</strong>
                    <span>Fixed {comparison.fixed_failures.length} · new {comparison.new_failures.length} · unchanged {comparison.unchanged_failures.length}</span>
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
    configs: { label: "Configs", value: "ready", detail: "Runtime config versions and comparisons are API-backed" },
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
    configs: [
      { icon: <KeyRound />, title: "Config versions", status: "immutable commits available", phase: "Phase 7" },
      { icon: <FileSearch />, title: "Config compare", status: "content diffs available", phase: "Phase 7" },
      { icon: <Network />, title: "Runtime bundles", status: "model/tool/retrieval payloads supported", phase: "Phase 7" }
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

function formatScore(score: Record<string, unknown>) {
  const nestedValue = asRecord(score.value);
  const verdict = nestedValue.verdict ?? score.verdict ?? score.status ?? "score";
  const value = nestedValue.score ?? score.score;
  const failureMode = score.failure_mode ? ` · ${String(score.failure_mode)}` : "";
  return value == null
    ? `${String(verdict)}${failureMode}`
    : `${String(verdict)} ${String(value)}${failureMode}`;
}

function formatSigned(value: number | null | undefined) {
  if (value == null) return "none";
  const rounded = Math.round(value * 1000) / 10;
  return `${rounded > 0 ? "+" : ""}${rounded}%`;
}

function parseJsonObject(value: string): Record<string, unknown> {
  const parsed = JSON.parse(value) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Expected a JSON object");
  }
  return parsed as Record<string, unknown>;
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
