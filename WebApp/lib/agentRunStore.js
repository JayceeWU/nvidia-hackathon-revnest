import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const globalForRuns = globalThis;
const runs = globalForRuns.revNestAgentRuns || new Map();

if (process.env.NODE_ENV !== "production") {
  globalForRuns.revNestAgentRuns = runs;
}

const webRoot = process.cwd();
const repoRoot = path.resolve(webRoot, "..");
const clawRoot = path.join(repoRoot, "Claw");
const runsDir = path.join(clawRoot, "runs");
const agentRunFixture = process.env.REVNEST_AGENT_RUN_FIXTURE || "";
const agentRunFixturesAllowed = process.env.REVNEST_ALLOW_AGENT_FIXTURES === "1";
const activeAgentRunFixture = agentRunFixturesAllowed ? agentRunFixture : "";
const defaultToolModel = process.env.REVNEST_TOOL_MODEL || process.env.REVNEST_OPENCLAW_MODEL || "ollama-local/qwen3.6:35b";
const defaultToolEndpoint = process.env.REVNEST_TOOL_MODEL_BASE_URL || "http://127.0.0.1:11434/v1";
const defaultTraceReasoningModel = process.env.REVNEST_TRACE_REASONING_MODEL || "nemotron3:33b";
const defaultTraceReasoningEndpoint = process.env.REVNEST_TRACE_REASONING_BASE_URL || "http://127.0.0.1:11434/v1";
const defaultReasoningModel = process.env.REVNEST_FINAL_REASONING_MODEL || "nemotron-3-super:latest";
const defaultReasoningEndpoint = process.env.REVNEST_FINAL_REASONING_BASE_URL || "http://127.0.0.1:11434/v1";
const defaultToolModelTimeoutSeconds = process.env.REVNEST_TOOL_MODEL_TIMEOUT_SECONDS || process.env.REVNEST_OPENCLAW_PROVIDER_TIMEOUT_SECONDS || "300";

function sanitize(value) {
  return String(value || "run").replace(/[^a-zA-Z0-9_-]/g, "-").slice(0, 80);
}

function normalizePropertyType(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "airbnb" || normalized.includes("airbnb") || normalized.includes("vacation rental") || normalized.includes("entire") || normalized.includes("private room") || normalized.includes("shared room") || normalized.includes("apartment") || normalized.includes("house") || normalized.includes("stay")) return "airbnb";
  if (normalized === "hotel" || normalized.includes("hotel") || normalized.includes("motel")) return "hotel";
  return null;
}

function normalizeRuntimeMode(value, propertyType) {
  if (propertyType === "airbnb") return "host-openclaw";
  if (propertyType === "hotel") return "nemoclaw";
  const normalized = String(value || "").trim().toLowerCase();
  if (["split-demo", "auto", "host-openclaw", "nemoclaw"].includes(normalized)) {
    return normalized;
  }
  return "split-demo";
}

function normalizeHotelScope(value, propertyType) {
  if (propertyType !== "hotel") return null;
  const normalized = String(value || "").trim().toLowerCase().replace(/_/g, "-");
  if (normalized === "all-room-types") return "all-room-types";
  return "room-type";
}

function runLogPath(runId) {
  return path.join(runsDir, `${runId}.log`);
}

