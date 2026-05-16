import { NextResponse } from "next/server";
import { query } from "@/lib/db";
import { getLatestRunForProperty, startAgentRun } from "@/lib/agentRunStore";

export const runtime = "nodejs";

function normalizePropertyType(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "airbnb" || normalized.includes("airbnb") || normalized.includes("vacation rental") || normalized.includes("entire") || normalized.includes("private room") || normalized.includes("shared room") || normalized.includes("apartment") || normalized.includes("house") || normalized.includes("stay")) return "airbnb";
  if (normalized === "hotel" || normalized.includes("hotel") || normalized.includes("motel")) return "hotel";
  return null;
}

function optionalPositiveNumber(value, fieldName) {
  if (value === undefined || value === null || value === "") return { value: undefined };
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return { error: `${fieldName} must be a positive number` };
  return { value: parsed };
}

function optionalPositiveInteger(value, fieldName) {
  if (value === undefined || value === null || value === "") return { value: undefined };
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1) return { error: `${fieldName} must be a positive integer` };
  return { value: parsed };
}

function normalizeMyPlace(payload) {
  const value = payload.myPlace ?? payload.my_place ?? payload.airbnbUrl ?? null;
  if (value === null || value === undefined) return undefined;
  const text = String(value).trim();
  return text || undefined;
}

function normalizeConversationId(payload) {
  const value = payload.conversationId ?? payload.conversation_id ?? null;
  if (value === null || value === undefined) return undefined;
  return String(value).trim().replace(/[^a-zA-Z0-9._-]/g, "-").slice(0, 160) || undefined;
}

export async function GET(request) {
  const propertyId = request.nextUrl.searchParams.get("propertyId");

  if (!propertyId) {
    return NextResponse.json({ error: "propertyId is required" }, { status: 400 });
  }

  const run = getLatestRunForProperty(propertyId);
  if (!run) {
    return NextResponse.json({ error: "No agent run was found for this property" }, { status: 404 });
  }

  return NextResponse.json(run);
}

export async function POST(request) {
  const payload = await request.json();
  const propertyType = normalizePropertyType(payload.propertyType);
  const minPrice = optionalPositiveNumber(payload.minPrice, "minPrice");
  const maxPrice = optionalPositiveNumber(payload.maxPrice, "maxPrice");
  const pricingHorizon = optionalPositiveInteger(payload.pricingHorizon, "pricingHorizon");
  const myPlace = normalizeMyPlace(payload);
  const conversationId = normalizeConversationId(payload);

  if (!payload.accountId) {
    return NextResponse.json({ error: "accountId is required" }, { status: 400 });
  }
  if (!propertyType) {
    return NextResponse.json({ error: "propertyType must be airbnb or hotel" }, { status: 400 });
  }
  for (const parsed of [minPrice, maxPrice, pricingHorizon]) {
    if (parsed.error) return NextResponse.json({ error: parsed.error }, { status: 400 });
  }
  if (minPrice.value !== undefined && maxPrice.value !== undefined && maxPrice.value <= minPrice.value) {
    return NextResponse.json({ error: "maxPrice must be greater than minPrice" }, { status: 400 });
  }

  try {
    const run = startAgentRun({
      accountId: payload.accountId,
      propertyId: payload.propertyId || undefined,
      propertyType,
      minPrice: minPrice.value,
      maxPrice: maxPrice.value,
      pricingHorizon: pricingHorizon.value,
      myPlace,
      supplementalInfo: payload.supplementalInfo,
      conversationId,
    });
    if (payload.propertyId) {
      await query(
        `
          UPDATE property
          SET data = data || $3::jsonb,
              my_place = COALESCE($4, my_place),
              updated_at = now()
          WHERE id = $1
            AND account_id = $2::uuid
        `,
        [
          payload.propertyId,
          payload.accountId,
          JSON.stringify({
            activeAgentRunId: run.runId,
            activeRevyConversationId: run.conversationId,
            agentRunStatus: "running",
            agentRunStartedAt: run.startedAt,
            ...(myPlace ? { myPlace } : {}),
          }),
          myPlace || null,
        ]
      );
    }
    return NextResponse.json(run);
  } catch (error) {
    return NextResponse.json({ error: error.message || "Failed to start agent run" }, { status: 500 });
  }
}
