"use client";

import { useState } from "react";

export default function RevyAgentPriceChart({ data, onPointClick }) {
  const points = (Array.isArray(data) ? data : []).filter((item) => Number.isFinite(Number(item.agent)));
  const [activeIndex, setActiveIndex] = useState(Math.min(3, Math.max(points.length - 1, 0)));

  if (points.length === 0) {
    return (
      <div className="airbnb-chart-empty">
        <strong>No Revy prices yet</strong>
        <span>Run Revy on this property to create an agent price curve.</span>
      </div>
    );
  }

  const width = 760;
  const height = 280;
  const padding = { top: 26, right: 36, bottom: 42, left: 58 };
  const values = points.map((item) => Number(item.agent));
  const min = Math.min(...values) - 18;
  const max = Math.max(...values) + 18;
  const spread = max - min || 1;
  const xStep = points.length > 1 ? (width - padding.left - padding.right) / (points.length - 1) : 0;
  const toX = (index) => (points.length > 1 ? padding.left + index * xStep : width / 2);
  const toY = (value) =>
    height -
    padding.bottom -
    ((Number(value) - min) / spread) * (height - padding.top - padding.bottom);
  const linePoints = points.map((item, index) => `${toX(index)},${toY(item.agent)}`).join(" ");
  const boundedActiveIndex = Math.min(activeIndex, points.length - 1);
  const active = points[boundedActiveIndex] ?? points[0];
  const activeX = toX(boundedActiveIndex);
  const activeY = toY(active.agent);

  function activatePoint(item, index) {
    setActiveIndex(index);
    if (onPointClick) onPointClick(item, index);
  }

  return (
    <div className="airbnb-agent-chart">
      <div className="airbnb-chart-legend">
        <span>
          <i />
          Revy suggested price
        </span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Revy suggested price chart">
        <line
          x1={padding.left}
          y1={height - padding.bottom}
          x2={width - padding.right}
          y2={height - padding.bottom}
          className="axis-line"
        />
        <line
          x1={padding.left}
          y1={padding.top}
          x2={padding.left}
          y2={height - padding.bottom}
          className="axis-line"
        />
        {[0, 1, 2].map((tick) => {
          const value = min + (spread * tick) / 2;
          const y = toY(value);
          return (
            <g key={tick}>
              <line x1={padding.left} y1={y} x2={width - padding.right} y2={y} className="grid-line" />
              <text x={padding.left - 10} y={y + 4} textAnchor="end" className="chart-label">
                ${Math.round(value)}
              </text>
            </g>
          );
        })}
        <polyline points={linePoints} fill="none" className="airbnb-agent-line" />
        {points.map((item, index) => (
          <g key={`${item.day}-${index}`}>
            <circle
              cx={toX(index)}
              cy={toY(item.agent)}
              r={activeIndex === index ? 7 : 5}
              className="airbnb-chart-point"
              onMouseEnter={() => setActiveIndex(index)}
              onFocus={() => setActiveIndex(index)}
              onClick={() => activatePoint(item, index)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  activatePoint(item, index);
                }
              }}
              role="button"
              tabIndex="0"
              aria-label={`Open Revy history for ${item.day || "this date"}, $${Math.round(item.agent)}`}
            />
            <text x={toX(index)} y={height - 14} textAnchor="middle" className="chart-label">
              {String(item.day || "").slice(0, 6)}
            </text>
          </g>
        ))}
        <g transform={`translate(${Math.min(activeX + 14, width - 166)} ${Math.max(activeY - 58, 18)})`}>
          <rect width="150" height="48" rx="6" className="chart-tooltip" />
          <text x="12" y="20" className="tooltip-title">
            {active.day}
          </text>
          <text x="12" y="37" className="tooltip-copy">
            Revy ${Math.round(active.agent)}
          </text>
        </g>
      </svg>
    </div>
  );
}
