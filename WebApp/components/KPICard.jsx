"use client";

// Generic KPI card. Used by the Overview Dashboard for portfolio numbers
// (Total Properties, RevPAR, Total Revenue, Agent Recommendations).

function trendClass(trend) {
  if (trend === "up") return "kpi-trend up";
  if (trend === "down") return "kpi-trend down";
  return "kpi-trend flat";
}

export default function KPICard({ label, value, trend, deltaLabel, footnote, accent }) {
  return (
    <article className={`kpi-card ${accent ? `accent-${accent}` : ""}`}>
      <span className="kpi-label">{label}</span>
      <strong className="kpi-value">{value}</strong>
      {deltaLabel ? (
        <span className={trendClass(trend)}>
          {trend === "up" ? "▲" : trend === "down" ? "▼" : "—"} {deltaLabel}
        </span>
      ) : null}
      {footnote ? <small className="kpi-foot">{footnote}</small> : null}
    </article>
  );
}
