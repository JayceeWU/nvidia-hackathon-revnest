"use client";

import { useState } from "react";
import { StepIcon, CheckIcon, ArrowRightIcon, SparkleIcon } from "./AgentIcons";

// Inline reasoning panel that drops into Property Detail under the price
// forecast. Renders the 5-step compact tool-call flow plus a final
// recommendation card with old/new price, lift, and a "Why this price"
// explanation. Uses the shared 5-step shape from lib/reasoningTrace.js.

function impactClass(impact) {
  if (impact === "up") return "signal-up";
  if (impact === "down") return "signal-down";
  if (impact === "cap") return "signal-cap";
  if (impact === "pending") return "signal-pending";
  return "signal-neutral";
}

function statusBadge(status) {
  if (status === "running") return { className: "step-status running", label: "running" };
  if (status === "pending") return { className: "step-status pending", label: "pending" };
  return { className: "step-status done", label: "done" };
}

export default function AgentReasoningPanel({ summary, steps, onViewFullTrace }) {
  const [expanded, setExpanded] = useState(null);
  if (!summary || !steps || steps.length === 0) return null;

  const lift = summary.revpar_lift_pct ?? summary.change_pct ?? 0;
  const liftLabel = `${lift > 0 ? "+" : ""}${lift}%`;

  return (
    <section className="panel agent-reasoning-panel">
      <div className="panel-heading agent-reasoning-heading">
        <div className="agent-reasoning-title">
          <span className="agent-badge">
            <SparkleIcon width={14} height={14} />
            Agent Reasoning
          </span>
          <h2>Multi-step pricing decision</h2>
          <small>
            {summary.property_name} · {summary.price_date}
          </small>
        </div>
        <button type="button" className="trace-link" onClick={onViewFullTrace}>
          View full trace
          <ArrowRightIcon width={14} height={14} />
        </button>
      </div>

      <ol className="step-flow" role="list">
        {steps.map((step, index) => {
          const badge = statusBadge(step.status);
          const isOpen = expanded === step.step;
          return (
            <li key={step.step} className={`step-card ${isOpen ? "open" : ""}`}>
              <button
                type="button"
                className="step-card-header"
                onClick={() => setExpanded(isOpen ? null : step.step)}
                aria-expanded={isOpen}
              >
                <span className="step-index">{index + 1}</span>
                <span className="step-icon">
                  <StepIcon name={step.icon} width={16} height={16} />
                </span>
                <span className="step-tool">
                  <code>{step.label}</code>
                  <small>{step.result}</small>
                </span>
                <span className={`step-signal ${impactClass(step.signal?.impact)}`}>
                  {step.signal?.label}
                </span>
                <span className={badge.className}>
                  {step.status === "done" ? <CheckIcon width={12} height={12} /> : null}
                  {badge.label}
                </span>
              </button>
              {isOpen ? (
                <div className="step-card-body">
                  <p>{step.reasoning}</p>
                </div>
              ) : null}
            </li>
          );
        })}
      </ol>

      <div className="recommendation-card">
        <div className="recommendation-prices">
          <div className="rec-price old">
            <span>Old price</span>
            <strong>${summary.old_price}</strong>
          </div>
          <ArrowRightIcon width={20} height={20} />
          <div className="rec-price new">
            <span>Agent recommended</span>
            <strong>${summary.final_price}</strong>
          </div>
          <div className="rec-lift">
            <span>RevPAR lift</span>
            <strong>{liftLabel}</strong>
          </div>
        </div>
        <div className="recommendation-why">
          <span className="why-label">Why this price</span>
          <p>{summary.why}</p>
        </div>
      </div>
    </section>
  );
}
