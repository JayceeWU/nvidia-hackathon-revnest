import { NextResponse } from "next/server";
import { defaultRevyState, getRevyData } from "@/lib/revyData";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET(request) {
  const accountId = request.nextUrl.searchParams.get("accountId");
  const propertyId = request.nextUrl.searchParams.get("propertyId");

  if (!accountId) {
    return NextResponse.json({ error: "accountId is required" }, { status: 400 });
  }

  try {
    return NextResponse.json(await getRevyData({ accountId, propertyId }), {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    if (error.code === "42P01" || error.code === "42703") {
      return NextResponse.json(
        {
          state: defaultRevyState(),
          conversations: [],
          revision: "missing-revy-tables",
          source: { conversations: "postgres.revy_conversation", status: "missing_table" },
        },
        { status: 500, headers: { "Cache-Control": "no-store" } },
      );
    }
    return NextResponse.json({ error: error.message || "Failed to load Revy data" }, { status: 500 });
  }
}
