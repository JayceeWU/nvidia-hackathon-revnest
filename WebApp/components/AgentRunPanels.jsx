"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckIcon, StepIcon } from "./AgentIcons";

export const TOOL_STAGES = [
  { stage: "context", label: "agent-browser", icon: "skill" },
  { stage: "guardrail_review", label: "guardrail_review.py", icon: "pyTool" },
  { stage: "market_data_parallel", label: "parallel market data", icon: "parallelGroup", groupLead: true },
  { stage: "weather", label: "weather_tool.py", icon: "pyTool", parallelChild: true },
  { stage: "holidays", label: "get_holiday.py", icon: "pyTool", parallelChild: true },
  { stage: "events_ticketmaster", label: "ticketmaster.py", icon: "pyTool", parallelChild: true },
  { stage: "events_serpapi", label: "serpapi.py events", icon: "pyTool", parallelChild: true },
  { stage: "hotel_comps_serpapi", label: "serpapi.py hotels", icon: "pyTool", parallelChild: true },
  { stage: "hotel_comps_moodtrip", label: "MoodTrip hotels", icon: "skill", parallelChild: true },
  { stage: "tourism_tavily", label: "tavily.py", icon: "pyTool", parallelChild: true },
  { stage: "pricing_decision", label: "pricing decision", icon: "skill" },
  { stage: "revpar_publish", label: "publish prices", icon: "skill" },
];

export function buildCompletedAgentEvents(propertyName = "this property") {
  const stamp = "2026-05-13T10:00:00.000Z";
  return [
    { timestamp: stamp, stage: "context", tool: "agent-browser", status: "completed", message: `Loaded listing context for ${propertyName}.` },
    { timestamp: stamp, stage: "guardrail_review", tool: "guardrail_review.py", status: "completed", message: "Validated min and max price guardrails before pricing." },
    { timestamp: stamp, stage: "market_data_parallel", tool: "parallel market data", status: "completed", message: "Merged market signals from parallel tools." },
    { timestamp: stamp, stage: "weather", tool: "weather_tool.py", status: "completed", message: "Checked near-term weather demand impact." },
    { timestamp: stamp, stage: "holidays", tool: "get_holiday.py", status: "completed", message: "Checked holiday and long-weekend calendar effects." },
    { timestamp: stamp, stage: "events_ticketmaster", tool: "ticketmaster.py", status: "completed", message: "Scanned major ticketed events near the listing." },
    { timestamp: stamp, stage: "events_serpapi", tool: "serpapi.py events", status: "completed", message: "Cross-checked local event search results." },
    { timestamp: stamp, stage: "hotel_comps_serpapi", tool: "serpapi.py hotels", status: "completed", message: "Reviewed hotel comp rates in the area." },
    { timestamp: stamp, stage: "hotel_comps_moodtrip", tool: "MoodTrip hotels", status: "completed", message: "Compared hospitality demand patterns." },
    { timestamp: stamp, stage: "tourism_tavily", tool: "tavily.py", status: "completed", message: "Reviewed tourism demand and neighborhood search intent." },
    { timestamp: stamp, stage: "pricing_decision", tool: "pricing decision", status: "completed", message: "Generated Revy's recommended nightly price curve." },
    { timestamp: stamp, stage: "revpar_publish", tool: "publish prices", status: "completed", message: "Saved the completed reasoning trace for review." },
  ];
}

const ACTIVE_STATUSES = new Set(["started", "running", "info"]);
const DONE_STATUSES = new Set(["completed", "skipped"]);
const TERMINAL_STATUSES = new Set(["completed", "failed", "skipped", "stopped"]);
const LIVE_RUN_STATUSES = new Set(["running", "started"]);

function eventIdentity(event) {
  if (event.stage === "agent_start" || event.stage === "agent_finish") {
    return "agent_lifecycle::openclaw agent";
  }
  return [
    event.stage || "stage",
    event.substage || "",
    event.tool || event.called_skill || event.skill || "",
  ].join("::");
}

function eventIconName(event) {
  const match = TOOL_STAGES.find((stage) => stage.stage === event.stage);
  return match?.icon || "skill";
}

function eventTitle(event) {
  return event.tool || event.called_skill || event.substage || event.stage || "agent step";
}

