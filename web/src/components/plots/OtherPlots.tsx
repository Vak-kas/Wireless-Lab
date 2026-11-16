import type { Plot, Scalar } from "../../api";
import { t } from "../../i18n";
import { Term } from "../ui";
import { extent, fmtValue, linear } from "./scale";

/** 성상도: 점들이 또렷이 모일수록 잘 받은 것. */
export function ConstellationPlot({ plot }: { plot: Plot }) {
  const S = 420;
  const m = 36;
  const s = plot.series?.[0];
  const xs = s?.x ?? [];
  const ys = s?.y ?? [];
  const lim = Math.max(1.2, ...extent([...xs, ...ys].map(Math.abs), 0.1));
  const sx = linear(-lim, lim, m, S - m);
  const sy = linear(-lim, lim, S - m, m);
  return (
    <svg viewBox={`0 0 ${S} ${S}`} role="img" aria-label={plot.title} style={{ maxWidth: S, margin: "0 auto" }}>
      <line className="plot-gridline" x1={m} x2={S - m} y1={sy(0)} y2={sy(0)} />
      <line className="plot-gridline" x1={sx(0)} x2={sx(0)} y1={m} y2={S - m} />
      {xs.map((x, i) => (
        <circle key={i} className="plot-point" data-role="primary" cx={sx(x)} cy={sy(ys[i] ?? 0)} r={2.2} fillOpacity={0.55} />
      ))}
      {plot.annotations
        .filter((a) => a.kind === "point" && a.x !== undefined && a.y !== undefined)
        .map((a, i) => (
          <circle key={`a${i}`} cx={sx(a.x!)} cy={sy(a.y!)} r={7} className="plot-mark-box">
            <title>{a.label}</title>
          </circle>
        ))}
      <g className="plot-axis">
        <text x={S - m} y={sy(0) - 6} textAnchor="end">
          {plot.x?.label}
        </text>
        <text x={sx(0) + 6} y={m + 4}>
          {plot.y?.label}
        </text>
      </g>
    </svg>
  );
}

/** 하늘 지도: 가운데가 머리 위(고도각 90°), 바깥 원이 지평선(0°). 위쪽이 북. */
export function SkyPlot({ plot }: { plot: Plot }) {
  const S = 440;
  const R = 170;
  const c = S / 2;
  const sky = plot.sky ?? { tracks: [], markers: [] };
  const pos = (az: number, el: number): [number, number] => {
    const r = (R * (90 - Math.max(0, Math.min(90, el)))) / 90;
    const a = (az * Math.PI) / 180;
    return [c + r * Math.sin(a), c - r * Math.cos(a)];
  };
  return (
    <svg viewBox={`0 0 ${S} ${S}`} role="img" aria-label={plot.title} style={{ maxWidth: S, margin: "0 auto" }}>
      {[0, 30, 60].map((el) => (
        <circle key={el} className="plot-gridline" fill="none" cx={c} cy={c} r={(R * (90 - el)) / 90} />
      ))}
      <line className="plot-gridline" x1={c - R} x2={c + R} y1={c} y2={c} />
      <line className="plot-gridline" x1={c} x2={c} y1={c - R} y2={c + R} />
      <g className="plot-axis">
        {(["n", "e", "s", "w"] as const).map((d, i) => {
          const [x, y] = pos(i * 90, -9);
          return (
            <text key={d} x={x} y={y + 4} textAnchor="middle">
              {t(`plot.sky.${d}`)}
            </text>
          );
        })}
        {[30, 60].map((el) => (
          <text key={el} x={c + 4} y={c - (R * (90 - el)) / 90 - 3}>
            {el}°
          </text>
        ))}
      </g>
      {sky.tracks.map((tr) => (
        <path
          key={tr.name}
          className="plot-line"
          data-role="muted"
          d={tr.az_deg
            .map((az, i) => {
              const [x, y] = pos(az, tr.el_deg[i] ?? 0);
              return `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
            })
            .join("")}
        >
          <title>{tr.name}</title>
        </path>
      ))}
      {sky.markers.map((mk) => {
        const [x, y] = pos(mk.az_deg, mk.el_deg);
        return (
          <g key={mk.name}>
            <circle className="plot-mark-point" cx={x} cy={y} r={7} />
            <text className="plot-mark-label" x={x + 11} y={y + 4}>
              {mk.name}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** 표. select_key가 있으면 행을 고를 수 있다(행 전체가 버튼처럼 동작, 키보드 Enter/Space). */
export function TablePlot({
  plot,
  selected,
  onSelect,
}: {
  plot: Plot;
  selected?: Scalar;
  onSelect?: (row: Record<string, Scalar>) => void;
}) {
  const table = plot.table ?? { columns: [], rows: [] };
  const key = table.select_key;
  const selectable = Boolean(key && onSelect);
  return (
    <div className="table-wrap">
      <table className="data t-caption">
        <caption className="sr-only">{plot.title}</caption>
        <thead>
          <tr>
            {table.columns.map((col) => (
              <th key={col.key} scope="col" className={`t-caption-strong ${col.align === "right" ? "right" : ""}`}>
                <Term k={col.term}>{col.label}</Term>
                {col.unit ? ` (${col.unit})` : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, i) => {
            const isSel = selectable && row[key!] === selected;
            return (
              <tr
                key={i}
                className={selectable ? "selectable" : undefined}
                aria-selected={selectable ? isSel : undefined}
                tabIndex={selectable ? 0 : undefined}
                onClick={selectable ? () => onSelect!(row) : undefined}
                onKeyDown={
                  selectable
                    ? (e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onSelect!(row);
                        }
                      }
                    : undefined
                }
              >
                {table.columns.map((col) => (
                  <td key={col.key} className={col.align === "right" ? "right num" : undefined}>
                    {fmtValue(row[col.key])}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
