"use client";

import { useEffect, useMemo, useState } from "react";

function formatDate(date) {
  return date.toISOString().slice(0, 10);
}

function monthStart(date) {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

function addMonths(date, count) {
  return new Date(date.getFullYear(), date.getMonth() + count, 1);
}

function monthDates(date) {
  const start = monthStart(date);
  const end = new Date(start.getFullYear(), start.getMonth() + 1, 0);
  const dates = [];
  for (let day = 1; day <= end.getDate(); day += 1) {
    dates.push(formatDate(new Date(start.getFullYear(), start.getMonth(), day)));
  }
  return dates;
}

function toPriceNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function dollars(value) {
  return `$${Number(value).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function buildChartData(roomType, dates, drafts) {
  if (!roomType) {
    return [];
  }

  return dates.map((date) => {
    const key = `${roomType.id}:${date}`;
    const draft = drafts[key];
    const value = draft ?? roomType.prices[date] ?? "";
    return {
      date,
      label: date.slice(5),
      price: toPriceNumber(value),
      changed: draft !== undefined,
    };
  });
}

function PriceLineChart({ points }) {
  const validPoints = points.filter((point) => point.price !== null);
  if (validPoints.length === 0) {
    return <div className="emptyChart">No prices available for this month.</div>;
  }

  const width = 920;
  const height = 300;
  const padding = { top: 28, right: 28, bottom: 42, left: 64 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const rawMin = Math.min(...validPoints.map((point) => point.price));
  const rawMax = Math.max(...validPoints.map((point) => point.price));
  const minPrice = Math.max(0, Math.floor((rawMin - 25) / 25) * 25);
  const maxPrice = Math.ceil((rawMax + 25) / 25) * 25;
  const priceRange = Math.max(1, maxPrice - minPrice);
  const xStep = points.length > 1 ? chartWidth / (points.length - 1) : 0;

  function xFor(index) {
    return padding.left + index * xStep;
  }

  function yFor(price) {
    return padding.top + ((maxPrice - price) / priceRange) * chartHeight;
  }

  const linePoints = points
    .map((point, index) => {
      if (point.price === null) {
        return null;
      }
      return { ...point, x: xFor(index), y: yFor(point.price), index };
    })
    .filter(Boolean);

  const path = linePoints
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
    .join(" ");

  const yTicks = [maxPrice, Math.round((maxPrice + minPrice) / 2), minPrice];
  const labelIndexes = [0, Math.floor((points.length - 1) / 2), points.length - 1].filter(
    (value, index, values) => values.indexOf(value) === index
  );

  return (
    <svg className="priceChart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Monthly room price line chart">
      {yTicks.map((tick) => {
        const y = yFor(tick);
        return (
          <g key={tick}>
            <line className="chartGrid" x1={padding.left} x2={width - padding.right} y1={y} y2={y} />
            <text className="chartTick" x={padding.left - 12} y={y + 4} textAnchor="end">
              {dollars(tick)}
            </text>
          </g>
        );
      })}
      <path className="chartLine" d={path} />
      {linePoints.map((point) => (
        <g key={point.date}>
          <circle className={point.changed ? "chartPoint changed" : "chartPoint"} cx={point.x} cy={point.y} r={point.changed ? 5 : 3.5} />
          <title>{`${point.date}: ${dollars(point.price)}`}</title>
        </g>
      ))}
      {labelIndexes.map((index) => (
        <text key={points[index].date} className="chartTick" x={xFor(index)} y={height - 14} textAnchor="middle">
          {points[index].label}
        </text>
      ))}
    </svg>
  );
}

function LoginForm({ onLogin }) {
  const [username, setUsername] = useState("manager");
  const [password, setPassword] = useState("password123");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");

    const response = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });
    const body = await response.json();
    setBusy(false);

    if (!response.ok) {
      setError(body.error || "Login failed");
      return;
    }

    onLogin(body.user);
  }

  return (
    <main className="shell">
      <form className="login" onSubmit={submit}>
        <h1>MockHotel</h1>
        <label className="field">
          <span>Username</span>
          <input value={username} onChange={(event) => setUsername(event.target.value)} />
        </label>
        <label className="field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {error ? <div className="error">{error}</div> : null}
        <button disabled={busy}>{busy ? "Signing in" : "Sign in"}</button>
      </form>
    </main>
  );
}

export default function Home() {
  const [user, setUser] = useState(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [month, setMonth] = useState(() => monthStart(new Date()));
  const [roomTypes, setRoomTypes] = useState([]);
  const [selectedRoomTypeId, setSelectedRoomTypeId] = useState("");
  const [drafts, setDrafts] = useState({});
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const dates = useMemo(() => monthDates(month), [month]);
  const selectedRoomType = useMemo(() => {
    return roomTypes.find((roomType) => roomType.id === selectedRoomTypeId) || roomTypes[0] || null;
  }, [roomTypes, selectedRoomTypeId]);
  const visibleDates = useMemo(() => {
    if (!selectedRoomType) {
      return dates;
    }
    return dates.filter((date) => {
      const key = `${selectedRoomType.id}:${date}`;
      return selectedRoomType.prices[date] !== undefined || drafts[key] !== undefined;
    });
  }, [selectedRoomType, dates, drafts]);
  const chartData = useMemo(() => buildChartData(selectedRoomType, visibleDates, drafts), [selectedRoomType, visibleDates, drafts]);
  const validPrices = chartData.map((point) => point.price).filter((price) => price !== null);
  const selectedDraftCount = selectedRoomType
    ? Object.keys(drafts).filter((key) => key.startsWith(`${selectedRoomType.id}:`)).length
    : 0;
  const averagePrice =
    validPrices.length > 0
      ? validPrices.reduce((total, price) => total + price, 0) / validPrices.length
      : null;
  const minPrice = validPrices.length > 0 ? Math.min(...validPrices) : null;
  const maxPrice = validPrices.length > 0 ? Math.max(...validPrices) : null;

  useEffect(() => {
    async function loadSession() {
      const response = await fetch("/api/session");
      const body = await response.json();
      setUser(body.user);
      setCheckingSession(false);
    }
    loadSession();
  }, []);

  useEffect(() => {
    if (!user) {
      return;
    }

    async function loadPrices() {
      setLoading(true);
      setError("");
      setStatus("");
      const start = dates[0];
      const end = dates[dates.length - 1];
      const response = await fetch(`/api/prices?start=${start}&end=${end}`);
      const body = await response.json();
      setLoading(false);

      if (!response.ok) {
        setError(body.error || "Could not load prices");
        return;
      }

      const nextRoomTypes = body.roomTypes || [];
      setRoomTypes(nextRoomTypes);
      setSelectedRoomTypeId((current) => {
        if (nextRoomTypes.some((roomType) => roomType.id === current)) {
          return current;
        }
        return nextRoomTypes[0]?.id || "";
      });
      setDrafts({});
    }

    loadPrices();
  }, [user, dates]);

  function draftKey(roomTypeId, date) {
    return `${roomTypeId}:${date}`;
  }

  function priceFor(roomType, date) {
    const key = draftKey(roomType.id, date);
    return drafts[key] ?? roomType.prices[date] ?? "";
  }

  function updateDraft(roomTypeId, date, value) {
    setDrafts((current) => ({ ...current, [draftKey(roomTypeId, date)]: value }));
  }

  async function saveChanges() {
    const updates = Object.entries(drafts)
      .filter(([, price]) => price !== "")
      .map(([key, price]) => {
        const [roomTypeId, date] = key.split(":");
        return { roomTypeId, date, price: Number(price) };
      });

    if (updates.length === 0) {
      setStatus("No changes to save");
      return;
    }

    setLoading(true);
    setError("");
    const response = await fetch("/api/prices", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ updates })
    });
    const body = await response.json();
    setLoading(false);

    if (!response.ok) {
      setError(body.error || "Could not save prices");
      return;
    }

    setStatus(`Saved ${body.count} room type price changes`);
    const start = dates[0];
    const end = dates[dates.length - 1];
    const refreshed = await fetch(`/api/prices?start=${start}&end=${end}`);
    const refreshedBody = await refreshed.json();
    const nextRoomTypes = refreshedBody.roomTypes || [];
    setRoomTypes(nextRoomTypes);
    setSelectedRoomTypeId((current) => {
      if (nextRoomTypes.some((roomType) => roomType.id === current)) {
        return current;
      }
      return nextRoomTypes[0]?.id || "";
    });
    setDrafts({});
  }

  async function logout() {
    await fetch("/api/logout", { method: "POST" });
    setUser(null);
    setRoomTypes([]);
    setSelectedRoomTypeId("");
    setDrafts({});
  }

  if (checkingSession) {
    return <main className="shell">Loading</main>;
  }

  if (!user) {
    return <LoginForm onLogin={setUser} />;
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand">
          <h1>MockHotel Price Manager</h1>
          <p>{user.username} can revise Dream Inn daily room-type prices.</p>
        </div>
        <button className="secondary" onClick={logout}>
          Sign out
        </button>
      </header>

      <section className="toolbar">
        <div className="selectors">
          <label className="selectField">
            <span>Room type</span>
            <select value={selectedRoomType?.id || ""} onChange={(event) => setSelectedRoomTypeId(event.target.value)}>
              {roomTypes.map((roomType) => (
                <option key={roomType.id} value={roomType.id}>
                  {roomType.name}
                </option>
              ))}
            </select>
          </label>
          <div className="monthControls" aria-label="Month selector">
            <button type="button" aria-label="Previous month" onClick={() => setMonth((current) => addMonths(current, -1))}>
              {"<"}
            </button>
            <strong>
              {month.toLocaleString("en", { month: "long" })} {month.getFullYear()}
            </strong>
            <button type="button" aria-label="Next month" onClick={() => setMonth((current) => addMonths(current, 1))}>
              {">"}
            </button>
          </div>
        </div>
        <div className="actions">
          <span className="status">
            {loading ? "Working" : status || `${Object.keys(drafts).length} unsaved changes`}
          </span>
          <button onClick={saveChanges} disabled={loading}>
            Save prices
          </button>
        </div>
      </section>

      {error ? <div className="toolbar error">{error}</div> : null}

      {selectedRoomType ? (
        <>
          <section className="overview">
            <div className="roomSummary">
              <div>
                <span className="eyebrow">Selected room</span>
                <h2>{selectedRoomType.name}</h2>
              </div>
              <div className="summaryMeta">
                <span>{selectedRoomType.roomCount} rooms</span>
                <span>{selectedRoomType.bed || "Bed pending"}</span>
                <span>Max {selectedRoomType.capacity || "?"}</span>
              </div>
            </div>
            <div className="metricStrip">
              <div className="metric">
                <span>Average</span>
                <strong>{averagePrice === null ? "N/A" : dollars(averagePrice)}</strong>
              </div>
              <div className="metric">
                <span>Low</span>
                <strong>{minPrice === null ? "N/A" : dollars(minPrice)}</strong>
              </div>
              <div className="metric">
                <span>High</span>
                <strong>{maxPrice === null ? "N/A" : dollars(maxPrice)}</strong>
              </div>
              <div className="metric">
                <span>Edited</span>
                <strong>{selectedDraftCount}</strong>
              </div>
            </div>
          </section>

          <section className="chartPanel">
            <div className="panelHeader">
              <div>
                <span className="eyebrow">Monthly price curve</span>
                <h2>
                  {month.toLocaleString("en", { month: "long" })} {month.getFullYear()}
                </h2>
              </div>
              <div className="legend">
                <span className="legendLine" />
                Price
                <span className="legendDot" />
                Edited
              </div>
            </div>
            <PriceLineChart points={chartData} />
          </section>

          <section className="tableWrap">
            <table className="priceTable">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Day</th>
                  <th>Price</th>
                </tr>
              </thead>
              <tbody>
                {visibleDates.map((date) => {
                  const key = draftKey(selectedRoomType.id, date);
                  const dayName = new Date(`${date}T00:00:00`).toLocaleString("en", { weekday: "short" });
                  return (
                    <tr key={key}>
                      <td>{date}</td>
                      <td>{dayName}</td>
                      <td>
                        <input
                          className={`priceInput ${drafts[key] === undefined ? "" : "changed"}`}
                          inputMode="decimal"
                          value={priceFor(selectedRoomType, date)}
                          onChange={(event) => updateDraft(selectedRoomType.id, date, event.target.value)}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        </>
      ) : (
        <section className="emptyState">No room types found for this month.</section>
      )}
    </main>
  );
}
