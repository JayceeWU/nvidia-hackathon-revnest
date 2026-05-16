import { NextResponse } from "next/server";
import { getRun } from "@/lib/agentRunStore";

export const runtime = "nodejs";

export async function GET(_request, { params }) {
  const { runId } = await params;
  if (!runId) {
    return NextResponse.json({ error: "runId is required" }, { status: 400 });
  }
  return NextResponse.json(getRun(runId));
}
