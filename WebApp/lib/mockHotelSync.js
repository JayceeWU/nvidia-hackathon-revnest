import pg from "pg";

const { Pool } = pg;

const defaultConnectionString = "postgres://postgres:postgres@localhost:55432/dev";
const connectionString =
  process.env.MOCKHOTEL_DATABASE_URL ||
  process.env.MOCK_HOTEL_DATABASE_URL ||
  defaultConnectionString;
const maxEditableDateSql = "CURRENT_DATE + INTERVAL '2 years' - INTERVAL '1 day'";
const monthNumbers = new Map(
  [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
  ].map((month, index) => [month, String(index + 1).padStart(2, "0")])
);

const globalForPg = globalThis;

const mockHotelPool =
  globalForPg.mockHotelSyncPool ||
  new Pool({
    connectionString,
  });

if (process.env.NODE_ENV !== "production") {
  globalForPg.mockHotelSyncPool = mockHotelPool;
}

function normalizeExactText(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function parseStayDate(value) {
  const text = String(value || "").trim();
  const isoMatch = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (isoMatch) {
    return text;
  }

  const namedMatch = text.match(/^([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})$/);
  if (namedMatch) {
    const [, monthName, day, year] = namedMatch;
    const month = monthNumbers.get(monthName.toLowerCase());
    if (month) {
      return `${year}-${month}-${String(day).padStart(2, "0")}`;
    }
  }

  const parsed = new Date(text);
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toISOString().slice(0, 10);
  }

  throw new Error(`Could not parse MockHotel price date "${value}"`);
}

function parsePriceCents(value) {
  const amount = Number(String(value || "").replace(/[^0-9.-]+/g, ""));
  if (!Number.isFinite(amount) || amount < 0) {
    throw new Error(`Could not parse MockHotel price "${value}"`);
  }

  return Math.round(amount * 100);
}

async function findMockHotelUpdatedBy(client) {
  const result = await client.query(
    `
      SELECT id
      FROM account
      ORDER BY created_at, id
      LIMIT 1
    `
  );

  return result.rows[0]?.id || null;
}

async function findRoomType(client, log) {
  const propertyId = String(log.propertyId || log.property_id || "").trim();
  if (propertyId) {
    const result = await client.query(
      `
        SELECT id, name, room_type
        FROM room_type
        WHERE id = $1
        LIMIT 1
      `,
      [propertyId]
    );

    if (result.rows[0]) {
      return result.rows[0];
    }

    throw new Error(`No MockHotel room type matched property_id "${propertyId}"`);
  }

  const propertyName = String(log.property || log.roomType || log.room_type || "").trim();
  const normalizedPropertyName = normalizeExactText(propertyName);
  if (!normalizedPropertyName) {
    throw new Error("Accepted price log is missing a room type identifier");
  }

  const result = await client.query(
    `
      SELECT id, name, room_type
      FROM room_type
      ORDER BY name, id
    `
  );
  const matches = result.rows.filter((row) => {
    return (
      normalizeExactText(row.name) === normalizedPropertyName ||
      normalizeExactText(row.room_type) === normalizedPropertyName
    );
  });

  if (matches.length === 1) {
    return matches[0];
  }
  if (matches.length > 1) {
    throw new Error(`Multiple MockHotel room types matched "${propertyName}"`);
  }

  throw new Error(`No MockHotel room type matched "${propertyName}"`);
}

export async function syncAcceptedPricesToMockHotel(logs) {
  const acceptedLogs = logs.filter(Boolean);
  if (acceptedLogs.length === 0) {
    return { ok: true, updatedRoomTypePrices: 0, updates: [] };
  }

  let client = null;
  try {
    client = await mockHotelPool.connect();
    await client.query("BEGIN");
    const updatedBy = await findMockHotelUpdatedBy(client);
    const updates = [];

    for (const log of acceptedLogs) {
      const roomType = await findRoomType(client, log);
      const stayDate = parseStayDate(log.priceDate);
      const priceCents = parsePriceCents(log.newPrice || log.finalPrice || log.agentSuggestedPrice);

      const result = await client.query(
        `
          INSERT INTO room_type_price (room_type_id, stay_date, price_cents, updated_by)
          SELECT $1::text, $2::date, $3::integer, $4::uuid
          WHERE $2::date >= CURRENT_DATE
            AND $2::date <= ${maxEditableDateSql}
          ON CONFLICT (room_type_id, stay_date)
          DO UPDATE SET
            price_cents = EXCLUDED.price_cents,
            updated_by = EXCLUDED.updated_by,
            updated_at = now()
          RETURNING room_type_id
        `,
        [roomType.id, stayDate, priceCents, updatedBy]
      );

      if (result.rowCount === 0) {
        throw new Error(`MockHotel date "${stayDate}" is outside the editable price horizon`);
      }

      updates.push({
        propertyId: roomType.id,
        property: roomType.name,
        priceDate: stayDate,
        priceCents,
        roomType: roomType.room_type,
      });
    }

    await client.query("COMMIT");
    return {
      ok: true,
      updatedRoomTypePrices: updates.length,
      updates,
    };
  } catch (error) {
    if (client) {
      await client.query("ROLLBACK").catch(() => {});
    }
    throw new Error(`MockHotel sync failed: ${error.message}`);
  } finally {
    if (client) {
      client.release();
    }
  }
}
