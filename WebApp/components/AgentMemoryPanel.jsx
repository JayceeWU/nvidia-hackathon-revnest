"use client";

import { StepIcon } from "./AgentIcons";

// Agent Memory panel for the Account view. Surfaces three lenses on the
// agent's persistent state: pricing rules the host set, the most recent
// actions the agent has taken, and preferences the agent has learned.
// Data shape mirrors lib/mockData.js → AGENT_MEMORY so it can be swapped
// for a real fetch of host_preferences.json and MEMORY.md later.

export default function AgentMemoryPanel({ memory }) {
  if (!memory) return null;
  const { pricing_rules, last_actions, learned_preferences } = memory;

  return (
    <section className="memory-panel">
      <header className="memory-panel-head">
        <span className="agent-badge">
          <StepIcon name="memory" width={14} height={14} />
          Agent Memory
        </span>
        <h2>What RevNest remembers about you</h2>
        <p>
          These rules and preferences persist across sessions. Closing the app
          and reopening it does not reset them.
        </p>
      </header>

      <div className="memory-grid">
        <article className="memory-card">
          <h3>Host Pricing Rules</h3>
          <dl>
            <div>
              <dt>Minimum price</dt>
              <dd>${pricing_rules.minimum_price}</dd>
            </div>
            <div>
              <dt>Maximum price</dt>
              <dd>${pricing_rules.maximum_price}</dd>
            </div>
            <div>
              <dt>Max change per action</dt>
              <dd>{pricing_rules.max_change_pct}%</dd>
            </div>
          </dl>
          <h4>Aggressive pricing when</h4>
          <ul>
            {pricing_rules.aggressive_pricing_when.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <h4>Conservative pricing when</h4>
          <ul>
            {pricing_rules.conservative_pricing_when.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </article>

        <article className="memory-card">
          <h3>Last Actions</h3>
          <ol className="memory-actions">
            {last_actions.map((action) => (
              <li key={`${action.property}-${action.date}`}>
                <strong>{action.property}</strong>
                <span className="memory-change">{action.change}</span>
                <small>
                  {action.date} · {action.status}
                </small>
                <p>{action.reason}</p>
              </li>
            ))}
          </ol>
        </article>

        <article className="memory-card">
          <h3>Learned Preferences</h3>
          <ul className="memory-learned">
            {learned_preferences.map((item) => (
              <li key={item}>
                <span className="learned-dot" />
                {item}
              </li>
            ))}
          </ul>
        </article>
      </div>
    </section>
  );
}
