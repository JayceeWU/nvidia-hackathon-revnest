"use client";

import { CheckIcon } from "./AgentIcons";

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

export default function AgentRunPanels({ events = [], emptyMessage = "Waiting for the first progress event..." }) {
  const visibleEvents = Array.isArray(events) ? events : [];

  return (
    <div className="live-agent-grid console-only">
      <div className="live-console">
        <div className="console-screen" role="log" aria-live="polite">
          {visibleEvents.length === 0 ? (
            <div className="console-empty">{emptyMessage}</div>
          ) : (
            visibleEvents.map((event, index) => (
              <div
                key={`${event.timestamp || "event"}-${event.stage}-${index}`}
                className={`console-line ${event.status === "completed" ? "done" : "running"}`}
              >
                <span className="console-marker">
                  {event.status === "completed" ? <CheckIcon width={12} height={12} /> : <span className="loading-dot" />}
                </span>
                <span className="console-step">
                  {event.status}
                  <code>{event.tool || event.stage}</code>
                </span>
                <span className="console-text">{event.message}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