function parsePositiveInteger(value) {
  const parsed = Number(String(value || "").trim());
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function processGroupForPid(pid) {
  const result = spawnSync("ps", ["-o", "pgid=", "-p", String(pid)], {
    encoding: "utf8",
    timeout: 1000,
  });
  if (result.status !== 0) return null;
  return parsePositiveInteger(result.stdout);
}

function processGroupsForRunId(runId) {
  if (!runId) return [];
  const result = spawnSync("pgrep", ["-af", String(runId)], {
    encoding: "utf8",
    timeout: 1000,
  });
  if (result.status !== 0 || !result.stdout) return [];
  const groups = new Set();
  for (const line of result.stdout.split(/\r?\n/)) {
    const match = line.match(/^\s*(\d+)\s+(.*)$/);
    if (!match) continue;
    const pid = parsePositiveInteger(match[1]);
    const command = match[2] || "";
    if (!pid || pid === process.pid) continue;
    if (!/(run_pricing_agent\.py|pricing_reasoning_trace\.py|openclaw|openclaw-agent)/.test(command)) continue;
    const pgid = processGroupForPid(pid);
    if (pgid && pgid !== process.pid) groups.add(pgid);
  }
  return [...groups];
}

function closeAgentBrowserSession(runId) {
  spawnSync("agent-browser", ["--session", String(runId), "close"], {
    cwd: clawRoot,
    env: process.env,
    stdio: "ignore",
    timeout: 5000,
  });
}

function signalProcessGroup(pgid, signal) {
  try {
    process.kill(-pgid, signal);
    return true;
  } catch (error) {
    if (error.code === "ESRCH") return false;
    throw error;
  }
}

export function isHostRunProcessAlive(runId) {
  return processGroupsForRunId(runId).length > 0;
}

function inferStatus(events) {
  const finish = [...events].reverse().find((event) => event.stage === "agent_finish");
  if (finish?.status === "completed") return "completed";
  if (finish?.status === "failed") return "failed";
  return "unknown";
}

function inferError(events) {
  return [...events].reverse().find((event) => event.error)?.error || null;
}

function defaultModelRouting() {
  return {
    toolModel: defaultToolModel,
    toolEndpoint: defaultToolEndpoint,
    toolModelRole: "tool_call_orchestration_only",
    traceReasoningModel: defaultTraceReasoningModel,
    traceReasoningEndpoint: defaultTraceReasoningEndpoint,
    traceReasoningModelRole: "fast_visible_substage_reasoning_trace",
    reasoningModel: defaultReasoningModel,
    reasoningEndpoint: defaultReasoningEndpoint,
    reasoningModelRole: "final_reasoning_verification_only",
  };
}

function assertAgentRunFixtureAllowed() {
  if (!agentRunFixture || agentRunFixturesAllowed) return;
  throw new Error("REVNEST_AGENT_RUN_FIXTURE is test-only. Set REVNEST_ALLOW_AGENT_FIXTURES=1 only for e2e test servers.");
}

function modelRoutingFromEvents(events, fallback = defaultModelRouting()) {
  const event = events.find((item) => item?.metadata?.modelRouting);
  return event?.metadata?.modelRouting || fallback;
}

const PRICING_REASONING_ORDER = [
  "supply_snapshot",
  "demand_snapshot",
  "supply_demand_synthesis",
  "occupancy_result",
  "guardrail_check",
  "calculator_run",
  "final_calendar",
  "final_reasoning_verification",
];

function labelizeSubstage(value) {
  return String(value || "reasoning step")
    .split("_")
    .filter(Boolean)
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}

function arrayFrom(value) {
  return Array.isArray(value) ? value : [];
}

function objectFrom(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function pricingReasoningRank(event) {
  const metadata = objectFrom(event?.metadata);
  const status = event?.status || "info";
  let rank = 0;
  if (status === "started") rank = 1;
  else if (status === "failed") rank = 2;
  else if (status === "info" || status === "completed" || status === "skipped") rank = 3;
  if (metadata.reasoningEngine === "source_fact_trace") rank += 1;
  if (metadata.reasoningEngine === "nemotron") rank += 2;
  if (metadata.finalReasoningVerification) rank += 3;
  return rank;
}

function formatPricingReasoningStep(event) {
  const metadata = objectFrom(event.metadata);
  const finalVerification = objectFrom(metadata.finalReasoningVerification);
  return {
    id: `${event.timestamp || "event"}-${event.substage}`,
    timestamp: event.timestamp || null,
    stage: event.stage,
    substage: event.substage,
    label: labelizeSubstage(event.substage),
    status: event.status || "info",
    summary: event.message || finalVerification.summary || "",
    facts: arrayFrom(metadata.facts),
    metrics: objectFrom(metadata.metrics || finalVerification.checked),
    sources: arrayFrom(metadata.sources),
    confidence: metadata.confidence || null,
    engine: metadata.reasoningEngine || null,
    model: metadata.reasoningModel || finalVerification.model || null,
    endpoint: metadata.reasoningEndpoint || finalVerification.endpoint || null,
    tool: event.tool || event.called_skill || event.skill || finalVerification.tool || null,
    rank: pricingReasoningRank(event),
  };
}

function pricingReasoningStepsFromEvents(events) {
  const bySubstage = new Map();
  for (const event of events || []) {
    if (event?.stage !== "pricing_decision" || !event.substage) continue;
    const next = formatPricingReasoningStep(event);
    const existing = bySubstage.get(event.substage);
    if (!existing || next.rank >= existing.rank) {
      bySubstage.set(event.substage, next);
    }
  }
  const ordered = [];
  for (const substage of PRICING_REASONING_ORDER) {
    if (bySubstage.has(substage)) {
      ordered.push(bySubstage.get(substage));
      bySubstage.delete(substage);
    }
  }
  return [...ordered, ...bySubstage.values()].sort((left, right) => {
    const leftOrder = PRICING_REASONING_ORDER.indexOf(left.substage);
    const rightOrder = PRICING_REASONING_ORDER.indexOf(right.substage);
    if (leftOrder !== -1 || rightOrder !== -1) {
      return (leftOrder === -1 ? 999 : leftOrder) - (rightOrder === -1 ? 999 : rightOrder);
    }
    return String(left.timestamp || "").localeCompare(String(right.timestamp || ""));
  });
}

function finalReasoningVerificationFromEvents(events) {
  const event = [...events].reverse().find(
    (item) =>
      item?.substage === "final_reasoning_verification" ||
      item?.metadata?.finalReasoningVerification,
  );
  if (!event) return null;
  return event.metadata?.finalReasoningVerification || {
    status: event.status,
    summary: event.message,
    model: event.metadata?.reasoningModel,
    endpoint: event.metadata?.reasoningEndpoint,
    tool: event.tool,
  };
}

export function parseProgressLog(logPath) {
  if (!fs.existsSync(logPath)) return [];
  return fs
    .readFileSync(logPath, "utf8")
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => {
      try {
        return JSON.parse(line);
      } catch {
        return null;
      }
    })
    .filter(Boolean);
}

export function getRun(runId) {
  const run = runs.get(runId);
  const logPath = run?.logPath || runLogPath(runId);
  const events = parseProgressLog(logPath);
  let status = run?.status || inferStatus(events);
  if (run?.process && run.process.exitCode === null && run.status !== "stopped") {
    status = "running";
  } else if (run?.process && run.process.exitCode !== null && status === "running") {
    status = run.process.exitCode === 0 ? inferStatus(events) : "failed";
  }
  return {
    runId,
    accountId: run?.accountId,
    propertyId: run?.propertyId,
    propertyIds: run?.propertyIds || [],
    propertyType: run?.propertyType,
    hotelScope: run?.hotelScope || null,
    runtimeMode: run?.runtimeMode,
    conversationId: run?.conversationId,
    status,
    exitCode: run?.process?.exitCode ?? run?.exitCode ?? null,
    logPath,
    startedAt: run?.startedAt || events.find((event) => event.stage === "agent_start")?.timestamp || null,
    error: inferError(events),
    fixtureMode: run?.fixtureMode || activeAgentRunFixture || null,
    recoveryEnabled: false,
    modelRouting: modelRoutingFromEvents(events, run?.modelRouting || defaultModelRouting()),
    toolTrace: events.map((event) => ({
      timestamp: event.timestamp,
      stage: event.stage,
      substage: event.substage || null,
      tool: event.tool || event.called_skill || event.skill || null,
      status: event.status,
      message: event.message,
      metadata: event.metadata || null,
    })),
    finalReasoningVerification: finalReasoningVerificationFromEvents(events),
    pricingReasoningSteps: pricingReasoningStepsFromEvents(events),
    events,
  };
}

export function getRunsForProperty(propertyId) {
  return [...runs.values()]
    .filter((run) => run.propertyId === propertyId || (Array.isArray(run.propertyIds) && run.propertyIds.includes(propertyId)))
    .map((run) => getRun(run.runId))
    .sort((left, right) => {
      const leftStarted = runs.get(left.runId)?.startedAt || "";
      const rightStarted = runs.get(right.runId)?.startedAt || "";
      return rightStarted.localeCompare(leftStarted);
    });
}

export function getLatestRunForProperty(propertyId) {
  return getRunsForProperty(propertyId)[0] || null;
}

export function startAgentRun(payload) {
  assertAgentRunFixtureAllowed();
  fs.mkdirSync(runsDir, { recursive: true });

  if (!payload.accountId) {
    throw new Error("accountId is required");
  }

  const propertyType = normalizePropertyType(payload.propertyType);
  if (!propertyType) {
    throw new Error("propertyType must resolve to airbnb or hotel");
  }
  const runtimeMode = normalizeRuntimeMode(payload.runtimeMode ?? payload.runtime_mode, propertyType);
  const hotelScope = normalizeHotelScope(payload.hotelScope ?? payload.hotel_scope, propertyType);

  const now = Date.now();
  const runSubject = hotelScope === "all-room-types" ? "hotel-all-room-types" : payload.propertyId || payload.myPlace || propertyType;
  const conversationId = payload.conversationId || `revy-${sanitize(runSubject)}-${now}`;
  const runId = `pricing-workflow-${sanitize(runSubject)}-${now}`;
  const logPath = runLogPath(runId);
  const runnerScript =
    activeAgentRunFixture === "demo1"
      ? "tests/demo1_airbnb_agent_fixture.py"
      : activeAgentRunFixture === "demo2"
        ? "tests/demo2_agent_fixture.py"
        : "tools/run_pricing_agent.py";
  const args = [
    runnerScript,
    "--clear-log",
    "--session-id",
    runId,
    "--run-id",
    runId,
    "--conversation-id",
    conversationId,
    "--log-path",
    logPath,
    "--account-id",
    payload.accountId,
    "--property-type",
    propertyType,
    ...(hotelScope ? ["--hotel-scope", hotelScope] : []),
    "--runtime-mode",
    runtimeMode,
    "--model",
    defaultToolModel,
    "--trace-reasoning-model",
    defaultTraceReasoningModel,
    "--trace-reasoning-base-url",
    defaultTraceReasoningEndpoint,
    "--final-reasoning-model",
    defaultReasoningModel,
    "--thinking",
    "medium",
    "--timeout-seconds",
    "1800",
  ];

  if (payload.propertyId) {
    args.push("--property-id", payload.propertyId);
  }
  if (payload.minPrice !== undefined) {
    args.push("--min-price", String(payload.minPrice));
  }
  if (payload.maxPrice !== undefined) {
    args.push("--max-price", String(payload.maxPrice));
  }
  if (payload.pricingHorizon !== undefined) {
    args.push("--pricing-horizon", String(payload.pricingHorizon));
  }
  if (payload.myPlace) {
    args.push("--my-place", payload.myPlace);
  }

  if (payload.supplementalInfo) {
    args.push("--message-extra", `Host supplemental information: ${payload.supplementalInfo}`);
  }

  const child = spawn("python3", args, {
    cwd: clawRoot,
    env: {
      ...process.env,
      REVNEST_WEBAPP_AGENT_RUN: "1",
      REVNEST_TOOL_MODEL: defaultToolModel,
      REVNEST_TOOL_MODEL_BASE_URL: defaultToolEndpoint,
      REVNEST_TRACE_REASONING_MODEL: defaultTraceReasoningModel,
      REVNEST_TRACE_REASONING_BASE_URL: defaultTraceReasoningEndpoint,
      REVNEST_FINAL_REASONING_MODEL: defaultReasoningModel,
      REVNEST_FINAL_REASONING_BASE_URL: defaultReasoningEndpoint,
      REVNEST_TOOL_MODEL_TIMEOUT_SECONDS: defaultToolModelTimeoutSeconds,
    },
    detached: true,
    stdio: ["ignore", "ignore", "ignore"],
  });
  child.unref();

  const run = {
    runId,
    conversationId,
    accountId: payload.accountId,
    propertyId: payload.propertyId,
    propertyIds: Array.isArray(payload.propertyIds) ? payload.propertyIds : [],
    propertyType,
    hotelScope,
    runtimeMode,
    modelRouting: defaultModelRouting(),
    fixtureMode: activeAgentRunFixture || null,
    logPath,
    process: child,
    status: "running",
    startedAt: new Date().toISOString(),
  };
  runs.set(runId, run);
  child.on("exit", (code) => {
    const current = runs.get(runId);
    if (current) {
      current.status = current.status === "stopped" ? "stopped" : code === 0 ? "completed" : "failed";
      current.exitCode = code;
    }
  });

  return {
    runId,
    conversationId,
    accountId: payload.accountId,
    propertyId: payload.propertyId,
    propertyIds: Array.isArray(payload.propertyIds) ? payload.propertyIds : [],
    hotelScope,
    runtimeMode,
    modelRouting: defaultModelRouting(),
    fixtureMode: activeAgentRunFixture || null,
    status: "running",
    logPath,
    startedAt: run.startedAt,
  };
}

export function stopAgentRun(runId) {
  const run = runs.get(runId);
  const processGroups = new Set(processGroupsForRunId(runId));
  if (run?.process?.pid) {
    processGroups.add(run.process.pid);
  }

  closeAgentBrowserSession(runId);

  const signaledGroups = [];
  for (const pgid of processGroups) {
    if (signalProcessGroup(pgid, "SIGTERM")) {
      signaledGroups.push(pgid);
    }
  }
  if (signaledGroups.length > 0) {
    const killTimer = setTimeout(() => {
      for (const pgid of signaledGroups) {
        signalProcessGroup(pgid, "SIGKILL");
      }
    }, 3500);
    if (typeof killTimer.unref === "function") killTimer.unref();
  }
  if (run) run.status = "stopped";
  return { runId, status: "stopped", stoppedProcessGroups: signaledGroups };
}

export function stopAgentRunsForProperty(propertyId) {
  const stopped = [];
  for (const [runId, run] of runs.entries()) {
    const ownsProperty = run.propertyId === propertyId || (Array.isArray(run.propertyIds) && run.propertyIds.includes(propertyId));
    if (!ownsProperty || run.status !== "running") {
      continue;
    }
    stopped.push(stopAgentRun(runId));
  }
  return stopped;
}
