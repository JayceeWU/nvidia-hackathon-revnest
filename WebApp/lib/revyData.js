import { query } from "@/lib/db";

const DEFAULT_MODEL = "nemotron3:33b";

export function defaultRevyState() {
  return {
    status: "idle",
    model: DEFAULT_MODEL,
    headline: "Reviewing current pricing signals and waiting for the next host question.",
    updatedAt: "May 15, 2026 7:20 PM",
    events: [],
    messages: [
      {
        role: "agent",
        text: "I am watching your pricing context and ready to explain the next recommendation.",
        at: "May 15, 2026 7:20 PM",
      },
    ],
  };
}

function arrayFrom(value) {
  return Array.isArray(value) ? value : [];
}

function objectFrom(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : null;
}

function isoValue(value) {
  if (!value) return null;
  if (value instanceof Date) return value.toISOString();
  return value;
}

function messagesFromConversationData(data, row) {
  const messages = arrayFrom(data.messages);
  if (messages.length > 0) return messages;

  const fallbackMessages = [];
  if (data.userMessage || data.user_message) {
    fallbackMessages.push({
      role: "user",
      text: data.userMessage || data.user_message,
      at: isoValue(row.finalMessageAt || row.updatedAt || row.createdAt),
    });
  }
  const finalText = data.finalMessage || data.final_message || data.summary;
  if (finalText) {
    fallbackMessages.push({
      role: "agent",
      text: finalText,
      at: isoValue(row.finalMessageAt || row.updatedAt || row.createdAt),
    });
  }
  return fallbackMessages;
}

export function formatRevyConversation(row) {
  const data = objectFrom(row.data) || {};
  const conversationId = data.conversationId || row.id;
  const traceEvents = arrayFrom(data.traceEvents || data.events);
  const priceCalendar = arrayFrom(data.priceCalendar || data.price_calendar);
  const reasoningSteps = arrayFrom(row.reasoningSteps);
  return {
    id: row.id,
    conversationId,
    title: row.title,
    finalMessageAt: isoValue(row.finalMessageAt),
    updatedAt: isoValue(row.updatedAt),
    createdAt: isoValue(row.createdAt),
    propertyId: row.propertyId || data.propertyId || null,
    summary: data.summary || "",
    messages: messagesFromConversationData(data, row),
    runId: data.runId || null,
    source: data.source || null,
    tool: data.tool || null,
    priceDateRange: objectFrom(data.priceDateRange) || null,
    revparSummary: objectFrom(data.revparSummary) || null,
    priceCalendar,
    traceEvents,
    reasoningSteps,
  };
}

function formatReasoningStep(row) {
  const data = objectFrom(row.data) || {};
  return {
    id: row.id,
    runId: data.runId || null,
    propertyId: data.propertyId || null,
    stage: data.stage || null,
    substage: data.substage || null,
    groupKey: data.groupKey || null,
    summary: data.summary || "",
    facts: arrayFrom(data.facts),
    metrics: objectFrom(data.metrics) || {},
    tool: data.tool || null,
    sources: arrayFrom(data.sources),
    confidence: data.confidence || null,
    timestamp: isoValue(data.timestamp || row.createdAt),
    updatedAt: isoValue(row.updatedAt),
  };
}

function reasoningStepsForConversation(conversationRow, reasoningSteps) {
  const data = objectFrom(conversationRow.data) || {};
  const runId = data.runId || null;
  const propertyId = conversationRow.propertyId || data.propertyId || null;
  const matched = reasoningSteps.filter((step) => {
    if (runId && step.runId === runId) return true;
    if (!runId && propertyId && step.propertyId === propertyId) return true;
    return false;
  });
  return matched.sort((left, right) => {
    const leftTime = left.timestamp || "";
    const rightTime = right.timestamp || "";
    if (leftTime !== rightTime) return leftTime.localeCompare(rightTime);
    return String(left.id).localeCompare(String(right.id));
  });
}

function buildRevision(stateRow, conversationRows, reasoningRows) {
  const stateUpdatedAt = isoValue(stateRow?.updatedAt) || "no-state";
  const conversationRevision = conversationRows
    .map((row) => `${row.id}:${isoValue(row.updatedAt) || ""}:${isoValue(row.finalMessageAt) || ""}`)
    .join("|");
  const reasoningRevision = reasoningRows
    .map((row) => `${row.id}:${isoValue(row.updatedAt) || ""}`)
    .join("|");
  return `${stateUpdatedAt}:${conversationRevision}:${reasoningRevision}`;
}

export async function getRevyData({ accountId, propertyId = null }) {
  const [stateResult, conversationResult, reasoningResult] = await Promise.all([
    query(
      `
        SELECT data, updated_at AS "updatedAt"
        FROM revy_state
        WHERE account_id = $1::uuid
        LIMIT 1
      `,
      [accountId],
    ),
    query(
      `
        SELECT
          id,
          title,
          property_id AS "propertyId",
          final_message_at AS "finalMessageAt",
          data,
          created_at AS "createdAt",
          updated_at AS "updatedAt"
        FROM revy_conversation
        WHERE account_id = $1::uuid
          AND ($2::text IS NULL OR property_id = $2)
        ORDER BY final_message_at DESC, updated_at DESC, id
      `,
      [accountId, propertyId || null],
    ),
    query(
      `
        SELECT
          id,
          data,
          created_at AS "createdAt",
          updated_at AS "updatedAt"
        FROM pricing_record
        WHERE account_id = $1::uuid
          AND record_type = 'reasoning_step'
          AND ($2::text IS NULL OR data->>'propertyId' = $2)
        ORDER BY COALESCE(data->>'timestamp', created_at::text), created_at, id
      `,
      [accountId, propertyId || null],
    ),
  ]);

  const stateRow = stateResult.rows[0] || null;
  const reasoningSteps = reasoningResult.rows.map(formatReasoningStep);
  const conversations = conversationResult.rows.map((row) =>
    formatRevyConversation({
      ...row,
      reasoningSteps: reasoningStepsForConversation(row, reasoningSteps),
    }),
  );
  return {
    state: stateRow?.data || defaultRevyState(),
    conversations,
    revision: buildRevision(stateRow, conversationResult.rows, reasoningResult.rows),
    source: {
      conversations: "postgres.revy_conversation",
      reasoningSteps: "postgres.pricing_record",
      state: "postgres.revy_state",
    },
    counts: {
      conversations: conversations.length,
      reasoningSteps: reasoningSteps.length,
    },
  };
}
