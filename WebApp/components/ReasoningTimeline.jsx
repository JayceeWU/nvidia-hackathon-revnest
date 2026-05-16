"use client";

import { StepIcon, CheckIcon } from "./AgentIcons";

// Vertical timeline of the 10-step reasoning trace, used as the left rail
// of the Reasoning Trace detail view. Selecting a step fires onSelect with
// that step's number so the right detail panel can render its body.

function statusDot(status) {
  if (status === "running") return "timeline-dot running";
  if (status === "pending") return "timeline-dot pending";
  return "timeline-dot done";
}

export default function ReasoningTimeline({ steps, selectedStep, onSelect }) {
  if (!steps || steps.length === 0) return null;

  return (
    <ol className="reasoning-timeline" role="list">
      {steps.map((step) => {
        const isSelected = step.step === selectedStep;
        return (
          <li
            key={step.step}
            className={`timeline-item ${isSelected ? "selected" : ""}`}
          >
            <button
              type="button"
              className="timeline-button"
              onClick={() => onSelect(step.step)}
              aria-current={isSelected ? "step" : undefined}
            >
              <span className={statusDot(step.status)}>
                {step.status === "done" ? <CheckIcon width={10} height={10} /> : null}
              </span>
              <span className="timeline-content">
                <span className="timeline-step-label">
                  Step {step.step}
                  {step.tool ? <code>{step.tool}</code> : null}
                </span>
                <strong>{step.label}</strong>
                <span className="timeline-icon">
                  <StepIcon name={step.icon} width={14} height={14} />
                  <small>{step.signal?.label || "thinking"}</small>
                </span>
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
