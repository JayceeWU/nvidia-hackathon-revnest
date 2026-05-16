"use client";

import { useState } from "react";

// SVG line chart comparing fixed nightly rate vs the agent's dynamic
// recommendation across a 7-day horizon. Extracted from the original
// page.js so it can be reused on Property Detail and the (future) A/B
// Performance page without duplication.

export default function PriceForecastChart({ data }) {
  const [activeIndex, setActiveIndex] = useState(3);
  if (!data || data.length === 0) return null;

  const width = 720;
  const height = 280;
  const padding = { top: 26, right: 34, bottom: 42, left: 54 };
  const values = data.flatMap((item) => [item.fixed, item.agent]);
  const min = Math.min(...values) - 18;
  const max = Math.max(...values) + 18;
  const xStep = (width - padding.left - padding.right) / (data.length - 1);
  const toX = (index) => padding.left + index * xStep;
  const toY = (value) =>
    height -
    padding.bottom -
    ((value - min) / (max - min)) * (height - padding.top - padding.bottom);
  const fixedPoints = data
    .map((item, index) => `${toX(index)},${toY(item.fixed)}`)
    .join(" ");
  const agentPoints = data
    .map((item, index) => `${toX(index)},${toY(item.agent)}`)
    .join(" ");
  const active = data[activeIndex] ?? data[0];
  const activeX = toX(activeIndex);
  const activeY = toY(active.agent);

  return (
    <div className="chart-card">
      <div className="chart-legend">
        <span>
          <i className="legend-fixed" /> Fixed price
        </span>
        <span>
          <i className="legend-agent" /> Agent dynamic price
        </span>
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Price forecast line chart"
      >
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
          const value = min + ((max - min) * tick) / 2;
          const y = toY(value);
          return (
            <g key={tick}>
              <line
                x1={padding.left}
                y1={y}
                x2={width - padding.right}
                y2={y}
                className="grid-line"
              />
              <text
                x={padding.left - 10}
                y={y + 4}
                textAnchor="end"
                className="chart-label"
              >
                ${Math.round(value)}
              </text>
            </g>
          );
        })}
        <polyline points={fixedPoints} fill="none" className="fixed-line" />
        <polyline points={agentPoints} fill="none" className="agent-line" />
        {data.map((item, index) => (
          <g key={item.day}>
            <circle
              cx={toX(index)}
              cy={toY(item.agent)}
              r={activeIndex === index ? 7 : 5}
              className="chart-point"
              onMouseEnter={() => setActiveIndex(index)}
              onFocus={() => setActiveIndex(index)}
              tabIndex="0"
            />
            <text
              x={toX(index)}
              y={height - 14}
              textAnchor="middle"
              className="chart-label"
            >
              {item.day.slice(0, 6)}
            </text>
          </g>
        ))}
        <g
          transform={`translate(${Math.min(activeX + 14, width - 166)} ${Math.max(
            activeY - 58,
            18,
          )})`}
        >
          <rect width="150" height="48" rx="6" className="chart-tooltip" />
          <text x="12" y="20" className="tooltip-title">
            {active.day}
          </text>
          <text x="12" y="37" className="tooltip-copy">
            Fixed ${active.fixed} / Agent ${active.agent}
          </text>
        </g>
      </svg>
    </div>
  );
}
