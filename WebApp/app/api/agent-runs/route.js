import { NextResponse } from "next/server";
import { query } from "@/lib/db";
import { getLatestRunForProperty, getRun, startAgentRun, stopAgentRun } from "@/lib/agentRunStore";

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

function normalizeRuntimeMode(value, propertyType) {
  if (propertyType === "airbnb") return "host-openclaw";
  if (propertyType === "hotel") return "nemoclaw";
  const normalized = String(value || "").trim().toLowerCase();
  const allowed = new Set(["split-demo", "auto", "host-openclaw", "nemoclaw"]);
  if (allowed.has(normalized)) return normalized;
  return undefined;
}

function normalizeHotelScope(value, propertyType) {
  if (propertyType !== "hotel") return undefined;
  const normalized = String(value || "").trim().toLowerCase().replace(/_/g, "-");
  if (normalized === "all-room-types") return "all-room-types";
  return "room-type";
}

async function getHotelRoomTypeProperties(accountId) {
  const result = await query(
    `
      SELECT id, data
      FROM property
      WHERE account_id = $1::uuid
        AND data->>'propertyType' = 'Hotel Room Type'
      ORDER BY id
    `,
    [accountId],
  );
  return result.rows;
}

function runningRunForProperties(properties) {
  for (const row of properties) {
    const runId = row.data?.activeAgentRunId;
    if (!runId) continue;
    const run = getRun(runId);
    if (run.status === "running") return run;
  }
  return null;
}

async function getSinglePropertyForRun(accountId, propertyId) {
  const result = await query(
    `
      SELECT id, data
      FROM property
      WHERE id = $1
        AND account_id = $2::uuid
      LIMIT 1
    `,
    [propertyId, accountId],
  );
  return result.rows[0] || null;
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
  const runtimeMode = normalizeRuntimeMode(payload.runtimeMode ?? payload.runtime_mode, propertyType);
  const hotelScope = normalizeHotelScope(payload.hotelScope ?? payload.hotel_scope, propertyType);

  if (!payload.accountId) {
    return NextResponse.json({ error: "accountId is required" }, { status: 400 });
  }
  if (!propertyType) {
    return NextResponse.json({ error: "propertyType must be airbnb or hotel" }, { status: 400 });
  }
  if ((payload.hotelScope || payload.hotel_scope) && propertyType !== "hotel") {
    return NextResponse.json({ error: "hotelScope is only valid for hotel runs" }, { status: 400 });
  }
  for (const parsed of [minPrice, maxPrice, pricingHorizon]) {
    if (parsed.error) return NextResponse.json({ error: parsed.error }, { status: 400 });
  }
  if (minPrice.value !== undefined && maxPrice.value !== undefined && maxPrice.value <= minPrice.value) {
    return NextResponse.json({ error: "maxPrice must be greater than minPrice" }, { status: 400 });
  }

  try {
    let batchPropertyIds = [];
    let singleProperty = null;
    if (hotelScope === "all-room-types") {
      const roomTypeProperties = await getHotelRoomTypeProperties(payload.accountId);
      if (roomTypeProperties.length === 0) {
        return NextResponse.json({ error: "No hotel room type properties were found for this account" }, { status: 400 });
      }
      const runningRun = runningRunForProperties(roomTypeProperties);
      if (runningRun) {
        return NextResponse.json({ error: "A Revy run is already active for this hotel account", run: runningRun }, { status: 409 });
      }
      batchPropertyIds = roomTypeProperties.map((row) => row.id);
    } else if (payload.propertyId) {
      singleProperty = await getSinglePropertyForRun(payload.accountId, payload.propertyId);
      if (!singleProperty) {
        return NextResponse.json(
          { error: `Property ${payload.propertyId} was not found for this account. Save the property before starting Revy.` },
          { status: 404 },
        );
      }
      const runningRun = runningRunForProperties([singleProperty]);
      if (runningRun) {
        return NextResponse.json({ error: "A Revy run is already active for this property", run: runningRun }, { status: 409 });
      }
    }

    const run = startAgentRun({
      accountId: payload.accountId,
      propertyId: payload.propertyId || undefined,
      propertyIds: batchPropertyIds,
      propertyType,
      hotelScope,
      minPrice: minPrice.value,
      maxPrice: maxPrice.value,
      pricingHorizon: pricingHorizon.value,
      myPlace,
      supplementalInfo: payload.supplementalInfo,
      conversationId,
      runtimeMode,
    });
    if (hotelScope === "all-room-types") {
      await query(
        `
          UPDATE property
          SET data = data - 'agentRunError' - 'pricingOutputError' - 'agentRunStopReason' - 'agentRunFinishedAt' || $3::jsonb,
              updated_at = now()
          WHERE account_id = $1::uuid
            AND id = ANY($2::text[])
        `,
        [
          payload.accountId,
          batchPropertyIds,
          JSON.stringify({
            activeAgentRunId: run.runId,
            activeRevyConversationId: run.conversationId,
            agentRunStatus: "running",
            agentRunStartedAt: run.startedAt,
            agentRunRuntimeMode: run.runtimeMode,
            agentRunHotelScope: run.hotelScope,
          }),
        ],
      );
    } else if (payload.propertyId) {
      const updateResult = await query(
        `
          UPDATE property
          SET data = data - 'agentRunError' - 'pricingOutputError' - 'agentRunStopReason' - 'agentRunFinishedAt' || $3::jsonb,
              my_place = COALESCE($4, my_place),
              updated_at = now()
          WHERE id = $1
            AND account_id = $2::uuid
          RETURNING id
        `,
        [
          payload.propertyId,
          payload.accountId,
          JSON.stringify({
            activeAgentRunId: run.runId,
            activeRevyConversationId: run.conversationId,
            agentRunStatus: "running",
            agentRunStartedAt: run.startedAt,
            agentRunRuntimeMode: run.runtimeMode,
            ...(run.hotelScope ? { agentRunHotelScope: run.hotelScope } : {}),
            ...(myPlace ? { myPlace } : {}),
          }),
          myPlace || null,
        ]
      );
      if (updateResult.rowCount === 0) {
        stopAgentRun(run.runId);
        return NextResponse.json(
          { error: `Property ${payload.propertyId} was not found for this account. Revy run was not started.` },
          { status: 404 },
        );
      }
    }
    return NextResponse.json(run);
  } catch (error) {
    return NextResponse.json({ error: error.message || "Failed to start agent run" }, { status: 500 });
  }
}
