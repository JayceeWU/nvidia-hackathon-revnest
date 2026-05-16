import { NextResponse } from "next/server";
import { query } from "@/lib/db";
import { requireSession } from "@/lib/session";

const maxEditableDateSql = "CURRENT_DATE + INTERVAL '2 years' - INTERVAL '1 day'";

function parseDateParam(value, label) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw Object.assign(new Error(`${label} must be YYYY-MM-DD`), { status: 400 });
  }
  return value;
}

function toDollars(cents) {
  return Number(cents) / 100;
}

export async function GET(request) {
  try {
    await requireSession();
    const params = request.nextUrl.searchParams;
    const start = parseDateParam(params.get("start"), "start");
    const end = parseDateParam(params.get("end"), "end");

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
          room_type_price.stay_date,
          room_type_price.price_cents
        FROM room_type
        JOIN room_type_price ON room_type_price.room_type_id = room_type.id
        WHERE room_type_price.stay_date BETWEEN $1::date AND $2::date
          AND room_type_price.stay_date >= CURRENT_DATE
          AND room_type_price.stay_date <= ${maxEditableDateSql}
        ORDER BY room_type.name, room_type_price.stay_date
      `,
      [start, end]
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
          minPrice: toDollars(row.min_price_cents).toFixed(2),
          maxPrice: toDollars(row.max_price_cents).toFixed(2),
          basePrice: toDollars(row.base_price_cents).toFixed(2),
          prices: {}
        });
      }
      const roomType = roomTypes.get(row.room_type_id);
      const date = row.stay_date.toISOString().slice(0, 10);
      roomType.prices[date] = toDollars(row.price_cents).toFixed(2);
    }

    return NextResponse.json({ roomTypes: Array.from(roomTypes.values()) });
  } catch (error) {
    return NextResponse.json(
      { error: error.message || "Failed to load prices" },
      { status: error.status || 500 }
    );
  }
}

export async function POST(request) {
  try {
    const session = await requireSession();
    const { updates } = await request.json();

    if (!Array.isArray(updates) || updates.length === 0) {
      return NextResponse.json({ error: "No price updates were provided" }, { status: 400 });
    }

    if (updates.length > 1500) {
      return NextResponse.json({ error: "Too many price updates in one request" }, { status: 400 });
    }

    const values = [];
    const placeholders = updates.map((update, index) => {
      const roomTypeId = String(update.roomTypeId || "").trim();
      if (!roomTypeId) {
        throw Object.assign(new Error("roomTypeId is required"), { status: 400 });
      }
      const stayDate = parseDateParam(update.date, "date");
      const price = Number(update.price);
      if (!Number.isFinite(price) || price < 0) {
        throw Object.assign(new Error("price must be a non-negative number"), { status: 400 });
      }

      values.push(roomTypeId, stayDate, Math.round(price * 100), session.id);
      const offset = index * 4;
      return `($${offset + 1}::text, $${offset + 2}::date, $${offset + 3}::integer, $${offset + 4}::uuid)`;
    });

    const result = await query(
      `
        INSERT INTO room_type_price (room_type_id, stay_date, price_cents, updated_by)
        SELECT room_type_id, stay_date, price_cents, updated_by
        FROM (VALUES ${placeholders.join(", ")}) AS updates(room_type_id, stay_date, price_cents, updated_by)
        WHERE stay_date >= CURRENT_DATE
          AND stay_date <= ${maxEditableDateSql}
        ON CONFLICT (room_type_id, stay_date)
        DO UPDATE SET
          price_cents = EXCLUDED.price_cents,
          updated_by = EXCLUDED.updated_by,
          updated_at = now()
        WHERE room_type_price.stay_date >= CURRENT_DATE
          AND room_type_price.stay_date <= ${maxEditableDateSql}
        RETURNING room_type_id
      `,
      values
    );

    return NextResponse.json({ ok: true, count: result.rowCount });
  } catch (error) {
    return NextResponse.json(
      { error: error.message || "Failed to save prices" },
      { status: error.status || 500 }
    );
  }
}
