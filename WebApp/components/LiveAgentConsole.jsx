"use client";

import { useEffect, useRef, useState } from "react";
import { StepIcon, CheckIcon, PlayIcon, ArrowRightIcon, SparkleIcon } from "./AgentIcons";

// Live Agent Console — primary demo entry point.
// User submits a prompt, then the agent "runs" each tool one by one and
// streams the running/done log into the console. Tool sequence is the same
// 5-step compact flow as the inline AgentReasoningPanel.

const DEFAULT_PROMPT =
  "Use the RevNest workflow to price the Santa Cruz Coastal Suite for May 17, 2026.";

const STREAM_STEPS = [
  {
    name: "check_weather",
    label: "check_weather()",
    icon: "weather",
    runningMs: 800,
    runningText: "Calling Open-Meteo for Santa Cruz, CA forecast…",
    doneText: "Weather checked · partly cloudy · neutral signal",
  },
  {
    name: "scrape_competitor_price",
    label: "scrape_competitor_price()",
    icon: "competitor",
    runningMs: 900,
    runningText: "Loading authorized competitor snapshot for 2026-05-17…",
    doneText: "Median $238 across 5 comps · static price 21% below market",
  },
  {
    name: "get_local_events",
    label: "get_local_events()",
    icon: "event",
    runningMs: 850,
    runningText: "Querying Ticketmaster Discovery API · 30 day window…",
    doneText: "Stadium concert 2.4mi · 1.34x demand multiplier",
  },
  {
    name: "calc_demand_index",
    label: "calc_demand_index()",
    icon: "calc",
    runningMs: 700,
    runningText: "Combining market median, event multiplier, host preferences…",
    doneText: "Demand index 1.34x · raw price $246",
  },
  {
    name: "update_price",
    label: "update_price()",
    icon: "send",
    runningMs: 750,
    runningText: "Applying guardrails, queueing for host approval…",
    doneText: "$189 → $246 · queued · within 30% cap",
  },
];

export default function LiveAgentConsole({ onViewFullTrace }) {
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [running, setRunning] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [logs, setLogs] = useState([]); // { stepIndex, type: 'running'|'done', text }
  const [activeIndex, setActiveIndex] = useState(-1);
  const timersRef = useRef([]);
  const logEndRef = useRef(null);

  useEffect(() => {
    return () => {
      timersRef.current.forEach((id) => clearTimeout(id));
      timersRef.current = [];
    };
  }, []);

  useEffect(() => {
    if (logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [logs]);

  function reset() {
    timersRef.current.forEach((id) => clearTimeout(id));
    timersRef.current = [];
    setLogs([]);
    setActiveIndex(-1);
    setRunning(false);
    setCompleted(false);
  }

  function startRun() {
    if (running) return;
    reset();
    setRunning(true);

    let cumulative = 0;
    STREAM_STEPS.forEach((step, index) => {
      const startAt = cumulative;
      cumulative += step.runningMs;
      const finishAt = cumulative;

      timersRef.current.push(
        setTimeout(() => {
          setActiveIndex(index);
          setLogs((current) => [
            ...current,
            {
              id: `${index}-running`,
              stepIndex: index,
              type: "running",
              label: step.label,
              text: step.runningText,
              icon: step.icon,
            },
          ]);
        }, startAt),
      );

      timersRef.current.push(
        setTimeout(() => {
          setLogs((current) => [
            ...current,
            {
              id: `${index}-done`,
              stepIndex: index,
              type: "done",
              label: step.label,
              text: step.doneText,
              icon: step.icon,
            },
          ]);
        }, finishAt),
      );
    });

    timersRef.current.push(
      setTimeout(() => {
        setRunning(false);
        setCompleted(true);
        setActiveIndex(STREAM_STEPS.length - 1);
      }, cumulative + 80),
    );
  }

  function handleSubmit(event) {
    event.preventDefault();
    if (running) return;
    startRun();
  }

  return (
    <section className="live-agent">
      <header className="live-agent-header">
        <div>
          <span className="agent-badge">
            <SparkleIcon width={14} height={14} />
            Live Agent
          </span>
          <h1>Watch the agent decide</h1>
          <p>
            Send a pricing prompt and the RevNest agent will call each tool in
            sequence. Every tool call streams live so you can see what the
            agent inspected before it moved the price.
          </p>
        </div>
      </header>

      <form className="live-agent-prompt" onSubmit={handleSubmit}>
        <label htmlFor="live-agent-input">Prompt</label>
        <div className="prompt-row">
          <textarea
            id="live-agent-input"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            rows={2}
            placeholder="Ask the agent to price a property…"
          />
          <button
            type="submit"
            className="primary-action"
            disabled={running}
          >
            {running ? (
              <>
                <span className="loading-dot" /> Running…
              </>
            ) : (
              <>
                <PlayIcon width={14} height={14} />
                Run agent
              </>
            )}
          </button>
        </div>
      </form>

      <div className="live-agent-grid">
        <aside className="live-tool-rail" aria-label="Tool call status">
          <h3>Tool call sequence</h3>
          <ol>
            {STREAM_STEPS.map((step, index) => {
              const isActive = activeIndex === index && running;
              const isDone =
                (completed && index <= activeIndex) ||
                logs.some((log) => log.stepIndex === index && log.type === "done");
              return (
                <li
                  key={step.name}
                  className={`tool-rail-item ${isActive ? "active" : ""} ${isDone ? "done" : ""}`}
                >
                  <span className="tool-rail-icon">
                    {isDone ? (
                      <CheckIcon width={14} height={14} />
                    ) : isActive ? (
                      <span className="loading-dot" />
                    ) : (
                      <StepIcon name={step.icon} width={14} height={14} />
                    )}
                  </span>
                  <code>{step.label}</code>
                </li>
              );
            })}
          </ol>
        </aside>

        <div className="live-console">
          <div className="console-screen" role="log" aria-live="polite">
            {logs.length === 0 ? (
              <div className="console-empty">
                Waiting for prompt. The agent will narrate every tool call here.
              </div>
            ) : (
              logs.map((log) => (
                <div key={log.id} className={`console-line ${log.type}`}>
                  <span className="console-marker">
                    {log.type === "done" ? (
                      <CheckIcon width={12} height={12} />
                    ) : (
                      <span className="loading-dot" />
                    )}
                  </span>
                  <span className="console-step">
                    Step {log.stepIndex + 1}:
                    <code>{log.label}</code>
                  </span>
                  <span className="console-text">{log.text}</span>
                </div>
              ))
            )}
            <div ref={logEndRef} />
          </div>

          {completed ? (
            <div className="console-finale">
              <div>
                <strong>Run complete.</strong>
                <span>
                  Agent recommended <b>$246</b> (was $189) for May 17, 2026 — queued
                  for host approval.
                </span>
              </div>
              <button type="button" className="primary-action" onClick={onViewFullTrace}>
                View full reasoning trace
                <ArrowRightIcon width={14} height={14} />
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
