"use client";

import RevyHistoryPanel from "./RevyHistoryPanel";
import RevyThinkingPanel from "./RevyThinkingPanel";

const terminalRunStatuses = new Set(["completed", "failed", "stopped", "idle"]);

export default function RevyWorkspacePanel({
  revyState,
  events = [],
  thinkingStatus,
  queuedSteer = null,
  chatInput = "",
  onChatInputChange,
  onChatSubmit,
  isThinking = false,
  isStarting = false,
  isStopping = false,
  activeRunId = "",
  onStopThinking,
  conversations = [],
  selectedConversationId = "",
  onSelectConversation,
}) {
  const runStatus = thinkingStatus?.status || revyState?.status || "idle";
  const hasActiveRun = Boolean(activeRunId);
  const isActivelyThinking = hasActiveRun || (isThinking && !terminalRunStatuses.has(runStatus));
  const displayedRunStatus = hasActiveRun && terminalRunStatuses.has(runStatus) ? "running" : runStatus;
  const actionLabel = isActivelyThinking ? (isStopping ? "Stopping..." : "Stop thinking") : isStarting ? "Starting..." : "Send";
  const isInputDisabled = isStarting && !isActivelyThinking;
  const isActionDisabled = isActivelyThinking ? isStopping : !chatInput.trim() || isStarting;

  return (
    <section className="revy-page">
      <RevyThinkingPanel
        className="airbnb-property-card revy-current-card"
        title="Revy is thinking"
        model={revyState?.model}
        events={events}
        emptyMessage="Revy is ready for the next pricing signal."
        runStatus={displayedRunStatus}
        startedAt={thinkingStatus?.startedAt}
        runError={thinkingStatus?.error}
        modelRouting={thinkingStatus?.modelRouting}
        finalReasoningVerification={thinkingStatus?.finalReasoningVerification}
        pricingReasoningSteps={thinkingStatus?.pricingReasoningSteps}
      >
        <section className="revy-chat-panel compact-revy-chat-panel" aria-label="Talk with Revy">
          {queuedSteer ? (
            <div className="queued-steer-note" role="status">
              <strong>Queued steer</strong>
              <span>{queuedSteer.text}</span>
            </div>
          ) : null}
          <form className="chat-input-row" onSubmit={onChatSubmit}>
            <input
              value={chatInput}
              onChange={(event) => onChatInputChange(event.target.value)}
              placeholder={isActivelyThinking ? "Type a steer and press Enter" : "Ask Revy"}
              aria-label="Message Revy"
              disabled={isInputDisabled}
            />
            <button
              type={isActivelyThinking ? "button" : "submit"}
              className={isActivelyThinking ? "stop-thinking-button" : ""}
              disabled={isActionDisabled}
              onClick={isActivelyThinking ? onStopThinking : undefined}
            >
              {actionLabel}
            </button>
          </form>
        </section>
      </RevyThinkingPanel>

      <section className="airbnb-property-card revy-history-card">
        <div className="airbnb-section-heading">
          <h2>Revy History</h2>
        </div>
        <RevyHistoryPanel
          conversations={conversations}
          selectedConversationId={selectedConversationId}
          onSelectConversation={onSelectConversation}
        />
      </section>
    </section>
  );
}
