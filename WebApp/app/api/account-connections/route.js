import { NextResponse } from "next/server";
import { query } from "@/lib/db";

export const runtime = "nodejs";

function sanitizeConnection(value) {
  if (!value || typeof value !== "object") {
    return null;
  }

  const id = String(value.id || "").trim();
  const name = String(value.name || "").trim();
  const accountId = String(value.accountId || "").trim();
  const status = String(value.status || "Connected").trim() || "Connected";
  const connectedAt = String(value.connectedAt || "").trim();

  if (!id || !name || !accountId) {
    return null;
  }

  return {
    id,
    name,
    accountId,
    status,
    connectedAt,
    ...(value.provider ? { provider: String(value.provider).trim() } : {}),
  };
}

function mapConnectionRows(rows) {
  return rows.map((row) => ({ ...row.data, id: row.id }));
}

export async function GET(request) {
  const accountId = request.nextUrl.searchParams.get("accountId");

  if (!accountId) {
    return NextResponse.json({ error: "accountId is required" }, { status: 400 });
  }

  try {
    const [externalAccountResult, channelResult] = await Promise.all([
      query(
        `
          SELECT id, data
          FROM external_account
          WHERE account_id = $1::uuid
          ORDER BY created_at, id
        `,
        [accountId],
      ),
      query(
        `
          SELECT id, data
          FROM account_channel
          WHERE account_id = $1::uuid
          ORDER BY created_at, id
        `,
        [accountId],
      ),
    ]);

    return NextResponse.json({
      externalAccounts: mapConnectionRows(externalAccountResult.rows),
      connectedChannels: mapConnectionRows(channelResult.rows),
    });
  } catch (error) {
    if (error.code === "42P01") {
      return NextResponse.json({ externalAccounts: [], connectedChannels: [] });
    }
    return NextResponse.json({ error: error.message || "Failed to load account connections" }, { status: 500 });
  }
}

export async function POST(request) {
  const { accountId, type, connection } = await request.json();
  const sanitizedConnection = sanitizeConnection(connection);

  if (!accountId || !type || !sanitizedConnection) {
    return NextResponse.json({ error: "accountId, type, and a valid connection are required" }, { status: 400 });
  }

  const tableName = type === "externalAccount" ? "external_account" : type === "channel" ? "account_channel" : null;
  if (!tableName) {
    return NextResponse.json({ error: "type must be externalAccount or channel" }, { status: 400 });
  }

  try {
    const result = await query(
      `
        INSERT INTO ${tableName} (id, account_id, data)
        VALUES ($1, $2::uuid, $3::jsonb)
        ON CONFLICT (account_id, id)
        DO UPDATE SET data = EXCLUDED.data,
                      updated_at = now()
        RETURNING id, data
      `,
      [sanitizedConnection.id, accountId, JSON.stringify(sanitizedConnection)],
    );

    return NextResponse.json({ connection: { ...result.rows[0].data, id: result.rows[0].id } });
  } catch (error) {
    return NextResponse.json({ error: error.message || "Failed to save account connection" }, { status: 500 });
  }
}
