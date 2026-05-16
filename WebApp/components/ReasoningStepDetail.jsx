"use client";

import { StepIcon } from "./AgentIcons";

// Right-side detail panel for the Reasoning Trace view. Shows the
// step's reasoning text, tool input/output JSON, and a small visual
// summary (signal pill + key numbers) for the current selection.

function impactClass(impact) {
  if (impact === "up") return "signal-up";
  if (impact === "down") return "signal-down";
  if (impact === "cap") return "signal-cap";
  if (impact === "pending") return "signal-pending";
  return "signal-neutral";
}

function JsonBlock({ title, value }) {
  if (value === undefined || value === null) return null;
  let body;
  try {
    body = JSON.stringify(value, null, 2);
  } catch (error) {
    body = String(value);
  }
  return (
    <div className="json-block">
      <span className="json-block-title">{title}</span>
      <pre>
        <code>{body}</code>
      </pre>
    </div>
  );
}

export default function ReasoningStepDetail({ step, summary }) {
  if (!step) {
    return (
      <div className="step-detail empty">
        <h3>Pick a step</h3>
        <p>Select any step in the timeline to inspect what the agent did and why.</p>
      </div>
    );
  }

  const visualNumbers = buildVisualSummary(step, summary);

  return (
    <div className="step-detail">
      <div className="step-detail-head">
        <span className="step-detail-icon">
          <StepIcon name={step.icon} width={20} height={20} />
        </span>
        <div>
          <span className="step-detail-eyebrow">
            Step {step.step}
            {step.tool ? <code>{step.tool}</code> : null}
          </span>
          <h2>{step.label}</h2>
        </div>
        {step.signal ? (
          <span className={`step-signal large ${impactClass(step.signal.impact)}`}>
            {step.signal.label}
          </span>
        ) : null}
      </div>

      <section className="step-detail-section">
        <h3>Reasoning</h3>
        <p>{step.reasoning}</p>
      </section>

      {visualNumbers.length > 0 ? (
        <section className="step-detail-section">
          <h3>Visual summary</h3>
          <div className="visual-summary-grid">
            {visualNumbers.map((item) => (
              <article key={item.label} className={`visual-tile ${item.tone || ""}`}>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
                {item.sub ? <small>{item.sub}</small> : null}
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {step.calculation ? (
        <section className="step-detail-section">
          <h3>Calculation</h3>
          <pre className="calc-block">
            <code>{step.calculation}</code>
          </pre>
        </section>
      ) : null}

      <section className="step-detail-section json-pair">
        <JsonBlock title="Tool input" value={step.tool_input} />
        <JsonBlock title="Tool output" value={step.tool_output} />
      </section>
    </div>
  );
}

function buildVisualSummary(step, summary) {
  const out = [];

  if (step.name === "scrape_competitor_price" || step.name === "fetch_market_rates") {
    if (step.tool_output?.median_rate !== undefined) {
      out.push({ label: "Competitor median", value: `$${step.tool_output.median_rate}`, tone: "info" });
    }
    if (Array.isArray(step.tool_output?.rates)) {
      out.push({ label: "Comparable rates", value: step.tool_output.rates.length, sub: "snapshots" });
    }
  }

  if (step.name === "get_local_events" || step.name === "fetch_demand_signals") {
    if (Array.isArray(step.tool_output?.events)) {
      out.push({ label: "Upcoming events", value: step.tool_output.events.length });
      const top = step.tool_output.events.reduce(
        (best, ev) => (ev.demand_multiplier > (best?.demand_multiplier || 0) ? ev : best),
        null,
      );
      if (top) {
        out.push({
          label: "Top multiplier",
          value: `${top.demand_multiplier.toFixed(2)}x`,
          sub: top.name,
          tone: "up",
        });
      }
    }
  }

  if (step.name === "fetch_history") {
    if (step.tool_output?.occupancy_rate !== undefined) {
      out.push({
        label: "Occupancy",
        value: `${Math.round(step.tool_output.occupancy_rate * 100)}%`,
        tone: "up",
      });
    }
    if (step.tool_output?.revpar !== undefined) {
      out.push({ label: "RevPAR", value: `$${step.tool_output.revpar}`, tone: "info" });
    }
  }

  if (step.name === "calc_demand_index") {
    if (step.tool_output?.demand_index !== undefined) {
      out.push({
        label: "Demand index",
        value: `${step.tool_output.demand_index.toFixed(2)}x`,
        tone: "up",
      });
    }
    if (step.tool_output?.raw_price !== undefined) {
      out.push({ label: "Raw price", value: `$${step.tool_output.raw_price}` });
    }
  }

  if (step.name === "enforce_guardrails") {
    if (step.tool_output?.final_price !== undefined) {
      out.push({
        label: "Final price",
        value: `$${Math.round(step.tool_output.final_price)}`,
        tone: "info",
      });
    }
    if (step.tool_output?.change_pct !== undefined) {
      out.push({
        label: "Change",
        value: `${step.tool_output.change_pct}%`,
        tone: step.tool_output.capped ? "cap" : "up",
      });
    }
  }

  if (step.name === "update_price") {
    if (summary?.old_price !== undefined && summary?.final_price !== undefined) {
      out.push({ label: "Old price", value: `$${summary.old_price}` });
      out.push({ label: "Queued price", value: `$${summary.final_price}`, tone: "info" });
    }
  }

  if (step.name === "check_weather" && Array.isArray(step.tool_output?.forecast)) {
    out.push({ label: "Days forecast", value: step.tool_output.forecast.length });
    const peak = step.tool_output.forecast.reduce(
      (h, day) => (day.high_f > h ? day.high_f : h),
      0,
    );
    if (peak > 0) {
      out.push({ label: "Peak temp", value: `${peak}°F` });
    }
  }

  return out;
}
