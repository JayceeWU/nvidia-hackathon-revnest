import { NextResponse } from "next/server";
import { getRun, isHostRunProcessAlive } from "@/lib/agentRunStore";
import { query } from "@/lib/db";
import { getPricingOutputState, missingPricingOutputError } from "@/lib/pricingOutputVerifier";

export const runtime = "nodejs";

const TERMINAL_RUN_STATUSES = new Set(["completed", "failed", "stopped"]);

function finalEventTimestamp(run) {
  const event = [...(run.events || [])]
    .reverse()
    .find((item) => item.stage === "agent_finish" || item.status === "failed" || item.status === "stopped");
  return event?.timestamp || new Date().toISOString();
}

async function finalizePropertyRun({ accountId, propertyId, runId, run }) {
  if (!TERMINAL_RUN_STATUSES.has(run.status)) return;
  const outputState = await getPricingOutputState({ runId, run, propertyId, accountId });
  const outputError = run.status === "completed" && !outputState.hasCompletePrices
    ? missingPricingOutputError(runId, outputState.missingPropertyIds.length > 0 ? outputState.missingPropertyIds : [propertyId])
    : null;
  const finalStatus = outputError ? "failed" : run.status;
  const finishedAt = finalEventTimestamp(run);

  await query(
    `
      UPDATE property
      SET data = data - 'activeAgentRunId' - 'agentRunStartedAt' - 'agentRunHotelScope' - 'agentRunStopReason' - 'agentRunError' - 'pricingOutputError' || $4::jsonb,
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
        agentRunStatus: finalStatus,
        agentRunFinishedAt: finishedAt,
        ...(outputError ? { agentRunError: outputError, pricingOutputError: outputError } : {}),
        ...(finalStatus === "completed" ? { status: "active", activatedAt: finishedAt } : {}),
        ...(run.conversationId ? { lastRevyConversationId: run.conversationId } : {}),
      }),
    ],
  );

  return { status: finalStatus, error: outputError };
}

async function markStaleRunFinished({ accountId, propertyId, runId }) {
  const outputState = await getPricingOutputState({ runId, propertyId, accountId });
  const hasPrices = outputState.hasCompletePrices;
  const status = hasPrices ? "completed" : "failed";
  const error = hasPrices ? null : missingPricingOutputError(runId, outputState.missingPropertyIds.length > 0 ? outputState.missingPropertyIds : [propertyId]);
  const finishedAt = new Date().toISOString();

  await query(
    `
      UPDATE property
      SET data = data - 'activeAgentRunId' - 'agentRunStartedAt' - 'agentRunHotelScope' - 'agentRunStopReason' - 'agentRunError' - 'pricingOutputError' || $4::jsonb,
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
        agentRunStatus: status,
        agentRunFinishedAt: finishedAt,
        agentRunStopReason: "stale_no_host_process",
        ...(error ? { agentRunError: error, pricingOutputError: error } : { status: "active", activatedAt: finishedAt }),
      }),
    ],
  );

  return { status, error, finishedAt };
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
    if (run.status === "running" || isHostRunProcessAlive(runId)) {
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
    if (row.data?.agentRunStatus === "running") {
      const finished = await markStaleRunFinished({ accountId, propertyId: row.id, runId });
      return {
        isThinking: false,
        runId,
        propertyId: row.id,
        conversationId: row.data?.activeRevyConversationId || null,
        status: finished.status,
        error: finished.error,
        startedAt: row.data?.agentRunStartedAt || null,
        updatedAt: new Date().toISOString(),
      };
    }
    const finalized = await finalizePropertyRun({ accountId, propertyId: row.id, runId, run });
    if (finalized?.error) {
      return {
        isThinking: false,
        runId,
        propertyId: row.id,
        conversationId: row.data?.activeRevyConversationId || null,
        status: finalized.status,
        error: finalized.error,
        startedAt: row.data?.agentRunStartedAt || null,
        updatedAt: new Date().toISOString(),
      };
    }
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
