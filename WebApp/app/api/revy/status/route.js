import { NextResponse } from "next/server";
import { getRun } from "@/lib/agentRunStore";
import { query } from "@/lib/db";

export const runtime = "nodejs";

const TERMINAL_RUN_STATUSES = new Set(["completed", "failed", "stopped"]);

function finalEventTimestamp(run) {
  const event = [...(run.events || [])]
    .reverse()
    .find((item) => item.stage === "agent_finish" || TERMINAL_RUN_STATUSES.has(item.status));
  return event?.timestamp || new Date().toISOString();
}

async function finalizePropertyRun({ accountId, propertyId, runId, run }) {
  if (!TERMINAL_RUN_STATUSES.has(run.status)) return;

  await query(
    `
      UPDATE property
      SET data = data - 'activeAgentRunId' - 'agentRunStartedAt' - 'agentRunHotelScope' || $4::jsonb,
          updated_at = now()
      WHERE id = $1
        AND account_id = $2::uuid
        AND data->>'activeAgentRunId' = $3
    `,
    [
      propertyId,
      accountId,
      runId,
      JSON.stringify({
        lastAgentRunId: runId,
        agentRunStatus: run.status,
        agentRunFinishedAt: finalEventTimestamp(run),
        ...(run.conversationId ? { lastRevyConversationId: run.conversationId } : {}),
      }),
    ],
  );
}

export async function getRevyThinkingStatus(accountId) {
  const propertyResult = await query(
    `
      SELECT id, data
      FROM property
      WHERE account_id = $1::uuid
      ORDER BY updated_at DESC, created_at DESC, id
    `,
    [accountId],
  );

  for (const row of propertyResult.rows) {
    const runId = row.data?.activeAgentRunId;
    if (!runId) continue;
    const run = getRun(runId);
    if (run.status === "running") {
      return {
        isThinking: true,
        runId,
        propertyId: row.id,
        conversationId: row.data?.activeRevyConversationId || null,
        status: "running",
        startedAt: run.startedAt || row.data?.agentRunStartedAt || null,
        updatedAt: new Date().toISOString(),
      };
    }
    await finalizePropertyRun({ accountId, propertyId: row.id, runId, run });
  }

  return {
    isThinking: false,
    runId: null,
    propertyId: null,
    conversationId: null,
    status: "idle",
    startedAt: null,
    updatedAt: new Date().toISOString(),
  };
}

export async function GET(request) {
  const accountId = request.nextUrl.searchParams.get("accountId");
  if (!accountId) {
    return NextResponse.json({ error: "accountId is required" }, { status: 400 });
  }

  try {
    return NextResponse.json(await getRevyThinkingStatus(accountId));
  } catch (error) {
    return NextResponse.json({ error: error.message || "Failed to load Revy status" }, { status: 500 });
  }
}
