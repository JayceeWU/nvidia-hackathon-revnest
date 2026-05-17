import { query } from "@/lib/db";

const DEFAULT_MODEL = "qwen tool calls + Nemotron reasoning";

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
  const priceCalendar = arrayFrom(data.priceCalendar || data.price_calendar);
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
    traceEvents: [],
    reasoningSteps: [],
  };
}

function buildRevision(stateRow, conversationRows) {
  const stateUpdatedAt = isoValue(stateRow?.updatedAt) || "no-state";
  const conversationRevision = conversationRows
    .map((row) => `${row.id}:${isoValue(row.updatedAt) || ""}:${isoValue(row.finalMessageAt) || ""}`)
    .join("|");
  return `${stateUpdatedAt}:${conversationRevision}`;
}

export async function getRevyData({ accountId, propertyId = null }) {
  const [stateResult, conversationResult] = await Promise.all([
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
  ]);

  const stateRow = stateResult.rows[0] || null;
  const conversations = conversationResult.rows.map(formatRevyConversation);
  return {
    state: stateRow?.data || defaultRevyState(),
    conversations,
    revision: buildRevision(stateRow, conversationResult.rows),
    source: {
      conversations: "postgres.revy_conversation",
      state: "postgres.revy_state",
    },
    counts: {
      conversations: conversations.length,
      reasoningSteps: 0,
    },
  };
}
