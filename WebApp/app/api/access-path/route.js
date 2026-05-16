import { NextResponse } from "next/server";
import { getAccessPathInfo } from "@/lib/accessPath";

export const runtime = "nodejs";

export async function GET() {
  return NextResponse.json(getAccessPathInfo());
}
