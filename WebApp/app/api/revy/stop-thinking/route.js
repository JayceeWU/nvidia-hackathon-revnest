import { NextResponse } from "next/server";
import { getRun, stopAgentRun } from "@/lib/agentRunStore";
import { query } from "@/lib/db";
import { getRevyThinkingStatus } from "../status/route";

export const runtime = "nodejs";

async function findRunningRun(accountId, requestedRunId) {
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
    if (requestedRunId && requestedRunId !== runId) continue;
    const run = getRun(runId);
    if (run.status === "running") {
      return { runId, propertyId: row.id };
    }
  }

  return null;
}

export async function POST(request) {
  const payload = await request.json();
  const accountId = payload.accountId;
  const requestedRunId = payload.runId || null;

  if (!accountId) {
    return NextResponse.json({ error: "accountId is required" }, { status: 400 });
  }

  try {
    const running = await findRunningRun(accountId, requestedRunId);
    if (running?.runId) {
      stopAgentRun(running.runId);
      await query(
        `
          UPDATE property
          SET data = data - 'activeAgentRunId' - 'agentRunStartedAt' - 'agentRunHotelScope' || $3::jsonb,
              updated_at = now()
          WHERE account_id = $1::uuid
            AND data->>'activeAgentRunId' = $2
        `,
        [
          accountId,
          running.runId,
          JSON.stringify({
            agentRunStatus: "stopped",
            lastAgentRunId: running.runId,
            agentRunFinishedAt: new Date().toISOString(),
          }),
        ],
      );
    }

    return NextResponse.json({ stoppedRunId: running?.runId || null, status: await getRevyThinkingStatus(accountId) });
  } catch (error) {
    return NextResponse.json({ error: error.message || "Failed to stop Revy thinking" }, { status: 500 });
  }
}
