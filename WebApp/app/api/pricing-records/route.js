import { NextResponse } from "next/server";
import { pool } from "@/lib/db";
import { writeAcceptedPendingTaskPriceLogs } from "@/lib/pricingRecords";
import { requireAccountSession } from "@/lib/serverSession";

export const runtime = "nodejs";

export async function POST(request) {
  const { accountId, taskId, action, finalPrice, feedback } = await request.json();

  if (!accountId || !taskId || !action) {
    return NextResponse.json({ error: "accountId, taskId, and action are required" }, { status: 400 });
  }

  if (!["apply", "close"].includes(action)) {
    return NextResponse.json({ error: "action must be apply or close" }, { status: 400 });
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
        WHERE pricing_record.id = $1
          AND pricing_record.account_id = $2::uuid
          AND pricing_record.record_type = 'pending_task'
        LIMIT 1
        FOR UPDATE OF pricing_record
      `,
      [taskId, accountId]
    );

    const task = taskResult.rows[0]?.data;
    if (!task) {
      await client.query("ROLLBACK");
      return NextResponse.json({ error: "Pending task was not found" }, { status: 404 });
    }

    let log = null;
    let mockHotelSync = null;
    if (action === "apply") {
      const writeResult = await writeAcceptedPendingTaskPriceLogs({
        client,
        accountId,
        taskRows: taskResult.rows,
        session: auth.session,
        finalPriceForTask: () => finalPrice,
        feedbackForTask: () => feedback,
        approvalSource: "webapp_accept_button",
      });
      log = writeResult.logs[0] || null;
      mockHotelSync = writeResult.mockHotelSync;
    }

    await client.query(
      `
        DELETE FROM pricing_record
        WHERE id = $1
          AND account_id = $2::uuid
          AND record_type = 'pending_task'
      `,
      [taskId, accountId]
    );

    await client.query("COMMIT");
    return NextResponse.json({ ok: true, log, mockHotelSync });
  } catch (error) {
    await client.query("ROLLBACK");
    return NextResponse.json({ error: error.message || "Failed to update pricing record" }, { status: 500 });
  } finally {
    client.release();
  }
}
