import { NextResponse } from "next/server";
import { stopAgentRun } from "@/lib/agentRunStore";

export const runtime = "nodejs";

export async function POST(_request, { params }) {
  const { runId } = await params;
  if (!runId) {
    return NextResponse.json({ error: "runId is required" }, { status: 400 });
  }
  try {
    return NextResponse.json(stopAgentRun(runId));
  } catch (error) {
    return NextResponse.json({ error: error.message || "Failed to stop run" }, { status: 500 });
  }
}
