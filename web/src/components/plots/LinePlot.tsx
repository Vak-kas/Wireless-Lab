import { useMemo, useState } from "react";
import type { Plot, PlotAnnotation } from "../../api";
import { axisScale, extent, fmt, linear, ticks } from "./scale";

const W = 880;
const H = 360;
const M = { l: 64, r: 20, t: 28, b: 48 };
const ROLES = ["primary", "accent", "muted"] as const;

/** 선 그림: spectrum, correlation, timeseries. 강조 영역에 올리거나 초점을 주면 아래에 설명이 뜬다. */
export function LinePlot({ plot }: { plot: Plot }) {
  const [note, setNote] = useState<PlotAnnotation | null>(null);
  const series = useMemo(() => plot.series ?? [], [plot.series]);

  const view = useMemo(() => {
    const xs = series.flatMap((s) => s.x ?? []);
    const ys = series.flatMap((s) => s.y ?? []);
    const hasBars = series.some((s) => s.mode === "bars");
    const [x0, x1] = plot.x?.min !== undefined && plot.x.max !== undefined ? [plot.x.min, plot.x.max] : extent(xs, hasBars ? 0.08 : 0);
    let [y0, y1] = extent(ys, 0.08);
    if (hasBars) y0 = Math.min(0, y0);
    if (plot.y?.min !== undefined) y0 = plot.y.min;
    if (plot.y?.max !== undefined) y1 = plot.y.max;
    return { x0, x1, y0, y1 };
  }, [series, plot.x, plot.y]);

  const sx = linear(view.x0, view.x1, M.l, W - M.r);
  const sy = linear(view.y0, view.y1, H - M.b, M.t);
  const xUnit = axisScale(plot.x?.unit, view.x0, view.x1);
  const multi = series.length > 1;

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={plot.title}>
        <g className="plot-axis">
          {ticks(view.y0, view.y1, 5).map((v) => (
            <g key={`y${v}`}>
              <line className="plot-gridline" x1={M.l} x2={W - M.r} y1={sy(v)} y2={sy(v)} />
              <text x={M.l - 8} y={sy(v) + 4} textAnchor="end">
                {fmt(v)}
              </text>
            </g>
          ))}
          {ticks(view.x0, view.x1, 6).map((v) => (
            <text key={`x${v}`} x={sx(v)} y={H - M.b + 18} textAnchor="middle">
              {fmt(v / xUnit.div)}
            </text>
          ))}
          {plot.x && (
            <text x={(M.l + W - M.r) / 2} y={H - 8} textAnchor="middle">
              {plot.x.label}
              {xUnit.unit ? ` (${xUnit.unit})` : ""}
            </text>
          )}
          {plot.y && (
            <text transform={`translate(14 ${(M.t + H - M.b) / 2}) rotate(-90)`} textAnchor="middle">
              {plot.y.label}
              {plot.y.unit ? ` (${plot.y.unit})` : ""}
            </text>
          )}
        </g>

        {plot.annotations
          .filter((a) => a.kind === "region")
          .map((a, i) => (
            <rect
              key={`r${i}`}
              className="plot-mark-region"
              x={sx(a.x0 ?? view.x0)}
              width={Math.max(0, sx(a.x1 ?? view.x1) - sx(a.x0 ?? view.x0))}
              y={M.t}
              height={H - M.b - M.t}
            />
          ))}

        {series.map((s, i) => {
          const role = s.role ?? ROLES[Math.min(i, ROLES.length - 1)];
          const xs = s.x ?? [];
          const ysr = s.y ?? [];
          if (s.mode === "bars") {
            const bw = Math.max(4, ((W - M.l - M.r) / Math.max(1, xs.length)) * 0.6);
            return xs.map((x, j) => {
              const y = ysr[j] ?? 0;
              return (
                <rect
                  key={`${s.name}${j}`}
                  className="plot-bar"
                  data-role={role}
                  x={sx(x) - bw / 2}
                  width={bw}
                  y={Math.min(sy(y), sy(0))}
                  height={Math.abs(sy(y) - sy(0))}
                />
              );
            });
          }
          if (s.mode === "points") {
            return xs.map((x, j) => (
              <circle key={`${s.name}${j}`} className="plot-point" data-role={role} cx={sx(x)} cy={sy(ysr[j] ?? 0)} r={2.5} />
            ));
          }
          const d = xs
            .map((x, j) => `${j ? "L" : "M"}${sx(x).toFixed(1)} ${sy(ysr[j] ?? 0).toFixed(1)}`)
            .join("");
          return <path key={s.name} className="plot-line" data-role={role} d={d} />;
        })}

        {plot.annotations.map((a, i) => {
          const events = {
            onMouseEnter: () => setNote(a),
            onMouseLeave: () => setNote(null),
            onFocus: () => setNote(a),
            onBlur: () => setNote(null),
          };
          if (a.kind === "vline" && a.x !== undefined) {
            const x = sx(a.x);
            // category 1 = 보조 표시(예: 신호가 없는 후보 자리). 흐리게 긋고 이름은 올렸을 때만 보여준다.
            const minor = a.category === 1;
            return (
              <g key={i}>
                <line className={minor ? "plot-mark-line minor" : "plot-mark-line"} x1={x} x2={x} y1={M.t} y2={H - M.b} />
                {!minor && (
                  <text className="plot-mark-label" x={x} y={M.t - 8} textAnchor="middle">
                    {a.label}
                  </text>
                )}
                <rect className="plot-hit" tabIndex={0} aria-label={`${a.label}. ${a.description ?? ""}`} x={x - 12} width={24} y={0} height={H - M.b} {...events} />
              </g>
            );
          }
          if (a.kind === "hline" && a.y !== undefined) {
            return (
              <g key={i}>
                <line className="plot-mark-line" x1={M.l} x2={W - M.r} y1={sy(a.y)} y2={sy(a.y)} />
                <text className="plot-mark-label" x={W - M.r} y={sy(a.y) - 6} textAnchor="end">
                  {a.label}
                </text>
              </g>
            );
          }
          if (a.kind === "point" && a.x !== undefined && a.y !== undefined) {
            return (
              <g key={i}>
                <circle className="plot-mark-point" cx={sx(a.x)} cy={sy(a.y)} r={5} />
                <text className="plot-mark-label" x={sx(a.x) + 9} y={sy(a.y) - 8}>
                  {a.label}
                </text>
                <circle className="plot-hit" tabIndex={0} aria-label={`${a.label}. ${a.description ?? ""}`} cx={sx(a.x)} cy={sy(a.y)} r={16} {...events} />
              </g>
            );
          }
          if (a.kind === "region") {
            const x0 = sx(a.x0 ?? view.x0);
            const x1 = sx(a.x1 ?? view.x1);
            return (
              <g key={i}>
                <text className="plot-mark-label" x={(x0 + x1) / 2} y={M.t - 8} textAnchor="middle">
                  {a.label}
                </text>
                <rect className="plot-hit" tabIndex={0} aria-label={`${a.label}. ${a.description ?? ""}`} x={x0} width={Math.max(0, x1 - x0)} y={M.t} height={H - M.b - M.t} {...events} />
              </g>
            );
          }
          return null;
        })}
      </svg>
      {multi && (
        <ul className="legend t-caption" aria-label={plot.title}>
          {series.map((s, i) => (
            <li key={s.name} className="row">
              <span className="swatch" data-role={s.role ?? ROLES[Math.min(i, ROLES.length - 1)]} aria-hidden="true" />
              {s.name}
            </li>
          ))}
        </ul>
      )}
      <p className="plot-note t-caption" aria-live="polite">
        {note ? `${note.label} — ${note.description ?? ""}` : ""}
      </p>
    </div>
  );
}
