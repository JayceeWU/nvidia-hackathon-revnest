import { NextResponse } from "next/server";
import { pool } from "@/lib/db";
import { syncAcceptedPricesToMockHotel } from "@/lib/mockHotelSync";
import { approvalActor, requireAccountSession } from "@/lib/serverSession";

export const runtime = "nodejs";

function taskPriceDirection(task) {
  const direction = task.priceDirection || task.changeType || task.price_direction || task.type;
  return direction === "Increase" || direction === "Decrease" ? direction : null;
}

function buildAcceptedLog(task, index, session) {
  const now = Date.now();
  const acceptedAt = new Date().toISOString();
  const priceDirection = taskPriceDirection(task);
  const pendingTaskType = task.taskType || task.classification || null;
  const pendingTaskTypeLabel = task.taskTypeLabel || task.classificationLabel || null;
  return {
    id: `log-accepted-${now}-${index}`,
    propertyId: task.propertyId || task.property_id || null,
    property: task.property,
    priceDate: task.priceDate,
    type: priceDirection || task.type,
    priceDirection,
    pendingTaskType,
    pendingTaskTypeLabel,
    taskTypeDescription: task.taskTypeDescription || task.classificationDescription || null,
    approvalGateLabel: task.approvalGateLabel || null,
    oldPrice: task.currentPrice,
    newPrice: task.agentSuggestedPrice,
    agentSuggestedPrice: task.agentSuggestedPrice,
    change: task.change,
    agentSuggestedAt: task.agentSuggestedAt,
    adjustedAt: acceptedAt,
    acceptedAt,
    acceptedBy: approvalActor(session),
    approvalSource: "webapp_accept_button",
    classification: task.classification || null,
    classificationLabel: task.classificationLabel || null,
    classificationDescription: task.classificationDescription || task.taskTypeDescription || null,
    approvalRequirement: task.approvalRequirement || null,
    strategyRange: task.strategyRange || null,
    reviewDrivers: Array.isArray(task.reviewDrivers) ? task.reviewDrivers : [],
    reviewReason: task.reviewReason || null,
    reason: `${task.reason} Accepted through Accept all.`,
    agentSignals: ["Pending task accepted", "Host guardrails checked", "Final price confirmed by user"],
  };
}

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

    const accountType = taskResult.rows[0]?.account_type;
    const logs = taskResult.rows.map((row, index) => buildAcceptedLog(row.data, index, auth.session));
    let mockHotelSync = null;

    if (accountType === "hotel" && logs.length > 0) {
      mockHotelSync = await syncAcceptedPricesToMockHotel(logs);
    }
    for (const log of logs) {
      log.mockHotelSync = mockHotelSync;
    }

    for (const log of logs) {
      await client.query(
        `
          INSERT INTO pricing_record (id, account_id, record_type, data)
          VALUES ($1, $2::uuid, 'price_log', $3::jsonb)
        `,
        [log.id, accountId, JSON.stringify(log)]
      );
    }

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
