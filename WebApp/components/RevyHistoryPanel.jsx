"use client";

import { useMemo, useState } from "react";

function formatFinalTime(value) {
  if (!value) return "No final time";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function roleLabel(role) {
  const normalized = String(role || "").trim().toLowerCase();
  if (normalized === "user") return "User";
  if (normalized === "agent" || normalized === "assistant") return "Revy";
  return normalized ? normalized[0].toUpperCase() + normalized.slice(1) : "Message";
}

export default function RevyHistoryPanel({
  conversations = [],
  selectedConversationId = "",
  onSelectConversation,
  emptyMessage = "Saved rows from revy_conversation will appear here after a Revy run writes a conversation.",
}) {
  const [internalSelectedId, setInternalSelectedId] = useState("");
  const activeSelectedId = useMemo(() => {
    const selected = selectedConversationId || internalSelectedId;
    if (selected && conversations.some((conversation) => [conversation.id, conversation.conversationId].includes(selected))) {
      return selected;
    }
    return conversations[0]?.conversationId || conversations[0]?.id || "";
  }, [conversations, internalSelectedId, selectedConversationId]);
  const selectedConversation = useMemo(
    () => conversations.find((conversation) => [conversation.id, conversation.conversationId].includes(activeSelectedId)) || conversations[0] || null,
    [activeSelectedId, conversations],
  );
  const conversationMessages = Array.isArray(selectedConversation?.messages) ? selectedConversation.messages : [];

  function selectConversation(conversationId) {
    if (onSelectConversation) {
      onSelectConversation(conversationId);
      return;
    }
    setInternalSelectedId(conversationId);
  }

  return (
    <div className="revy-history-layout revy-debug-layout">
      <aside className="revy-conversation-list" aria-label="Revy conversations">
        {conversations.length > 0 ? (
          conversations.map((conversation) => {
            const conversationId = conversation.conversationId || conversation.id;
            const isSelected = selectedConversation && [selectedConversation.id, selectedConversation.conversationId].includes(conversationId);
            return (
              <button
                key={conversation.id}
                className={isSelected ? "selected" : ""}
                type="button"
                onClick={() => selectConversation(conversationId)}
              >
                <strong>{conversation.title || "Revy conversation"}</strong>
                <span>{formatFinalTime(conversation.finalMessageAt || conversation.updatedAt)}</span>
              </button>
            );
          })
        ) : (
          <div className="empty-state">
            <strong>No history yet</strong>
            <span>{emptyMessage}</span>
          </div>
        )}
      </aside>

      <div className="revy-conversation-detail revy-debug-detail">
        {selectedConversation ? (
          <section className="revy-debug-section" aria-label="Saved conversation messages">
            <div className="revy-debug-section-heading">
              <strong>Conversation record</strong>
              <span>{conversationMessages.length} messages</span>
            </div>
            {conversationMessages.length > 0 ? (
              <div className="revy-history-messages">
                {conversationMessages.map((message, index) => {
                  const roleClass = String(message.role || "").toLowerCase() === "user" ? "user" : "agent";
                  return (
                    <article className={`chat-message ${roleClass}`} key={`${selectedConversation.id}-message-${index}`}>
                      <strong>{roleLabel(message.role)}</strong>
                      <span>{message.text || message.content || ""}</span>
                      {message.at || message.timestamp ? <small>{formatFinalTime(message.at || message.timestamp)}</small> : null}
                    </article>
                  );
                })}
              </div>
            ) : (
              <div className="empty-state compact-empty-state">
                <strong>No messages stored</strong>
                <span>This conversation only has a final summary.</span>
              </div>
            )}
          </section>
        ) : (
          <div className="empty-state">
            <strong>Select a conversation</strong>
            <span>Choose a Revy history item to inspect the conversation record.</span>
          </div>
        )}
      </div>
    </div>
  );
}
