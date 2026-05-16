import { NextResponse } from "next/server";
import { getRun } from "@/lib/agentRunStore";
import { query } from "@/lib/db";

export const runtime = "nodejs";

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
