import { NextResponse } from "next/server";
import { pool } from "@/lib/db";
import { stopAgentRunsForProperty } from "@/lib/agentRunStore";

export const runtime = "nodejs";

const PROFILE_FIELDS = [
  { column: "room_count", jsonKey: "roomCount", keys: ["roomCount", "room_count"], type: "integer" },
  { column: "capacity", jsonKey: "capacity", keys: ["capacity"], type: "integer" },
  { column: "zip_code", jsonKey: "zipCode", keys: ["zipCode", "zip_code"], type: "text" },
  { column: "county", jsonKey: "county", keys: ["county"], type: "text" },
  { column: "state", jsonKey: "state", keys: ["state"], type: "text" },
  { column: "city", jsonKey: "city", keys: ["city"], type: "text" },
  { column: "bed", jsonKey: "bed", keys: ["bed", "beds"], type: "text" },
  { column: "bath", jsonKey: "bath", keys: ["bath", "bathroom"], type: "text" },
  { column: "other_info", jsonKey: "otherInfo", keys: ["otherInfo", "other_info"], type: "text" },
];

function hasOwn(object, key) {
  return Object.prototype.hasOwnProperty.call(object, key);
}

function hasAny(data, keys) {
  return keys.some((key) => hasOwn(data, key));
}

function firstPatchValue(data, keys) {
  for (const key of keys) {
    if (hasOwn(data, key)) return data[key];
  }
  return undefined;
}

function normalizeOptionalText(value) {
  if (value === undefined || value === null) return null;
  const text = String(value).trim();
  return text || null;
}

function parseOptionalNonNegativeInteger(value, fieldName) {
  if (value === undefined || value === null || value === "") return { value: null };
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 0) return { error: `${fieldName} must be a non-negative integer` };
  return { value: parsed };
}

function hasMyPlaceField(data) {
  return hasAny(data, ["myPlace", "my_place", "airbnbUrl"]);
}

function resolveMyPlace(data) {
  return normalizeOptionalText(data.myPlace ?? data.my_place ?? data.airbnbUrl ?? null);
}

function resolveProfilePatch(data) {
  const updates = [];
  const patchData = { ...data };

  for (const field of PROFILE_FIELDS) {
    if (!hasAny(data, field.keys)) continue;
    const raw = firstPatchValue(data, field.keys);
    const parsed =
      field.type === "integer"
        ? parseOptionalNonNegativeInteger(raw, field.jsonKey)
        : { value: normalizeOptionalText(raw) };
    if (parsed.error) return { error: parsed.error };

    updates.push({ ...field, value: parsed.value });
    patchData[field.jsonKey] = parsed.value;
    if (field.column === "bed" && !hasOwn(patchData, "beds") && parsed.value) patchData.beds = parsed.value;
    if (field.column === "bath" && !hasOwn(patchData, "bathroom") && parsed.value) patchData.bathroom = parsed.value;
  }

  return { updates, patchData };
}

function propertyResponse(row) {
  return {
    ...row.data,
    id: row.id,
    myPlace: row.my_place || row.data.myPlace || row.data.airbnbUrl || null,
    roomCount: row.room_count ?? row.data.roomCount ?? null,
    capacity: row.capacity ?? row.data.capacity ?? null,
    zipCode: row.zip_code || row.data.zipCode || null,
    county: row.county || row.data.county || null,
    state: row.state || row.data.state || null,
    city: row.city || row.data.city || null,
    bed: row.bed || row.data.bed || row.data.beds || null,
    bath: row.bath || row.data.bath || row.data.bathroom || null,
    otherInfo: row.other_info || row.data.otherInfo || row.data.other_info || null,
  };
}

export async function DELETE(request, { params }) {
  const { propertyId } = await params;
  const accountId = request.nextUrl.searchParams.get("accountId");

  if (!propertyId || !accountId) {
    return NextResponse.json({ error: "propertyId and accountId are required" }, { status: 400 });
  }

  const client = await pool.connect();
  try {
    const stoppedRuns = stopAgentRunsForProperty(propertyId);
    await client.query("BEGIN");
    await client.query("DELETE FROM property_price WHERE property_id = $1", [propertyId]);
    const result = await client.query(
      `
        DELETE FROM property
        WHERE id = $1
          AND account_id = $2::uuid
      `,
      [propertyId, accountId]
    );
    await client.query("COMMIT");
    return NextResponse.json({ ok: true, deleted: result.rowCount, stoppedRuns });
  } catch (error) {
    await client.query("ROLLBACK");
    return NextResponse.json({ error: error.message || "Failed to delete property" }, { status: 500 });
  } finally {
    client.release();
  }
}

export async function PATCH(request, { params }) {
  const { propertyId } = await params;
  const { accountId, data } = await request.json();

  if (!propertyId || !accountId || !data || typeof data !== "object") {
    return NextResponse.json({ error: "propertyId, accountId, and data are required" }, { status: 400 });
  }

  const shouldUpdateMyPlace = hasMyPlaceField(data);
  const myPlace = shouldUpdateMyPlace ? resolveMyPlace(data) : null;
  const profilePatch = resolveProfilePatch(data);
  if (profilePatch.error) {
    return NextResponse.json({ error: profilePatch.error }, { status: 400 });
  }
  const patchData = shouldUpdateMyPlace ? { ...profilePatch.patchData, myPlace } : profilePatch.patchData;

  const values = [propertyId, accountId, JSON.stringify(patchData)];
  const assignments = ["data = data || $3::jsonb"];
  if (shouldUpdateMyPlace) {
    values.push(myPlace);
    assignments.push(`my_place = $${values.length}`);
  }
  for (const update of profilePatch.updates) {
    values.push(update.value);
    assignments.push(`${update.column} = $${values.length}`);
  }
  assignments.push("updated_at = now()");

  try {
    const result = await pool.query(
      `
        UPDATE property
        SET ${assignments.join(",\n            ")}
        WHERE id = $1
          AND account_id = $2::uuid
        RETURNING id, my_place, room_count, capacity, zip_code, county, state, city, bed, bath, other_info, data
      `,
      values
    );

    if (!result.rows[0]) {
      return NextResponse.json({ error: "Property was not found" }, { status: 404 });
    }

    return NextResponse.json({ property: propertyResponse(result.rows[0]) });
  } catch (error) {
    return NextResponse.json({ error: error.message || "Failed to update property" }, { status: 500 });
  }
}
