import { NextResponse } from "next/server";
import { pool } from "@/lib/db";
import { writeAcceptedPendingTaskPriceLogs } from "@/lib/pricingRecords";
import { requireAccountSession } from "@/lib/serverSession";

export const runtime = "nodejs";

export async function POST(request) {
  const { accountId } = await request.json();

  if (!accountId) {
    return NextResponse.json({ error: "accountId is required" }, { status: 400 });
  }

  const auth = requireAccountSession(request, accountId);
  if (auth.error) {
    return NextResponse.json({ error: auth.error.message }, { status: auth.error.status });
  }

  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const taskResult = await client.query(
      `
        SELECT pricing_record.id, pricing_record.data, account.account_type
        FROM pricing_record
        JOIN account ON account.id = pricing_record.account_id
        WHERE pricing_record.account_id = $1::uuid
          AND pricing_record.record_type = 'pending_task'
        ORDER BY pricing_record.created_at DESC, pricing_record.id
        FOR UPDATE OF pricing_record
      `,
      [accountId]
    );

    const { logs, mockHotelSync } = await writeAcceptedPendingTaskPriceLogs({
      client,
      accountId,
      taskRows: taskResult.rows,
      session: auth.session,
      approvalSource: "webapp_accept_all_button",
      acceptAll: true,
    });

    await client.query(
      `
        DELETE FROM pricing_record
        WHERE account_id = $1::uuid
          AND record_type = 'pending_task'
      `,
      [accountId]
    );

    await client.query("COMMIT");
    return NextResponse.json({ ok: true, acceptedCount: logs.length, logs, mockHotelSync });
  } catch (error) {
    await client.query("ROLLBACK");
    return NextResponse.json({ error: error.message || "Failed to accept pending tasks" }, { status: 500 });
  } finally {
    client.release();
  }
}
