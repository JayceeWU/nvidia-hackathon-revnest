import { syncAcceptedPricesToMockHotel } from "@/lib/mockHotelSync";
import { approvalActor } from "@/lib/serverSession";

function safeRecordId(value) {
  return String(value || "record").replace(/[^a-zA-Z0-9_-]/g, "-").slice(0, 120);
}

function taskPriceDirection(task) {
  const direction = task.priceDirection || task.changeType || task.price_direction || task.type;
  return direction === "Increase" || direction === "Decrease" ? direction : null;
}

function buildAcceptedLogId(task, taskRecordId, acceptedAt, index) {
  const timestamp = Date.parse(acceptedAt) || Date.now();
  return `log-${safeRecordId(taskRecordId || task.id)}-${timestamp}-${index}`;
}

export function buildAcceptedPriceLog(task, {
  taskRecordId = null,
  index = 0,
  finalPrice = null,
  feedback = "",
  session = null,
  approvalSource = "webapp_accept_button",
  acceptAll = false,
} = {}) {
  const acceptedAt = new Date().toISOString();
  const priceDirection = taskPriceDirection(task);
  const pendingTaskType = task.taskType || task.classification || null;
  const pendingTaskTypeLabel = task.taskTypeLabel || task.classificationLabel || null;
  const baseReason = task.reason || "Pending task accepted.";
  const trimmedFeedback = String(feedback || "").trim();
  const reason = trimmedFeedback
    ? `${baseReason} Host note: ${trimmedFeedback}`
    : acceptAll
      ? `${baseReason} Accepted through Accept all.`
      : baseReason;

  return {
    id: buildAcceptedLogId(task, taskRecordId, acceptedAt, index),
    sourcePendingTaskId: taskRecordId || task.id || null,
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
    approvalSource,
    status: "accepted",
    classification: task.classification || null,
    classificationLabel: task.classificationLabel || null,
    classificationDescription: task.classificationDescription || task.taskTypeDescription || null,
    approvalRequirement: task.approvalRequirement || null,
    strategyRange: task.strategyRange || null,
    reviewDrivers: Array.isArray(task.reviewDrivers) ? task.reviewDrivers : [],
    reviewReason: task.reviewReason || null,
    reason,
    agentSignals: acceptAll
      ? ["Pending task accepted", "Host guardrails checked", "Final price confirmed by user"]
      : ["Demand change detected", "Host guardrails checked", "Final price confirmed by user"],
  };
}

export async function writeAcceptedPendingTaskPriceLogs({
  client,
  accountId,
  taskRows,
  session,
  finalPriceForTask = () => null,
  feedbackForTask = () => "",
  approvalSource = "webapp_accept_button",
  acceptAll = false,
}) {
  const rows = Array.isArray(taskRows) ? taskRows : [];
  const logs = rows.map((row, index) =>
    buildAcceptedPriceLog(row.data, {
      taskRecordId: row.id,
      index,
      finalPrice: finalPriceForTask(row, index),
      feedback: feedbackForTask(row, index),
      session,
      approvalSource,
      acceptAll,
    })
  );

  const accountType = rows[0]?.account_type;
  let mockHotelSync = null;
  if (accountType === "hotel" && logs.length > 0) {
    mockHotelSync = await syncAcceptedPricesToMockHotel(logs);
  }

  for (const log of logs) {
    log.mockHotelSync = mockHotelSync;
    await client.query(
      `
        INSERT INTO pricing_record (id, account_id, record_type, data)
        VALUES ($1, $2::uuid, 'price_log', $3::jsonb)
      `,
      [log.id, accountId, JSON.stringify(log)]
    );
  }

  return { logs, mockHotelSync };
}
