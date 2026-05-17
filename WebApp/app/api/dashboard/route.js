import { NextResponse } from "next/server";
import { getLatestRunForProperty, getRun, isHostRunProcessAlive } from "@/lib/agentRunStore";
import { query } from "@/lib/db";

const dateFormatter = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

function toDollars(cents) {
  return Math.round(Number(cents) / 100);
}

function formatForecastDate(value) {
  return dateFormatter.format(new Date(value));
}

function pricingOutputError(row, forecast, activeAgentRunId, agentRunStatus) {
  if (row.data.agentRunError || row.data.pricingOutputError) {
    return row.data.agentRunError || row.data.pricingOutputError;
  }
  if (activeAgentRunId || forecast.length > 0) return null;
  if (agentRunStatus === "completed") {
    return "Revy completed, but no suggested prices were saved for this property.";
  }
  if (agentRunStatus === "failed") {
    return "Revy failed before suggested prices were saved for this property.";
  }
  if (agentRunStatus === "stopped") {
    return row.data.agentRunStopReason === "stale_no_host_process"
      ? "Revy stopped unexpectedly before suggested prices were saved for this property."
      : "Revy stopped before suggested prices were saved for this property.";
  }
  return null;
}

export async function GET(request) {
  const accountId = request.nextUrl.searchParams.get("accountId");

  if (!accountId) {
    return NextResponse.json({ error: "accountId is required" }, { status: 400 });
  }

  const [propertyResult, priceResult, recordResult, hotelHomeDashboardResult] = await Promise.all([
    query(
      `
        SELECT id, min_price_cents, max_price_cents, pricing_horizon, my_place, room_count, capacity, zip_code, county, state, city, bed, bath, other_info, data
        FROM property
        WHERE account_id = $1
        ORDER BY created_at, id
      `,
      [accountId]
    ),
    query(
      `
        SELECT property_id, price_date, fixed_price_cents, agent_price_cents
        FROM property_price
        WHERE property_id IN (SELECT id FROM property WHERE account_id = $1)
        ORDER BY property_id, price_date
      `,
      [accountId]
    ),
    query(
      `
        SELECT id, record_type, data, created_at
        FROM pricing_record
        WHERE account_id = $1
        ORDER BY created_at DESC, id
      `,
      [accountId]
    ),
    query(
      `
        SELECT data
        FROM hotel_home_dashboard
        WHERE account_id = $1
          AND id = 'home'
        LIMIT 1
      `,
      [accountId]
    ),
  ]);

  const forecastByProperty = new Map();
  for (const row of priceResult.rows) {
    if (!forecastByProperty.has(row.property_id)) {
      forecastByProperty.set(row.property_id, []);
    }
    forecastByProperty.get(row.property_id).push({
      day: formatForecastDate(row.price_date),
      fixed: toDollars(row.fixed_price_cents),
      agent: toDollars(row.agent_price_cents),
    });
  }

  const properties = propertyResult.rows.map((row) => {
    const savedRun = row.data.activeAgentRunId ? getRun(row.data.activeAgentRunId) : null;
    const runtimeRun = getLatestRunForProperty(row.id) || savedRun;
    const runtimeIsRunning = runtimeRun?.status === "running";
    const savedRunIsAlive = row.data.activeAgentRunId ? isHostRunProcessAlive(row.data.activeAgentRunId) : false;
    const activeAgentRunId = runtimeIsRunning
      ? runtimeRun.runId
      : savedRunIsAlive
        ? row.data.activeAgentRunId
        : null;
    const runtimeStatus = runtimeRun?.status && runtimeRun.status !== "unknown" ? runtimeRun.status : null;
    const savedStatus = row.data.agentRunStatus === "running" && !activeAgentRunId ? null : row.data.agentRunStatus;
    const forecast = forecastByProperty.get(row.id) || row.data.forecast || [];
    let agentRunStatus = activeAgentRunId ? "running" : runtimeStatus || savedStatus || null;
    if (!activeAgentRunId && agentRunStatus === "stopped" && forecast.length > 0) {
      agentRunStatus = "completed";
    }
    return {
      ...row.data,
      id: row.id,
      minPrice: toDollars(row.min_price_cents),
      maxPrice: toDollars(row.max_price_cents),
      minPriceCents: Number(row.min_price_cents),
      maxPriceCents: Number(row.max_price_cents),
      pricingHorizon: Number(row.pricing_horizon),
      myPlace: row.my_place || row.data.myPlace || row.data.airbnbUrl || null,
      roomCount: row.room_count ?? row.data.roomCount ?? null,
      capacity: row.capacity ?? row.data.capacity ?? null,
      zipCode: row.zip_code || row.data.zipCode || null,
      county: row.county || row.data.county || null,
      state: row.state || row.data.state || null,
      city: row.city || row.data.city || null,
      bed: row.bed || row.data.bed || row.data.beds || null,
      beds: row.data.beds || row.bed || null,
      bath: row.bath || row.data.bath || row.data.bathroom || null,
      bathroom: row.data.bathroom || row.bath || null,
      otherInfo: row.other_info || row.data.otherInfo || row.data.other_info || null,
      activeAgentRunId,
      agentRunStatus,
      forecast,
      pricingOutputError: pricingOutputError(row, forecast, activeAgentRunId, agentRunStatus),
    };
  });

  const pendingTasks = [];
  const priceLogs = [];
  for (const row of recordResult.rows) {
    if (row.record_type === "pending_task") {
      pendingTasks.push({ ...row.data, id: row.id, taskDataId: row.data?.id || null });
    } else if (row.record_type === "price_log") {
      priceLogs.push(row.data);
    }
  }

  const hotelHomeDashboard = hotelHomeDashboardResult.rows[0]?.data || null;

  return NextResponse.json({ properties, pendingTasks, priceLogs, hotelHomeDashboard });
}
