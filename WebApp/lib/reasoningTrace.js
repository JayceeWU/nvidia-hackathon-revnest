// Mock reasoning trace data for the RevNest agent.
// Shape mirrors Claw/memory/multi_step_reasoning_trace.json so this file
// can be replaced with a real fetch() against the Python backend later
// without changing the components that consume it.

export const FULL_TRACE_STEPS = [
  {
    step: 1,
    name: "understand_property",
    label: "Understand Property",
    tool: null,
    status: "done",
    icon: "brain",
    reasoning:
      "Santa Cruz private Airbnb suite in a coastal high-demand market. Initial ADR hypothesis $200-$240/night before market verification.",
  },
  {
    step: 2,
    name: "read_memory",
    label: "Read Host Memory",
    tool: "memory_read",
    status: "done",
    icon: "memory",
    reasoning:
      "Host prefers higher ADR over maximum occupancy. Manual approval is the default. Hold target range; lean to upper end.",
    tool_input: { property_id: "coastal-suite" },
    tool_output: {
      host_preferences: { risk_tolerance: "prefer higher ADR over max occupancy" },
      approval_mode: "manual",
      max_change_pct: 30,
    },
  },
  {
    step: 3,
    name: "check_weather",
    label: "Check Weather",
    tool: "weather",
    status: "done",
    icon: "weather",
    reasoning:
      "Mild weekend conditions, no severe weather. Treat as a neutral signal that does not dampen event-driven demand.",
    tool_input: { location: "Santa Cruz, CA", days: 7 },
    tool_output: {
      forecast: [
        { date: "2026-05-15", high_f: 67, low_f: 54, conditions: "partly cloudy", precip_pct: 10 },
        { date: "2026-05-16", high_f: 69, low_f: 55, conditions: "sunny", precip_pct: 5 },
        { date: "2026-05-17", high_f: 68, low_f: 56, conditions: "partly cloudy", precip_pct: 12 },
      ],
    },
    signal: { type: "weather", label: "Mild weekend, neutral", impact: "neutral" },
  },
  {
    step: 4,
    name: "scrape_competitor_price",
    label: "Fetch Competitor Rates",
    tool: "competitor_rates",
    status: "done",
    icon: "competitor",
    reasoning:
      "Competitor median is $238 for 2026-05-17. The static $189 is 21% below market. The property's ocean access supports targeting at-or-above median.",
    tool_input: { location: "Santa Cruz, CA", date: "2026-05-17" },
    tool_output: {
      median_rate: 238,
      rates: [
        { property: "Boardwalk Studio", rate: 238 },
        { property: "Westside Guest Suite", rate: 224 },
        { property: "Downtown Private Room", rate: 196 },
        { property: "Ocean View Apartment", rate: 278 },
        { property: "Capitola Cottage", rate: 252 },
      ],
      compliance_note:
        "Demo competitor snapshots are simulated/local CSV. Production would call authorized OTA, PMS, or market intelligence APIs.",
    },
    signal: { type: "competitor", label: "Below median by 21%", impact: "up" },
  },
  {
    step: 5,
    name: "get_local_events",
    label: "Fetch Local Events",
    tool: "events",
    status: "done",
    icon: "event",
    reasoning:
      "A stadium concert is 2.4 miles away on the target date with a 1.34x demand multiplier. Strong upward pressure on the event window.",
    tool_input: { location: "Santa Cruz", days: 30 },
    tool_output: {
      events: [
        { name: "Stadium concert", date: "2026-05-17", distance_miles: 2.4, demand_multiplier: 1.34, category: "music" },
        { name: "Downtown food festival", date: "2026-05-20", distance_miles: 1.1, demand_multiplier: 1.18, category: "festival" },
        { name: "Regional youth sports tournament", date: "2026-05-24", distance_miles: 5.8, demand_multiplier: 1.28, category: "sports" },
        { name: "Conference center trade show", date: "2026-06-01", distance_miles: 3.2, demand_multiplier: 1.16, category: "business" },
      ],
    },
    signal: { type: "event", label: "Stadium concert 2.4mi (1.34x)", impact: "up" },
  },
  {
    step: 6,
    name: "fetch_history",
    label: "Historical Performance",
    tool: "history_summary",
    status: "done",
    icon: "history",
    reasoning:
      "Historical occupancy is 80% with RevPAR $147 — the property is underpriced for the current market. Supports a controlled increase rather than a discount.",
    tool_input: { property_id: "coastal-suite", csv: "history_pricing.csv" },
    tool_output: {
      rows: 5,
      average_rate: 190.4,
      occupancy_rate: 0.8,
      booked_count: 4,
      revenue: 737,
      revpar: 147.4,
    },
    signal: { type: "occupancy", label: "80% occupancy", impact: "up" },
  },
  {
    step: 7,
    name: "calc_demand_index",
    label: "Calculate Demand Index",
    tool: "demand_calc",
    status: "done",
    icon: "calc",
    reasoning:
      "Combine market median, event multiplier, and host ADR-first preference. Raw suggestion lands at $246 — aligned with median and above the static price.",
    calculation: "base $238 × demand_factor 1.034 = raw $246",
    tool_output: { demand_index: 1.34, base_rate: 238, raw_price: 246 },
    signal: { type: "demand", label: "Demand index 1.34x", impact: "up" },
  },
  {
    step: 8,
    name: "enforce_guardrails",
    label: "Enforce Guardrails",
    tool: "guardrails",
    status: "done",
    icon: "shield",
    reasoning:
      "30% max-change cap is exactly hit. Final actionable price is $246, within the $120-$280 host range. Within auto-publish policy when connected.",
    tool_input: {
      old_price: 189,
      suggested_price: 246,
      min_price: 120,
      max_price: 280,
      max_change_pct: 30,
    },
    tool_output: {
      final_price: 245.7,
      change_pct: 30,
      within_auto_publish_policy: true,
      capped: true,
    },
    signal: { type: "guardrail", label: "30% cap applied", impact: "cap" },
  },
  {
    step: 9,
    name: "update_price",
    label: "Queue Price Update",
    tool: "publish_price",
    status: "done",
    icon: "send",
    reasoning:
      "Property is in manual mode → queued as a Pending Task instead of being auto-published. Awaiting host approval.",
    tool_input: {
      property_id: "coastal-suite",
      date: "2026-05-17",
      old_price: 189,
      new_price: 246,
      mode: "dry_run",
    },
    tool_output: {
      status: "queued",
      mode: "dry_run",
      audit_id: "audit-2026-05-09-001",
      audit_log: "Claw/memory/pricing_publish_audit.jsonl",
    },
    signal: { type: "action", label: "Queued for approval", impact: "pending" },
  },
  {
    step: 10,
    name: "save_memory",
    label: "Save to Memory",
    tool: "memory_write",
    status: "done",
    icon: "save",
    reasoning:
      "Persisted run summary, final price, key signals, and reasoning so a new terminal/session can recover the decision history.",
    tool_input: {
      property_id: "coastal-suite",
      summary: { final_price: 246, action: "pending host approval" },
    },
    tool_output: { written: true, file: "Claw/memory/host_preferences.json" },
  },
];

