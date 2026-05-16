"use client";

import { StepIcon } from "./AgentIcons";

// Demand signal card used on the Overview Dashboard. Shows one of weather,
// events, competitor median, or occupancy with a headline metric and a
// short detail line. Tone reflects whether the signal is pushing prices up,
// down, or neutral so the dashboard reads at a glance.

function trendClass(trend) {
  if (trend === "up") return "signal-trend up";
  if (trend === "down") return "signal-trend down";
  if (trend === "flat") return "signal-trend flat";
  return "signal-trend neutral";
}

const collectedAtFormatter = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  timeZoneName: "short",
});

function formatCollectedAt(value) {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return collectedAtFormatter.format(date);
}

export default function DemandSignalCard({ icon, label, value, detail, trend, footnote, items, collectedAt }) {
  const collectedAtText = formatCollectedAt(collectedAt);
  return (
    <article className="signal-card">
      <div className="signal-card-head">
        <span className="signal-card-icon">
          <StepIcon name={icon} width={18} height={18} />
        </span>
        <span className="signal-card-label">{label}</span>
      </div>
      {collectedAtText ? <span className="signal-card-collected">Fetched {collectedAtText}</span> : null}
      <strong className="signal-card-value">{value}</strong>
      {detail ? <span className="signal-card-detail">{detail}</span> : null}
      {trend ? (
        <span className={trendClass(trend)}>
          {trend === "up" ? "▲" : trend === "down" ? "▼" : "•"} {footnote || "vs last period"}
        </span>
      ) : null}
      {items && items.length > 0 ? (
        <ul className="signal-card-list">
          {items.slice(0, 3).map((item) => (
            <li key={`${item.name}-${item.date}`}>
              <span>{item.name}</span>
              <small>
                {item.date}
                {item.multiplier ? ` · ${item.multiplier.toFixed(2)}x` : ""}
              </small>
            </li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}
