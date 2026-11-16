import { t } from "../../i18n";

/** 그림 공용 계산: 눈금, 축 범위, 숫자 표기. */

export function extent(values: number[], pad = 0.05): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of values) {
    if (!Number.isFinite(v)) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (lo === Infinity) return [0, 1];
  if (lo === hi) return [lo - 1, hi + 1];
  const d = (hi - lo) * pad;
  return [lo - d, hi + d];
}

/** 보기 좋은 눈금 값 (1, 2, 5 × 10^n 간격). */
export function ticks(lo: number, hi: number, count = 5): number[] {
  const span = hi - lo;
  if (!(span > 0)) return [lo];
  const raw = span / count;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Number(v.toPrecision(12)));
  return out;
}

export function linear(d0: number, d1: number, r0: number, r1: number): (v: number) => number {
  const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0);
  return (v) => r0 + (v - d0) * k;
}

/** 축 단위에 맞춰 큰 수를 줄여 쓴다 (Hz → MHz 등). */
export function axisScale(unit: string | undefined, lo: number, hi: number): { div: number; unit: string } {
  const max = Math.max(Math.abs(lo), Math.abs(hi));
  if (unit === "Hz") {
    if (max >= 1e9) return { div: 1e6, unit: "MHz" };
    if (max >= 1e6) return { div: 1e6, unit: "MHz" };
    if (max >= 1e4) return { div: 1e3, unit: "kHz" };
  }
  return { div: 1, unit: unit ?? "" };
}

export function fmt(v: number): string {
  if (!Number.isFinite(v)) return "–";
  const a = Math.abs(v);
  if (a !== 0 && (a >= 1e6 || a < 1e-3)) return v.toExponential(2);
  return String(Number(v.toPrecision(6)));
}

/** 값 카드용 숫자 표기: 정수는 그대로, 실수는 유효숫자 6자리까지. */
export function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return "–";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(Number(v.toPrecision(7)));
  if (typeof v === "boolean") return t(v ? "common.yes" : "common.no");
  if (Array.isArray(v)) return v.map(fmtValue).join(", ");
  return String(v);
}
