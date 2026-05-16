import { NextResponse } from "next/server";
import { query } from "@/lib/db";

export const runtime = "nodejs";

const maxEditableDateSql = "CURRENT_DATE + INTERVAL '2 years' - INTERVAL '1 day'";

function parseDateParam(value, label) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw Object.assign(new Error(`${label} must be YYYY-MM-DD`), { status: 400 });
  }
  return value;
}

function parseRoomTypeIds(value) {
  if (!value) {
    return null;
  }
  const ids = value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  return ids.length > 0 ? ids : null;
}

function toDollars(cents) {
  return (Number(cents) / 100).toFixed(2);
}

function requireAgentToken(request) {
  const configuredToken = process.env.MOCKHOTEL_AGENT_TOKEN;
  if (!configuredToken) {
    throw Object.assign(new Error("MockHotel agent token is not configured"), { status: 503 });
  }

  const header = request.headers.get("authorization") || "";
  const [scheme, token] = header.split(/\s+/, 2);
  if (scheme !== "Bearer" || token !== configuredToken) {
    throw Object.assign(new Error("Authentication required"), { status: 401 });
  }
}

export async function GET(request) {
  try {
    requireAgentToken(request);

    const params = request.nextUrl.searchParams;
    const start = parseDateParam(params.get("start"), "start");
    const end = parseDateParam(params.get("end"), "end");
    const roomTypeIds = parseRoomTypeIds(params.get("roomTypeIds"));

    const result = await query(
      `
        SELECT
          room_type.id AS room_type_id,
          room_type.name,
          room_type.room_type,
          room_type.room_count,
          room_type.capacity,
          room_type.bed,
          room_type.bath,
          room_type.min_price_cents,
          room_type.max_price_cents,
          room_type.base_price_cents,
          room_type.source,
          room_type.data,
          room_type_price.stay_date,
          room_type_price.price_cents
        FROM room_type
        JOIN room_type_price ON room_type_price.room_type_id = room_type.id
        WHERE room_type_price.stay_date BETWEEN $1::date AND $2::date
          AND room_type_price.stay_date >= CURRENT_DATE
          AND room_type_price.stay_date <= ${maxEditableDateSql}
          AND ($3::text[] IS NULL OR room_type.id = ANY($3::text[]))
        ORDER BY room_type.name, room_type_price.stay_date
      `,
      [start, end, roomTypeIds]
    );

    const roomTypes = new Map();
    for (const row of result.rows) {
      if (!roomTypes.has(row.room_type_id)) {
        roomTypes.set(row.room_type_id, {
          id: row.room_type_id,
          name: row.name,
          roomType: row.room_type,
          roomCount: Number(row.room_count),
          capacity: row.capacity === null ? null : Number(row.capacity),
          bed: row.bed,
          bath: row.bath,
          minPrice: toDollars(row.min_price_cents),
          maxPrice: toDollars(row.max_price_cents),
          basePrice: toDollars(row.base_price_cents),
          source: row.source,
          data: row.data || {},
          prices: {}
        });
      }
      const roomType = roomTypes.get(row.room_type_id);
      const date = row.stay_date.toISOString().slice(0, 10);
      roomType.prices[date] = toDollars(row.price_cents);
    }

    return NextResponse.json({
      start,
      end,
      currency: "USD",
      moneyUnit: "dollars",
      roomTypes: Array.from(roomTypes.values())
    });
  } catch (error) {
    return NextResponse.json(
      { error: error.message || "Failed to load current prices" },
      { status: error.status || 500 }
    );
  }
}
