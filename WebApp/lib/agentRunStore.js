import { spawn } from "node:child_process";
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

function sanitize(value) {
  return String(value || "run").replace(/[^a-zA-Z0-9_-]/g, "-").slice(0, 80);
}

function normalizePropertyType(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "airbnb" || normalized.includes("airbnb") || normalized.includes("vacation rental") || normalized.includes("entire") || normalized.includes("private room") || normalized.includes("shared room") || normalized.includes("apartment") || normalized.includes("house") || normalized.includes("stay")) return "airbnb";
  if (normalized === "hotel" || normalized.includes("hotel") || normalized.includes("motel")) return "hotel";
  return null;
}

function runLogPath(runId) {
  return path.join(runsDir, `${runId}.log`);
}

function inferStatus(events) {
  const finish = [...events].reverse().find((event) => event.stage === "agent_finish");
  if (finish?.status === "completed") return "completed";
  if (finish?.status === "failed") return "failed";
  return "unknown";
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
    propertyId: run?.propertyId,
    conversationId: run?.conversationId,
    status,
    exitCode: run?.process?.exitCode ?? run?.exitCode ?? null,
    logPath,
    events,
  };
}

export function getRunsForProperty(propertyId) {
  return [...runs.values()]
    .filter((run) => run.propertyId === propertyId)
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
  fs.mkdirSync(runsDir, { recursive: true });

  if (!payload.accountId) {
    throw new Error("accountId is required");
  }

  const propertyType = normalizePropertyType(payload.propertyType);
  if (!propertyType) {
    throw new Error("propertyType must resolve to airbnb or hotel");
  }

  const now = Date.now();
  const conversationId = payload.conversationId || `revy-${sanitize(payload.propertyId || payload.myPlace || propertyType)}-${now}`;
  const runId = `pricing-workflow-${sanitize(payload.propertyId || payload.myPlace || propertyType)}-${now}`;
  const logPath = runLogPath(runId);
  const args = [
    "tools/run_pricing_agent.py",
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
    },
    detached: true,
    stdio: ["ignore", "ignore", "ignore"],
  });
  child.unref();

  const run = {
    runId,
    conversationId,
    propertyId: payload.propertyId,
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
    propertyId: payload.propertyId,
    status: "running",
    logPath,
    startedAt: run.startedAt,
  };
}

export function stopAgentRun(runId) {
  const run = runs.get(runId);
  if (!run?.process?.pid) {
    return { runId, status: "stopped" };
  }
  try {
    process.kill(-run.process.pid, "SIGTERM");
  } catch (error) {
    if (error.code !== "ESRCH") throw error;
  }
  run.status = "stopped";
  return { runId, status: "stopped" };
}

export function stopAgentRunsForProperty(propertyId) {
  const stopped = [];
  for (const [runId, run] of runs.entries()) {
    if (run.propertyId !== propertyId || run.status !== "running") {
      continue;
    }
    stopped.push(stopAgentRun(runId));
  }
  return stopped;
}