// Compact 5-step view used by the inline AgentReasoningPanel on Property Detail.
// These are the user-facing tool calls the host actually cares about.
export const COMPACT_TRACE_STEPS = [
  {
    step: 1,
    name: "check_weather",
    label: "check_weather()",
    icon: "weather",
    status: "done",
    result: "Mild weekend, no severe weather",
    signal: { label: "Neutral", impact: "neutral" },
    reasoning: "Weather will not dampen event-driven demand.",
  },
  {
    step: 2,
    name: "scrape_competitor_price",
    label: "scrape_competitor_price()",
    icon: "competitor",
    status: "done",
    result: "Median $238 across 5 comps",
    signal: { label: "Below median 21%", impact: "up" },
    reasoning: "Static $189 is well below comparable listings.",
  },
  {
    step: 3,
    name: "get_local_events",
    label: "get_local_events()",
    icon: "event",
    status: "done",
    result: "Stadium concert 2.4 mi on 2026-05-17",
    signal: { label: "1.34x multiplier", impact: "up" },
    reasoning: "Event window creates strong demand compression.",
  },
  {
    step: 4,
    name: "calc_demand_index",
    label: "calc_demand_index()",
    icon: "calc",
    status: "done",
    result: "Demand index 1.34 → raw price $246",
    signal: { label: "+30% raw", impact: "up" },
    reasoning: "Combined market + event signals justify a controlled increase.",
  },
  {
    step: 5,
    name: "update_price",
    label: "update_price()",
    icon: "send",
    status: "done",
    result: "$189 → $246, queued for host approval",
    signal: { label: "Within 30% cap", impact: "pending" },
    reasoning: "Manual mode queues a Pending Task instead of auto-publishing.",
  },
];

// Run-level summary that complements the step-by-step trace.
export const TRACE_SUMMARY = {
  run_date: "2026-05-09",
  property_id: "coastal-suite",
  property_name: "Santa Cruz Coastal Suite",
  price_date: "2026-05-17",
  old_price: 189,
  final_price: 246,
  competitor_median: 238,
  occupancy_rate: 0.8,
  demand_index: 1.34,
  change_pct: 30,
  revpar_lift_pct: 30,
  action: "pending host approval",
  why:
    "Stadium concert demand compression plus competitor median above the static price → 30% controlled increase to $246.",
};

// Lightweight per-property override map. Right now only one property has a
// dedicated mock trace; others fall back to the canonical Coastal Suite run.
const TRACE_BY_PROPERTY = {
  "coastal-suite": {
    summary: TRACE_SUMMARY,
    full: FULL_TRACE_STEPS,
    compact: COMPACT_TRACE_STEPS,
  },
};

// Helper API used by components. Falls back to the Coastal Suite trace for
// any property without a dedicated mock so the UI is never empty in demo.
export function getReasoningTraceForProperty(propertyId) {
  if (TRACE_BY_PROPERTY[propertyId]) {
    return TRACE_BY_PROPERTY[propertyId];
  }
  return TRACE_BY_PROPERTY["coastal-suite"];
}

export function getLatestTrace() {
  return TRACE_BY_PROPERTY["coastal-suite"];
}
