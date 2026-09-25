import { useEffect, useState } from "react";
import { ApiError, api, type Insights as InsightsData } from "../api";
import PriceChart from "../components/PriceChart";
import { day, gallons, money } from "../format";

/**
 * The only screen reading the warehouse rather than the application tables.
 *
 * Everything else in this app shows what a tenant recorded. This shows what
 * it means: the same deliveries priced against the national diesel benchmark
 * the pipeline pulls from the EIA every morning.
 */

const WINDOWS = [
  { label: "13 weeks", value: 13 },
  { label: "26 weeks", value: 26 },
  { label: "52 weeks", value: 52 },
];

function cents(value: string): string {
  const n = Number(value) * 100;
  return `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(1)}¢`;
}

export default function Insights() {
  const [data, setData] = useState<InsightsData | null>(null);
  const [weeks, setWeeks] = useState(26);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .insights(weeks)
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Could not load insights.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [weeks]);

  const summary = data?.summary ?? null;
  const above = summary ? Number(summary.price_delta) >= 0 : false;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Insights</h1>
          <div className="subtle">
            Your realised diesel price against the national retail benchmark,
            rebuilt nightly from EIA open data.
          </div>
        </div>
        <div className="filters">
          <select value={weeks} onChange={(e) => setWeeks(Number(e.target.value))}>
            {WINDOWS.map((w) => (
              <option key={w.value} value={w.value}>
                {w.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {/* The warehouse is built by dbt, the app schema by Alembic. A database
          that has had one run and not the other is a normal state, not a
          failure, so it gets an explanation rather than an error. */}
      {!loading && data && !data.warehouse_available && (
        <div className="card">
          <div className="empty">
            <p>The warehouse has not been built yet.</p>
            <p className="subtle">
              Run <code>dbt build</code> in <code>analytics/</code>, or let the
              Airflow DAG run once, and this page will fill in.
            </p>
          </div>
        </div>
      )}

      {!loading && data?.warehouse_available && data.weeks.length === 0 && (
        <div className="card">
          <div className="empty">
            <p>No benchmarked deliveries in this window.</p>
            <p className="subtle">
              Only diesel carries an EIA benchmark, and only completed
              deliveries are priced against it.
            </p>
          </div>
        </div>
      )}

      {summary && data && data.weeks.length > 0 && (
        <>
          <div className="stats">
            <div className="stat">
              <div className="stat-label">Delivered</div>
              <div className="stat-value">{gallons(summary.delivered_gal)}</div>
              <div className="stat-note">
                gallons over {summary.delivery_count} deliveries
              </div>
            </div>

            <div className="stat">
              <div className="stat-label">Your average price</div>
              <div className="stat-value">${Number(summary.avg_price).toFixed(4)}</div>
              <div className="stat-note">per gallon, volume-weighted</div>
            </div>

            <div className="stat">
              <div className="stat-label">Against market</div>
              <div className={`stat-value ${above ? "up" : "down"}`}>
                {cents(summary.price_delta)}
              </div>
              <div className="stat-note">
                benchmark ${Number(summary.market_price).toFixed(4)}
              </div>
            </div>

            <div className="stat">
              <div className="stat-label">Margin vs benchmark</div>
              <div className={`stat-value ${above ? "up" : "down"}`}>
                {money(summary.margin_vs_benchmark)}
              </div>
              <div className="stat-note">
                {day(summary.first_week)} – {day(summary.latest_week)}
              </div>
            </div>
          </div>

          <div className="card">
            <PriceChart weeks={data.weeks} />
          </div>

          <div className="card">
            <table>
              <thead>
                <tr>
                  <th>Week of</th>
                  <th className="num">Deliveries</th>
                  <th className="num">Gallons</th>
                  <th className="num">Your price</th>
                  <th className="num">Market</th>
                  <th className="num">Delta</th>
                  <th className="num">Margin vs market</th>
                </tr>
              </thead>
              <tbody>
                {[...data.weeks].reverse().map((week) => {
                  const up = Number(week.price_delta) >= 0;
                  return (
                    <tr key={week.week_start}>
                      <td className="num">{day(week.week_start)}</td>
                      <td className="num">{week.delivery_count}</td>
                      <td className="num">{gallons(week.delivered_gal)}</td>
                      <td className="num">${Number(week.avg_price).toFixed(4)}</td>
                      <td className="num subtle">
                        ${Number(week.market_price).toFixed(4)}
                      </td>
                      <td className={`num ${up ? "up" : "down"}`}>
                        {cents(week.price_delta)}
                      </td>
                      <td className={`num ${up ? "up" : "down"}`}>
                        {money(week.margin_vs_benchmark)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <p className="subtle footnote">
            Benchmark: EIA weekly US No.&nbsp;2 diesel retail price, all
            sellers. Each delivery is priced against the most recent week
            published on or before its delivery date. Non-diesel products are
            excluded here — they move on different markets.
          </p>
        </>
      )}
    </>
  );
}
