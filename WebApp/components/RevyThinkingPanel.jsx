"use client";

import Image from "next/image";
import AgentRunPanels from "./AgentRunPanels";

export default function RevyThinkingPanel({
  className = "",
  title = "Revy is thinking",
  model = "",
  events = [],
  emptyMessage,
  runStatus = "idle",
  startedAt = null,
  runError = "",
  modelRouting = null,
  finalReasoningVerification = null,
  pricingReasoningSteps = null,
  beforePanels = null,
  children = null,
}) {
  const currentModel = modelRouting?.toolModel || model;

  return (
    <section className={className}>
      <header className="agent-run-header revy-agent-header">
        <div>
          <h2 className="agent-thinking-title">
            <span className="agent-thinking-icon">
              <Image className="revy-avatar-image" src="/Revy.png" alt="" width={34} height={34} />
            </span>
            <span>{title}</span>
            <span className="agent-thinking-dots" aria-hidden="true">
              <span />
              <span />
              <span />
            </span>
          </h2>
        </div>
        {currentModel ? (
          <span className="model-pill revy-model-pill" aria-label="Current Revy model">{currentModel}</span>
        ) : null}
      </header>

      {beforePanels}

      <AgentRunPanels
        events={events}
        emptyMessage={emptyMessage}
        runStatus={runStatus}
        startedAt={startedAt}
        runError={runError}
        modelRouting={modelRouting}
        finalReasoningVerification={finalReasoningVerification}
        pricingReasoningSteps={pricingReasoningSteps}
      />

      {children}
    </section>
  );
}
