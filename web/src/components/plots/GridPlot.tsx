import { useMemo, useState } from "react";
import type { Plot, PlotAnnotation } from "../../api";
import { useStore } from "../../state/store";

const W = 880;
const H = 420;
const M = { l: 56, r: 16, t: 16, b: 44 };
const MAX_ROWS = 120;
const MAX_COLS = 160;

interface Cell {
  r: number;
  c: number;
  v: number;
  cat: number;
}

/** 큰 격자는 묶어서(최댓값) 줄인다. 범주는 묶음 안에서 가장 센 칸의 것을 따른다. */
function reduce(plot: Plot): { rows: number; cols: number; cells: Cell[]; rf: number; cf: number } {
  const g = plot.grid!;
  const rf = Math.ceil(g.rows / MAX_ROWS);
  const cf = Math.ceil(g.cols / MAX_COLS);
  const rows = Math.ceil(g.rows / rf);
  const cols = Math.ceil(g.cols / cf);
  const cells: Cell[] = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      let v = 0;
      let cat = -1;
      for (let i = r * rf; i < Math.min(g.rows, (r + 1) * rf); i++) {
        for (let j = c * cf; j < Math.min(g.cols, (c + 1) * cf); j++) {
          const x = g.values[i]?.[j] ?? 0;
          const k = g.categories?.[i]?.[j] ?? -1;
          if (x > v || (cat < 0 && k >= 0)) {
            v = Math.max(v, x);
            if (k >= 0 || cat < 0) cat = k;
          }
        }
      }
      cells.push({ r, c, v, cat });
    }
  }
  return { rows, cols, cells, rf, cf };
}

/** 자원 격자·워터폴. 세기는 투명도, 영역(PSS, SSS …)은 색과 범례로 구분한다. 범례에 올리면 그 영역만 남는다. */
export function GridPlot({ plot }: { plot: Plot }) {
  const { glossary } = useStore();
  const [focusCat, setFocusCat] = useState<number | null>(null);
  const [note, setNote] = useState<PlotAnnotation | null>(null);
  const g = plot.grid!;
  const { rows, cols, cells, rf, cf } = useMemo(() => reduce(plot), [plot]);
  const cw = (W - M.l - M.r) / cols;
  const ch = (H - M.t - M.b) / rows;
  const names = g.category_names ?? [];
  const x = (c: number) => M.l + c * cw;
  const y = (r: number) => M.t + (rows - 1 - r) * ch; // 낮은 주파수가 아래
  const colStep = Math.max(1, Math.ceil(cols / 14));
  const rowStep = Math.max(1, Math.ceil(rows / 6));

  const describe = (i: number): string => {
    const fromAnnotation = plot.annotations.find((a) => a.category === i)?.description;
    const term = g.category_terms?.[i];
    return fromAnnotation ?? (term ? glossary[term]?.short : undefined) ?? "";
  };

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={plot.title} className={focusCat === null ? "" : "grid-dim"}>
        {cells.map((cell) => (
          <rect
            key={`${cell.r}-${cell.c}`}
            className="grid-cell"
            data-cat={cell.cat}
            data-on={focusCat !== null && cell.cat === focusCat ? "true" : undefined}
            x={x(cell.c)}
            y={y(cell.r)}
            width={Math.max(0.5, cw - (cw > 6 ? 1 : 0))}
            height={Math.max(0.5, ch - (ch > 3 ? 0.5 : 0))}
            fillOpacity={Math.max(0.04, Math.min(1, cell.v))}
          />
        ))}
        {plot.annotations
          .filter((a) => a.kind === "box" && a.x0 !== undefined && a.x1 !== undefined && a.y0 !== undefined && a.y1 !== undefined)
          .map((a, i) => {
            const bx = x(a.x0! / cf);
            const by = y(a.y1! / rf);
            const bw = ((a.x1! - a.x0! + 1) / cf) * cw;
            const bh = ((a.y1! - a.y0! + 1) / rf) * ch;
            return (
              <g key={i}>
                <rect className="plot-mark-box" x={bx} y={by} width={bw} height={bh} rx={3} />
                <rect
                  className="plot-hit"
                  tabIndex={0}
                  aria-label={`${a.label}. ${a.description ?? ""}`}
                  x={bx}
                  y={by}
                  width={bw}
                  height={bh}
                  onMouseEnter={() => setNote(a)}
                  onMouseLeave={() => setNote(null)}
                  onFocus={() => setNote(a)}
                  onBlur={() => setNote(null)}
                />
              </g>
            );
          })}
        <g className="plot-axis">
          {Array.from({ length: cols }, (_, c) => c)
            .filter((c) => c % colStep === 0)
            .map((c) => (
              <text key={`c${c}`} x={x(c) + cw / 2} y={H - M.b + 16} textAnchor="middle">
                {(g.col_start ?? 0) + c * cf}
              </text>
            ))}
          {Array.from({ length: rows }, (_, r) => r)
            .filter((r) => r % rowStep === 0)
            .map((r) => (
              <text key={`r${r}`} x={M.l - 8} y={y(r) + ch / 2 + 4} textAnchor="end">
                {(g.row_start ?? 0) + r * rf}
              </text>
            ))}
          <text x={(M.l + W - M.r) / 2} y={H - 6} textAnchor="middle">
            {g.col_label ?? plot.x?.label ?? ""}
          </text>
          <text transform={`translate(12 ${(M.t + H - M.b) / 2}) rotate(-90)`} textAnchor="middle">
            {g.row_label ?? plot.y?.label ?? ""}
          </text>
        </g>
      </svg>
      {names.length > 0 && (
        <ul className="legend t-caption">
          {names.map((name, i) => (
            <li key={name}>
              <button
                type="button"
                aria-pressed={focusCat === i}
                onMouseEnter={() => setFocusCat(i)}
                onMouseLeave={() => setFocusCat(null)}
                onFocus={() => setFocusCat(i)}
                onBlur={() => setFocusCat(null)}
              >
                <span className="swatch" data-cat={i} aria-hidden="true" />
                {name}
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="plot-note t-caption" aria-live="polite">
        {focusCat !== null ? `${names[focusCat] ?? ""} — ${describe(focusCat)}` : note ? `${note.label} — ${note.description ?? ""}` : ""}
      </p>
    </div>
  );
}