function eventDetail(event) {
  const parts = [event.stage, event.substage].filter(Boolean);
  return parts.join(" / ");
}

function compactEvents(events) {
  const compacted = [];
  const indexes = new Map();

  for (const event of Array.isArray(events) ? events : []) {
    const key = eventIdentity(event);
    const existingIndex = indexes.get(key);
    const next = {
      ...event,
      iconName: eventIconName(event),
      title: eventTitle(event),
      detail: eventDetail(event),
    };

    if (existingIndex === undefined) {
      indexes.set(key, compacted.length);
      compacted.push(next);
      continue;
    }

    const existing = compacted[existingIndex];
    compacted[existingIndex] = {
      ...existing,
      ...next,
      startedAt: existing.startedAt || existing.timestamp,
      completedAt: TERMINAL_STATUSES.has(next.status) ? next.timestamp : existing.completedAt,
    };
  }

  return compacted;
}

function parseTime(value) {
  if (!value) return null;
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? null : time;
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "0s";
  const totalSeconds = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = totalSeconds % 60;
  if (minutes <= 0) return `${remainingSeconds}s`;
  return `${minutes}m ${remainingSeconds}s`;
}

function statusClass(status) {
  if (status === "failed" || status === "stopped") return "failed";
  if (DONE_STATUSES.has(status)) return "done";
  if (ACTIVE_STATUSES.has(status)) return "running";
  return "neutral";
}

function eventSummary(event, fallback) {
  if (!event) return fallback;
  if (event.status === "failed" && event.error) {
    return `${event.error} Please try Run Revy again.`;
  }
  return event.message || event.error || fallback;
}

export default function AgentRunPanels({
  events = [],
  emptyMessage = "Waiting for the first progress event...",
  runStatus = "idle",
  startedAt = null,
}) {
  const [now, setNow] = useState(() => Date.now());
  const visibleEvents = useMemo(() => compactEvents(events), [events]);
  const latestEvent = visibleEvents[visibleEvents.length - 1] || null;
  const firstTimestamp = parseTime(startedAt) || parseTime(visibleEvents[0]?.timestamp);
  const lastTimestamp = parseTime(latestEvent?.completedAt || latestEvent?.timestamp);
  const isTerminalRun = TERMINAL_STATUSES.has(runStatus);
  const isActiveRun = LIVE_RUN_STATUSES.has(runStatus);
  const elapsedSeconds = firstTimestamp ? ((isActiveRun ? now : lastTimestamp || now) - firstTimestamp) / 1000 : 0;
  const workLabel = firstTimestamp && (isActiveRun || isTerminalRun) ? `Worked for ${formatDuration(elapsedSeconds)}` : "Ready";
  const latestSummary = eventSummary(latestEvent, emptyMessage);

  useEffect(() => {
    if (!isActiveRun) return undefined;
    const intervalId = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(intervalId);
  }, [isActiveRun]);

  return (
    <div className="live-agent-grid console-only">
      <div className="live-console">
        <div className="console-screen" role="log" aria-live="polite">
          <div className="agent-work-strip">
            <span className={`agent-work-dot ${isActiveRun ? "running" : ""}`} />
            <strong>{workLabel}</strong>
            <span className={latestEvent?.status === "failed" ? "agent-work-error" : ""}>{latestSummary}</span>
          </div>
          {visibleEvents.length === 0 ? (
            <div className="console-empty">{emptyMessage}</div>
          ) : (
            visibleEvents.map((event, index) => (
              <div
                key={`${event.timestamp || "event"}-${event.stage}-${index}`}
                className={`console-line agent-event-line ${statusClass(event.status)}`}
              >
                <span className="console-marker">
                  {DONE_STATUSES.has(event.status) ? (
                    <CheckIcon width={12} height={12} />
                  ) : ACTIVE_STATUSES.has(event.status) ? (
                    <span className="loading-dot" />
                  ) : (
                    <StepIcon name={event.iconName} width={12} height={12} />
                  )}
                </span>
                <span className="console-step">
                  <code>{event.title}</code>
                  {event.detail ? <small>{event.detail}</small> : null}
                </span>
                <span className="console-text">{event.message}</span>
                {event.error ? <span className="console-error">{event.error}</span> : null}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
