import { query } from "@/lib/db";

const TERMINAL_STATUSES = new Set(["completed", "failed", "stopped"]);

function arrayFrom(value) {
  return Array.isArray(value) ? value : [];
}

function unique(values) {
  return [...new Set(values.filter(Boolean).map(String))];
}

export function missingPricingOutputError(runId, propertyIds = []) {
  const propertyText = propertyIds.length > 0 ? ` for ${propertyIds.join(", ")}` : "";
  return `Revy finished but did not save suggested prices${propertyText}. No rows were written to property_price; check the agent log and run Revy again.`;
}

export async function getPricingOutputState({ runId, run = null, propertyId = null, accountId = null }) {
  const candidatePropertyIds = unique([propertyId, run?.propertyId, ...arrayFrom(run?.propertyIds)]);
  const result = await query(
    `
      SELECT
        property.id,
        property.account_id::text AS "accountId",
        property.data,
        (
          SELECT count(*)::int
          FROM property_price
          WHERE property_price.property_id = property.id
        ) AS "priceRowCount"
      FROM property
      WHERE (
          cardinality($1::text[]) > 0
          AND property.id = ANY($1::text[])
        )
        OR property.data->>'activeAgentRunId' = $2
        OR property.data->>'lastAgentRunId' = $2
        OR property.data->>'lastOpenClawFixtureRunId' = $2
      ORDER BY property.updated_at DESC, property.id
    `,
    [candidatePropertyIds, runId],
  );

  const rows = accountId
    ? result.rows.filter((row) => row.accountId === String(accountId))
    : result.rows;
  const propertyIds = rows.map((row) => row.id);
  const missingPropertyIds = rows
    .filter((row) => Number(row.priceRowCount || 0) <= 0)
    .map((row) => row.id);
  const storedError = rows.find((row) => row.data?.agentRunError || row.data?.pricingOutputError)?.data?.agentRunError
    || rows.find((row) => row.data?.agentRunError || row.data?.pricingOutputError)?.data?.pricingOutputError
    || null;
  const storedStatus = rows.find((row) => row.data?.agentRunStatus)?.data?.agentRunStatus || null;
  const staleNoHostProcess = rows.some((row) => row.data?.agentRunStopReason === "stale_no_host_process");

  return {
    propertyIds,
    missingPropertyIds,
    priceRowCount: rows.reduce((total, row) => total + Number(row.priceRowCount || 0), 0),
    hasKnownProperties: rows.length > 0,
    hasCompletePrices: rows.length > 0 && missingPropertyIds.length === 0,
    storedError,
    storedStatus,
    staleNoHostProcess,
  };
}

export function runNeedsPricingOutputFailure(run, outputState, { hostProcessAlive = false } = {}) {
  if (outputState.storedError) return outputState.storedError;
  if (!outputState.hasKnownProperties || outputState.hasCompletePrices) return "";

  if (run.status === "completed") {
    return missingPricingOutputError(run.runId, outputState.missingPropertyIds);
  }
  if (run.status === "stopped" && outputState.staleNoHostProcess) {
    return missingPricingOutputError(run.runId, outputState.missingPropertyIds);
  }
  if (run.status === "unknown" && !hostProcessAlive) {
    return missingPricingOutputError(run.runId, outputState.missingPropertyIds);
  }
  return "";
}

export function appendPricingOutputFailureEvent(run, error) {
  if (!error) return run;
  const events = arrayFrom(run.events);
  if (events.some((event) => event.tool === "pricing-output-verifier" && event.error === error)) {
    return run;
  }
  const timestamp = new Date().toISOString();
  return {
    ...run,
    events: [
      ...events,
      {
        timestamp,
        stage: "agent_finish",
        tool: "pricing-output-verifier",
        status: "failed",
        message: error,
        error,
      },
    ],
  };
}

export async function decorateRunWithPricingOutput(run, { hostProcessAlive = false } = {}) {
  const outputState = await getPricingOutputState({ runId: run.runId, run });
  const outputError = runNeedsPricingOutputFailure(run, outputState, { hostProcessAlive });
  let next = { ...run, pricingOutput: outputState };

  if (outputState.storedStatus && TERMINAL_STATUSES.has(outputState.storedStatus)) {
    next.status = outputState.storedStatus;
  }
  if (run.status === "unknown" && hostProcessAlive) {
    next.status = "running";
  }
  if (run.status === "unknown" && !hostProcessAlive && outputState.hasCompletePrices) {
    next.status = "completed";
  }
  if (outputError) {
    next = appendPricingOutputFailureEvent({
      ...next,
      status: "failed",
      error: outputError,
    }, outputError);
  }

  return next;
}
