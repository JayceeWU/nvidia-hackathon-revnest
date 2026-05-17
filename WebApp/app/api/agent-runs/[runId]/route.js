import { NextResponse } from "next/server";
import { getRun, isHostRunProcessAlive } from "@/lib/agentRunStore";
import { query } from "@/lib/db";
import { decorateRunWithPricingOutput, getPricingOutputState, missingPricingOutputError } from "@/lib/pricingOutputVerifier";

export const runtime = "nodejs";

const TERMINAL_RUN_STATUSES = new Set(["completed", "failed", "stopped"]);

function finalEventTimestamp(run) {
  const event = [...(run.events || [])]
    .reverse()
    .find((item) => item.stage === "agent_finish" || item.status === "failed" || item.status === "stopped");
  return event?.timestamp || new Date().toISOString();
}

async function activePropertiesForRun(runId) {
  const result = await query(
    `
      SELECT id, account_id::text AS "accountId", data
      FROM property
      WHERE data->>'activeAgentRunId' = $1
      ORDER BY updated_at DESC, id
    `,
    [runId],
  );
  return result.rows;
}

async function finishActivePropertyRun({ row, run, staleNoHostProcess }) {
  const outputState = await getPricingOutputState({
    runId: run.runId,
    run,
    propertyId: row.id,
    accountId: row.accountId,
  });
  const hasPrices = outputState.hasCompletePrices;
  const outputError = hasPrices ? null : missingPricingOutputError(
    run.runId,
    outputState.missingPropertyIds.length > 0 ? outputState.missingPropertyIds : [row.id],
  );
  const finalStatus = hasPrices && staleNoHostProcess
    ? "completed"
    : outputError
      ? "failed"
      : run.status;
  const finalError = finalStatus === "completed" ? null : (run.error || outputError || "Revy run ended before suggested prices were saved.");
  const finishedAt = staleNoHostProcess ? new Date().toISOString() : finalEventTimestamp(run);

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
      row.id,
      row.accountId,
      run.runId,
      JSON.stringify({
        lastAgentRunId: run.runId,
        agentRunStatus: finalStatus,
        agentRunFinishedAt: finishedAt,
        ...(staleNoHostProcess ? { agentRunStopReason: "stale_no_host_process" } : {}),
        ...(run.conversationId ? { lastRevyConversationId: run.conversationId } : {}),
        ...(finalError ? { agentRunError: finalError, pricingOutputError: finalError } : { status: "active", activatedAt: finishedAt }),
      }),
    ],
  );

  return { status: finalStatus, error: finalError };
}

async function syncRunToActiveProperties(run, hostProcessAlive) {
  const staleNoHostProcess = run.status === "unknown" && !hostProcessAlive;
  if (!staleNoHostProcess && !TERMINAL_RUN_STATUSES.has(run.status)) return run;

  const activeRows = await activePropertiesForRun(run.runId);
  if (activeRows.length === 0) return run;

  let nextStatus = run.status;
  let nextError = run.error || null;
  for (const row of activeRows) {
    const result = await finishActivePropertyRun({ row, run, staleNoHostProcess });
    if (result.status === "failed") nextStatus = "failed";
    else if (nextStatus === "unknown") nextStatus = result.status;
    if (result.error) nextError = result.error;
  }

  return {
    ...run,
    status: nextStatus,
    error: nextError,
  };
}

export async function GET(_request, { params }) {
  const { runId } = await params;
  if (!runId) {
    return NextResponse.json({ error: "runId is required" }, { status: 400 });
  }
  const hostProcessAlive = isHostRunProcessAlive(runId);
  const run = await syncRunToActiveProperties(getRun(runId), hostProcessAlive);
  return NextResponse.json(await decorateRunWithPricingOutput(run, { hostProcessAlive }));
}
