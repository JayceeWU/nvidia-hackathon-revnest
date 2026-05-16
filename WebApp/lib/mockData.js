// Mock data for KPIs and agent memory.
// Hotel home dashboard signals are seeded in the Claw/data/sql hotel_home_dashboard table.

export const PORTFOLIO_KPIS = {
  total_properties: 8,
  total_rooms: 40,
  revpar: 152,
  revpar_delta_pct: 12,
  total_revenue_month: 18420,
  total_revenue_delta_pct: 9,
  agent_recommendations_30d: 24,
  agent_recommendations_pending: 3,
};

export const AGENT_MEMORY = {
  pricing_rules: {
    minimum_price: 120,
    maximum_price: 280,
    max_change_pct: 30,
    aggressive_pricing_when: [
      "Local event within 5 miles with demand multiplier ≥ 1.25x",
      "Competitor median above static price by ≥ 15%",
      "Historical occupancy above 80%",
    ],
    conservative_pricing_when: [
      "Heavy rain forecast for two or more nights",
      "Weekday pickup below baseline",
      "Competitor inventory above 90% available",
    ],
  },
  last_actions: [
    {
      property: "Santa Cruz Coastal Suite",
      change: "$189 → $246 (+30%)",
      date: "May 9, 2026",
      status: "Pending host approval",
      reason: "Stadium concert + competitor compression",
    },
    {
      property: "Downtown Event Studio",
      change: "$162 → $149 (-8%)",
      date: "May 9, 2026",
      status: "Applied",
      reason: "Rain forecast + low weekday pickup",
    },
    {
      property: "Roadside King Room",
      change: "$96 → $118 (+23%)",
      date: "May 8, 2026",
      status: "Applied",
      reason: "Convention traffic + budget inventory low",
    },
  ],
  learned_preferences: [
    "Prefers higher ADR over maximum occupancy.",
    "Avoids aggressive weekend jumps above the 30% cap.",
    "Prefers manual approval unless platform is explicitly connected.",
    "Wants raw booking and revenue data to stay on-device (NemoClaw policy).",
  ],
};

// Lightweight session-style log used by Memory & Learning view fallback
// and by the Recent Reasoning Summary block on the dashboard.
export const RECENT_REASONING_SUMMARY = {
  property_name: "Santa Cruz Coastal Suite",
  price_date: "May 17, 2026",
  old_price: 189,
  final_price: 246,
  change_pct: 30,
  why:
    "Stadium concert demand compression plus competitor median above static price → 30% controlled increase to $246.",
  ran_at: "May 9, 2026 5:43 PM",
  tools_used: [
    "check_weather",
    "scrape_competitor_price",
    "get_local_events",
    "fetch_history",
    "calc_demand_index",
    "enforce_guardrails",
    "update_price",
  ],
};
