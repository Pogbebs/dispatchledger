import { useState } from "react";
import type { WeeklyPricePosition } from "../api";

/**
 * Two lines: what this tenant realised per gallon, against the national
 * benchmark for the same week.
 *
 * Drawn as plain SVG rather than pulling in a charting library. Two series
 * and a hover readout is not enough to justify a dependency the size of most
 * of this application, and the arithmetic below is the whole of what such a
 * library would do for us here.
 *
 * Both series are volume-weighted upstream in the warehouse, so the gap
 * between the lines is directly the money in `margin_vs_benchmark` -- if one
 * were a plain average the distance would be visually persuasive and
 * arithmetically meaningless.
 */

const W = 760;
const H = 280;
const PAD = { top: 18, right: 18, bottom: 34, left: 56 };
const INNER_W = W - PAD.left - PAD.right;
const INNER_H = H - PAD.top - PAD.bottom;

export default function PriceChart({ weeks }: { weeks: WeeklyPricePosition[] }) {
  const [hover, setHover] = useState<number | null>(null);

  const mine = weeks.map((w) => Number(w.avg_price));
  const market = weeks.map((w) => Number(w.market_price));
  const all = [...mine, ...market];

  // A little headroom either side, so the lines never sit on the axis. Fuel
  // prices move in cents on a base of dollars, so a zero-based axis would
  // flatten the whole series into one indistinguishable band -- the gap
  // between the two lines is the subject here, not the distance from zero.
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const span = hi - lo || 0.1;
  const min = lo - span * 0.15;
  const max = hi + span * 0.15;

  const x = (i: number) =>
    PAD.left + (weeks.length === 1 ? INNER_W / 2 : (i * INNER_W) / (weeks.length - 1));
  const y = (v: number) => PAD.top + INNER_H * (1 - (v - min) / (max - min));

  const path = (values: number[]) =>
    values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => min + (max - min) * t);

  // Roughly six labels regardless of window length, so a 52-week view does
  // not turn the axis into a smear.
  const labelEvery = Math.max(1, Math.ceil(weeks.length / 6));

  function onMove(event: React.MouseEvent<SVGSVGElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    // The SVG is scaled to its container, so the pointer has to be converted
    // back into viewBox units before it means anything.
    const px = ((event.clientX - box.left) / box.width) * W;
    const ratio = (px - PAD.left) / INNER_W;
    const index = Math.round(ratio * (weeks.length - 1));
    setHover(index >= 0 && index < weeks.length ? index : null);
  }

  const active = hover === null ? null : weeks[hover];

  return (
    <div className="chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="Realised price against the national diesel benchmark, by week"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        {ticks.map((value, i) => (
          <g key={i}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(value)}
              y2={y(value)}
              className="chart-grid"
            />
            <text x={PAD.left - 10} y={y(value) + 4} className="chart-axis" textAnchor="end">
              ${value.toFixed(2)}
            </text>
          </g>
        ))}

        {weeks.map((week, i) =>
          i % labelEvery === 0 ? (
            <text key={week.week_start} x={x(i)} y={H - 12} className="chart-axis" textAnchor="middle">
              {new Date(`${week.week_start}T00:00:00`).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
              })}
            </text>
          ) : null,
        )}

        <path d={path(market)} className="chart-line chart-market" />
        <path d={path(mine)} className="chart-line chart-mine" />

        {hover !== null && (
          <>
            <line
              x1={x(hover)}
              x2={x(hover)}
              y1={PAD.top}
              y2={PAD.top + INNER_H}
              className="chart-guide"
            />
            <circle cx={x(hover)} cy={y(market[hover])} r={4} className="chart-dot chart-market" />
            <circle cx={x(hover)} cy={y(mine[hover])} r={4} className="chart-dot chart-mine" />
          </>
        )}
      </svg>

      <div className="chart-legend">
        <span>
          <i className="swatch swatch-mine" /> Your price
        </span>
        <span>
          <i className="swatch swatch-market" /> National benchmark
        </span>
        <span className="chart-readout">
          {active ? (
            <>
              Week of{" "}
              {new Date(`${active.week_start}T00:00:00`).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
              })}
              {" · "}you ${Number(active.avg_price).toFixed(4)}
              {" · "}market ${Number(active.market_price).toFixed(4)}
              {" · "}
              <strong className={Number(active.price_delta) >= 0 ? "up" : "down"}>
                {Number(active.price_delta) >= 0 ? "+" : "−"}
                {Math.abs(Number(active.price_delta) * 100).toFixed(1)}¢
              </strong>
            </>
          ) : (
            "Hover the chart for a week"
          )}
        </span>
      </div>
    </div>
  );
}
