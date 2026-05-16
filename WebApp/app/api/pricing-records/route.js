import { NextResponse } from "next/server";
import { pool } from "@/lib/db";
import { syncAcceptedPricesToMockHotel } from "@/lib/mockHotelSync";
import { approvalActor, requireAccountSession } from "@/lib/serverSession";

export const runtime = "nodejs";

function taskPriceDirection(task) {
  const direction = task.priceDirection || task.changeType || task.price_direction || task.type;
  return direction === "Increase" || direction === "Decrease" ? direction : null;
}

function buildAcceptedLog(task, finalPrice, feedback, session) {
  const acceptedAt = new Date().toISOString();
  const priceDirection = taskPriceDirection(task);
  const pendingTaskType = task.taskType || task.classification || null;
  const pendingTaskTypeLabel = task.taskTypeLabel || task.classificationLabel || null;
  return {
    id: `log-${Date.now()}`,
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
    newPrice: finalPrice || task.agentSuggestedPrice,
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
    reason: feedback?.trim() ? `${task.reason} Host note: ${feedback.trim()}` : task.reason,
    agentSignals: ["Demand change detected", "Host guardrails checked", "Final price confirmed by user"],
  };
}

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
        SELECT pricing_record.data, account.account_type
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
    const accountType = taskResult.rows[0]?.account_type;
    if (!task) {
      await client.query("ROLLBACK");
      return NextResponse.json({ error: "Pending task was not found" }, { status: 404 });
    }

    let log = null;
    let mockHotelSync = null;
    if (action === "apply") {
      log = buildAcceptedLog(task, finalPrice, feedback, auth.session);

      if (accountType === "hotel") {
        mockHotelSync = await syncAcceptedPricesToMockHotel([log]);
      }
      log.mockHotelSync = mockHotelSync;

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
