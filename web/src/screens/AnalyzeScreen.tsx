import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import type { AnalyzeBits, AnalyzeDetail, AnalyzeFile, AnalyzeGrid, AnalyzeOverview, AnalyzeSource } from "../api";
import { SubNav, Tile, TileHead } from "../components/layout";
import { Badge, Button, Field } from "../components/ui";
import { t } from "../i18n";
import { useStore } from "../state/store";

/**
 * 신호 분석: 저장해 둔 I/Q 파일을 열어 뜯어본다. 장비는 쓰지 않는다.
 *
 * 화면의 순서가 곧 분석의 순서다.
 *   1. 파일 고르기      최근 녹화 목록, 파일 고르는 창, 경로 적기
 *   2. 전체 보기        파일 전체의 스펙트로그램과 시간에 따른 세기, 찾은 버스트 목록. 그림을 끌어 구간을 고른다
 *   3. 구간 자세히      스펙트로그램·스펙트럼·시간 파형·순간 주파수·성상도와 잰 값. 스펙트럼을 눌러 주파수를 고르면
 *                       그 신호만 남기고 본다(가운데로 옮긴 뒤 좁게 거른다)
 *
 * 계산은 전부 서버(analyze.py)가 한다. 여기서는 구간과 주파수를 정해 묻고, 받은 숫자를 그린다.
 * 그림은 캔버스에 그리고 색은 글자색 토큰을 쓴다. 고른 구간과 주파수 띠는 그림 위에 겹친 칸으로 보여 준다.
 */

const num = (v: number, digits = 3) => Number(v.toFixed(digits)).toString();
const mhz = (hz: number) => num(hz / 1e6, 4);
/** 시간을 읽기 좋은 단위로: 1초 미만은 ms, 1 ms 미만은 µs */
const span = (s: number) => (s >= 1 ? `${num(s, 3)} s` : s >= 1e-3 ? `${num(s * 1e3, 3)} ms` : `${num(s * 1e6, 1)} µs`);
const khz = (hz: number) => `${num(hz / 1e3, 1)} kHz`;

/** 캔버스의 글자색(토큰의 계산된 값). 그릴 때는 이 색에 투명도(globalAlpha)만 바꿔 쓴다 */
const inkCss = (el: HTMLElement) => getComputedStyle(el).color;
/** 같은 색을 [r, g, b] 숫자로(점 하나하나의 진하기를 직접 채우는 스펙트로그램용) */
function inkOf(el: HTMLElement): [number, number, number] {
  const m = inkCss(el).match(/\d+(\.\d+)?/g) ?? ["0", "0", "0"];
  return [Number(m[0]), Number(m[1]), Number(m[2])];
}
const noCanvas = () => navigator.userAgent.includes("jsdom"); // 테스트 환경에는 캔버스 그리기가 없다

/** 그림 위에서 가로로 끌어 구간을 고른다. 0 ~ 1 의 비율로 알려 준다. 끌지 않고 누르기만 하면 onPick */
function useDrag(onSelect?: (a: number, b: number) => void, onPick?: (at: number) => void) {
  const from = useRef<number | null>(null);
  const [live, setLive] = useState<[number, number] | null>(null);
  const at = (e: MouseEvent<HTMLElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    return box.width > 0 ? Math.min(1, Math.max(0, (e.clientX - box.left) / box.width)) : 0;
  };
  return {
    live,
    handlers: {
      onMouseDown: (e: MouseEvent<HTMLElement>) => {
        from.current = at(e);
        setLive([from.current, from.current]);
      },
      onMouseMove: (e: MouseEvent<HTMLElement>) => {
        if (from.current !== null) setLive([Math.min(from.current, at(e)), Math.max(from.current, at(e))]);
      },
      onMouseUp: (e: MouseEvent<HTMLElement>) => {
        if (from.current === null) return;
        const a = Math.min(from.current, at(e));
        const b = Math.max(from.current, at(e));
        from.current = null;
        setLive(null);
        if (b - a > 0.004) onSelect?.(a, b);
        else onPick?.(a);
      },
      onMouseLeave: () => {
        from.current = null;
        setLive(null);
      },
    },
  };
}

/** 스펙트로그램: 가로가 시간, 세로가 주파수(위가 높은 쪽), 진할수록 세다. sel 은 고른 시간 구간, band 는 고른 주파수 띠(둘 다 0 ~ 1) */
function Heat({ grid, sel, band, onSelect, label, testid }: { grid: AnalyzeGrid; sel?: [number, number] | null; band?: [number, number] | null; onSelect?: (a: number, b: number) => void; label: string; testid: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const drag = useDrag(onSelect);
  useEffect(() => {
    const c = ref.current;
    if (!c || noCanvas() || grid.cols === 0) return;
    const g = c.getContext("2d");
    if (!g) return;
    // 진하기 기준: 값들의 아래 30% 자리를 바닥, 가장 센 값을 꼭대기로
    const flat = grid.db.flat().sort((a, b) => a - b);
    const lo = flat[Math.floor(flat.length * 0.3)] ?? -100;
    const hi = Math.max(flat[flat.length - 1] ?? lo + 1, lo + 10);
    const [r, gg, b] = inkOf(c);
    const img = g.createImageData(grid.cols, grid.rows);
    for (let x = 0; x < grid.cols; x++) {
      const col = grid.db[x]!;
      for (let y = 0; y < grid.rows; y++) {
        const k = ((grid.rows - 1 - y) * grid.cols + x) * 4; // 위쪽이 높은 주파수
        img.data[k] = r;
        img.data[k + 1] = gg;
        img.data[k + 2] = b;
        img.data[k + 3] = Math.round(255 * Math.min(1, Math.max(0, (col[y]! - lo) / (hi - lo))));
      }
    }
    g.putImageData(img, 0, 0);
  }, [grid]);
  const shown = drag.live ?? sel;
  return (
    <div className="an-plot" {...(onSelect ? drag.handlers : {})} data-selectable={onSelect ? true : undefined} data-testid={testid}>
      <canvas ref={ref} width={Math.max(grid.cols, 1)} height={Math.max(grid.rows, 1)} className="an-heat" role="img" aria-label={label} />
      {shown && <span className="an-sel" style={{ left: `${shown[0] * 100}%`, width: `${Math.max((shown[1] - shown[0]) * 100, 0.3)}%` }} />}
      {band && <span className="an-band" style={{ top: `${(1 - band[1]) * 100}%`, height: `${Math.max((band[1] - band[0]) * 100, 0.6)}%` }} />}
    </div>
  );
}

/** 줄 그림. lines 의 값들을 같은 세로 눈금에 그린다(null 은 끊는다). sel 은 고른 가로 구간(0 ~ 1) */
function Trace({
  lines,
  sel,
  onSelect,
  onPick,
  label,
  testid,
  zero,
}: {
  lines: { values: (number | null)[]; faint?: boolean }[];
  sel?: [number, number] | null;
  onSelect?: (a: number, b: number) => void;
  onPick?: (at: number) => void;
  label: string;
  testid: string;
  /** true 면 세로 눈금이 0 을 포함한다(크기처럼 0 이 뜻이 있는 값) */
  zero?: boolean;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const drag = useDrag(onSelect, onPick);
  useEffect(() => {
    const c = ref.current;
    if (!c || noCanvas()) return;
    const g = c.getContext("2d");
    if (!g) return;
    const all = lines.flatMap((l) => l.values).filter((v): v is number => v !== null);
    g.clearRect(0, 0, c.width, c.height);
    if (all.length === 0) return;
    let lo = Math.min(...all);
    let hi = Math.max(...all);
    if (zero) lo = Math.min(lo, 0);
    if (hi - lo < 1e-9) hi = lo + 1;
    const pad = (hi - lo) * 0.08;
    g.lineWidth = 2;
    g.strokeStyle = inkCss(c);
    for (const line of lines) {
      const n = line.values.length;
      g.globalAlpha = line.faint ? 0.3 : 1;
      g.beginPath();
      let pen = false;
      line.values.forEach((v, k) => {
        if (v === null) {
          pen = false;
          return;
        }
        const x = n > 1 ? (k / (n - 1)) * c.width : c.width / 2;
        const y = c.height - ((v - (lo - pad)) / (hi - lo + 2 * pad)) * c.height;
        if (pen) g.lineTo(x, y);
        else g.moveTo(x, y);
        pen = true;
      });
      g.stroke();
    }
    g.globalAlpha = 1;
  }, [lines, zero]);
  const shown = drag.live ?? sel;
  const active = Boolean(onSelect || onPick);
  return (
    <div className="an-plot" {...(active ? drag.handlers : {})} data-selectable={active ? true : undefined} data-testid={testid}>
      <canvas ref={ref} width={800} height={150} className="an-trace" role="img" aria-label={label} />
      {shown && <span className="an-sel" style={{ left: `${shown[0] * 100}%`, width: `${Math.max((shown[1] - shown[0]) * 100, 0.3)}%` }} />}
    </div>
  );
}

/** 성상도: 가로 I, 세로 Q. 점마다 샘플 하나 */
function Scatter({ i, q, label }: { i: number[]; q: number[]; label: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c || noCanvas()) return;
    const g = c.getContext("2d");
    if (!g) return;
    const lim = Math.max(1.6, ...i.map(Math.abs), ...q.map(Math.abs)) * 1.05;
    g.clearRect(0, 0, c.width, c.height);
    g.fillStyle = inkCss(c);
    g.globalAlpha = 0.12;
    g.fillRect(c.width / 2, 0, 1, c.height);
    g.fillRect(0, c.height / 2, c.width, 1);
    g.globalAlpha = 0.5;
    i.forEach((v, k) => g.fillRect(((v / lim + 1) / 2) * c.width - 1, ((1 - q[k]! / lim) / 2) * c.height - 1, 3, 3));
    g.globalAlpha = 1;
  }, [i, q]);
  return <canvas ref={ref} width={300} height={300} className="an-scatter" role="img" aria-label={label} />;
}

interface Window {
  start: number;
  seconds: number;
}

export function AnalyzeScreen() {
  const { api, fail } = useStore();
  const [files, setFiles] = useState<{ folder: string; files: AnalyzeFile[]; can_choose: boolean } | null>(null);
  const [path, setPath] = useState("");
  const [rate, setRate] = useState("");
  const [center, setCenter] = useState("");
  const [src, setSrc] = useState<AnalyzeSource | null>(null);
  const [over, setOver] = useState<AnalyzeOverview | null>(null);
  const [opening, setOpening] = useState(false);
  const [win, setWin] = useState<Window | null>(null);
  /** 고른 주파수: 가운데에서 떨어진 만큼과 폭(Hz). 폭이 0 이면 고르지 않은 것(받은 폭 전체를 본다) */
  const [pick, setPick] = useState({ offset: 0, width: 0 });
  const [det, setDet] = useState<AnalyzeDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [made, setMade] = useState("");
  /** 비트로 풀기: 방식(자동·켜고 끄기·주파수 바꾸기), 심볼 속도(비우면 잰 값), 결과 */
  const [demodKind, setDemodKind] = useState("auto");
  const [baud, setBaud] = useState("");
  const [bits, setBits] = useState<AnalyzeBits | null>(null);
  const [demodding, setDemodding] = useState(false);

  const reload = useCallback(() => {
    void api.analyzeFiles().then(setFiles, () => setFiles({ folder: "", files: [], can_choose: false }));
  }, [api]);
  useEffect(reload, [reload]);

  const open = async (next: AnalyzeSource) => {
    setOpening(true);
    setMade("");
    try {
      const got = await api.analyzeOpen(next);
      setSrc({ ...next, path: got.file.path });
      setOver(got);
      setDet(null);
      setPick({ offset: 0, width: 0 });
      // 버스트가 있으면 가장 센 것부터 본다. 없으면 파일의 앞부분
      const best = [...got.bursts].sort((a, b) => b.above_floor_db - a.above_floor_db)[0];
      setWin(best ? around(best.start_s, best.seconds, got.file.seconds) : { start: 0, seconds: Math.min(got.file.seconds, 0.05) });
    } catch (e) {
      fail(String(e instanceof Error ? e.message : e));
    } finally {
      setOpening(false);
    }
  };
  const openTyped = () => void open({ path, sample_rate_hz: rate.trim() ? Number(rate) * 1e6 : undefined, center_hz: center.trim() ? Number(center) * 1e6 : undefined });
  const choose = async () => {
    try {
      const got = await api.analyzeChoose();
      if (got.path) {
        setPath(got.path);
        if (/\.sigmf-(meta|data)$/.test(got.path)) void open({ path: got.path });
      }
    } catch (e) {
      fail(String(e instanceof Error ? e.message : e));
    }
  };

  // 구간이나 고른 주파수가 바뀌면 자세히 보기를 다시 묻는다(값을 끄는 동안 연달아 묻지 않게 조금 기다린다)
  const start = win?.start;
  const seconds = win?.seconds;
  useEffect(() => {
    if (!src || start === undefined || seconds === undefined) return;
    setBits(null); // 구간이나 고른 주파수가 바뀌면 전에 푼 비트는 그 신호의 것이 아니다
    let on = true;
    const timer = setTimeout(() => {
      setBusy(true);
      api.analyzeDetail({ ...src, start_s: start, seconds, offset_hz: pick.offset, bandwidth_hz: pick.width }).then(
        (d) => on && setDet(d),
        (e: unknown) => on && fail(String(e instanceof Error ? e.message : e)),
      ).finally(() => on && setBusy(false));
    }, 150);
    return () => {
      on = false;
      clearTimeout(timer);
    };
    // fail 은 오류가 뜰 때마다 새 함수가 된다(넣으면 오류 하나에 다시 묻는다)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, src, start, seconds, pick.offset, pick.width]);

  const total = over?.file.seconds ?? 0;
  const fs = over?.file.sample_rate_hz ?? 1;
  const clampWin = useCallback(
    (w: Window): Window => {
      const len = Math.min(Math.max(w.seconds, 64 / fs), total);
      return { start: Math.min(Math.max(w.start, 0), Math.max(total - len, 0)), seconds: len };
    },
    [fs, total],
  );
  const move = (w: Window) => setWin(clampWin(w));
  const overSel = useMemo<[number, number] | null>(() => (win && total > 0 ? [win.start / total, (win.start + win.seconds) / total] : null), [win, total]);
  const band = useMemo<[number, number] | null>(
    () => (pick.width > 0 ? [0.5 + (pick.offset - pick.width / 2) / fs, 0.5 + (pick.offset + pick.width / 2) / fs] : null),
    [pick, fs],
  );
  const envelope = useMemo(() => [{ values: over?.envelope.peak_db ?? [] }, { values: over?.envelope.mean_db ?? [], faint: true }], [over]);
  const spectrum = useMemo(() => [{ values: det?.spectrum.mean_db ?? [] }, { values: det?.spectrum.max_db ?? [], faint: true }], [det]);
  const wave = useMemo(() => [{ values: det?.wave.max ?? [] }, ...(det?.wave.min ? [{ values: det.wave.min, faint: true }] : [])], [det]);
  const iq = useMemo(() => [{ values: det?.wave.i ?? [] }, { values: det?.wave.q ?? [], faint: true }], [det]);
  const freq = useMemo(() => [{ values: det?.inst_freq_hz ?? [] }], [det]);

  const cut = async () => {
    if (!src || !win) return;
    try {
      const got = await api.analyzeCut({ ...src, start_s: win.start, seconds: win.seconds });
      setMade(got.data_path);
      reload();
    } catch (e) {
      fail(String(e instanceof Error ? e.message : e));
    }
  };

  const demod = async () => {
    if (!src || !win) return;
    setDemodding(true);
    try {
      setBits(await api.analyzeDemod({ ...src, start_s: win.start, seconds: win.seconds, offset_hz: pick.offset, bandwidth_hz: pick.width, kind: demodKind, symbol_rate_hz: Number(baud) > 0 ? Number(baud) : undefined }));
    } catch (e) {
      fail(String(e instanceof Error ? e.message : e));
    } finally {
      setDemodding(false);
    }
  };

  const mod = det?.modulation;
  const occ = det?.occupied;
  return (
    <>
      <SubNav title={t("nav.analyze")} />
      <Tile tone="light" wide>
        <TileHead title={t("analyze.title")} lead={t("analyze.lead")} />

        <div className="card an-card" data-testid="analyze-files">
          <h3 className="t-tagline">{t("analyze.files.title")}</h3>
          {files && files.files.length > 0 ? (
            <div className="table-wrap">
              <table className="data t-caption">
                <caption className="sr-only">{t("analyze.files.title")}</caption>
                <tbody>
                  {files.files.map((f) => (
                    <tr key={f.path} data-now={src?.path === f.path}>
                      <td>{f.name}</td>
                      <td className="right">{span(f.seconds)}</td>
                      <td className="right">{mhz(f.center_hz)} MHz</td>
                      <td className="right">{num(f.sample_rate_hz / 1e6, 3)} MS/s</td>
                      <td className="right">{num(f.bytes / 1e6, 1)} MB</td>
                      <td>
                        <Button variant="link" onClick={() => void open({ path: f.path })} disabled={opening} data-testid={`analyze-open-${f.name}`}>
                          {t("analyze.open")}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="t-caption muted">{t("analyze.files.none", { folder: files?.folder ?? "" })}</p>
          )}
          <div className="row an-open">
            {files?.can_choose && (
              <Button variant="secondary" onClick={() => void choose()} disabled={opening} data-testid="analyze-choose">
                {t("analyze.choose")}
              </Button>
            )}
            <Field label={t("analyze.path")}>{(f) => <input {...f} value={path} onChange={(e) => setPath(e.target.value)} data-testid="analyze-path" />}</Field>
            <Field label={t("analyze.rate")}>{(f) => <input {...f} inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} data-testid="analyze-rate" />}</Field>
            <Field label={t("analyze.center")}>{(f) => <input {...f} inputMode="decimal" value={center} onChange={(e) => setCenter(e.target.value)} />}</Field>
            <Button onClick={openTyped} disabled={opening || !path.trim()} data-testid="analyze-open-path">
              {opening ? t("analyze.opening") : t("analyze.open")}
            </Button>
          </div>
          <p className="t-caption muted">{t("analyze.formats")}</p>
        </div>

        {over && (
          <div className="card an-card" data-testid="analyze-overview">
            <h3 className="t-tagline">{t("analyze.over.title", { name: over.file.name })}</h3>
            <p className="t-caption muted">
              {t("analyze.over.facts", { s: span(over.file.seconds), center: mhz(over.file.center_hz), rate: num(over.file.sample_rate_hz / 1e6, 3), type: over.file.datatype, scan: over.scan_s })}
            </p>
            <Heat grid={over.spectrogram} sel={overSel} onSelect={(a, b) => move({ start: a * total, seconds: (b - a) * total })} label={t("analyze.plot.spectrogram")} testid="analyze-over-heat" />
            <div className="an-axis t-caption muted">
              <span>0 s</span>
              <span>
                {t("analyze.axis.freq", { lo: mhz(over.file.center_hz - fs / 2), hi: mhz(over.file.center_hz + fs / 2) })}
                {over.spectrogram.sparse ? ` · ${t("analyze.over.sparse")}` : ""}
              </span>
              <span>{span(total)}</span>
            </div>
            <Trace lines={envelope} sel={overSel} onSelect={(a, b) => move({ start: a * total, seconds: (b - a) * total })} label={t("analyze.plot.envelope")} testid="analyze-over-envelope" />
            <p className="t-caption muted center">{t("analyze.over.caption")}</p>

            <h4 className="t-caption-strong">{t("analyze.bursts.title", { n: over.bursts.length })}</h4>
            {over.bursts.length === 0 ? (
              <p className="t-caption muted">{t("analyze.bursts.none")}</p>
            ) : (
              <div className="table-wrap an-bursts">
                <table className="data t-caption" data-testid="analyze-bursts">
                  <caption className="sr-only">{t("analyze.bursts.title", { n: over.bursts.length })}</caption>
                  <thead>
                    <tr>
                      {["no", "start", "length", "peak", "above", "go"].map((c) => (
                        <th key={c} scope="col" className={`t-caption-strong ${c === "go" ? "" : "right"}`}>
                          {t(`analyze.bursts.col.${c}`)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {over.bursts.map((b, k) => (
                      <tr key={k} data-now={win !== null && b.start_s >= win.start && b.start_s + b.seconds <= win.start + win.seconds}>
                        <td className="right">{k + 1}</td>
                        <td className="right">{num(b.start_s, 4)} s</td>
                        <td className="right">{span(b.seconds)}</td>
                        <td className="right">{b.peak_db.toFixed(1)} dBFS</td>
                        <td className="right">+{b.above_floor_db.toFixed(0)} dB</td>
                        <td>
                          <Button variant="link" onClick={() => setWin(around(b.start_s, b.seconds, total))} data-testid={`analyze-burst-${k}`}>
                            {t("analyze.bursts.go")}
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {over && win && (
          <div className="card an-card" data-testid="analyze-detail">
            <h3 className="t-tagline">{t("analyze.detail.title")}</h3>
            <div className="row an-controls">
              <Field label={t("analyze.detail.start")}>
                {(f) => <input {...f} inputMode="decimal" value={num(win.start, 6)} onChange={(e) => move({ ...win, start: Number(e.target.value) || 0 })} data-testid="analyze-start" />}
              </Field>
              <Field label={t("analyze.detail.length")}>
                {(f) => <input {...f} inputMode="decimal" value={num(win.seconds * 1e3, 4)} onChange={(e) => Number(e.target.value) > 0 && move({ ...win, seconds: Number(e.target.value) / 1e3 })} data-testid="analyze-length" />}
              </Field>
              <Field label={t("analyze.detail.offset")}>
                {(f) => <input {...f} inputMode="decimal" value={num(pick.offset / 1e3, 2)} onChange={(e) => setPick({ ...pick, offset: (Number(e.target.value) || 0) * 1e3 })} data-testid="analyze-offset" />}
              </Field>
              <Field label={t("analyze.detail.width")}>
                {(f) => <input {...f} inputMode="decimal" value={num(pick.width / 1e3, 2)} onChange={(e) => setPick({ ...pick, width: Math.max(0, Number(e.target.value) || 0) * 1e3 })} data-testid="analyze-width" />}
              </Field>
            </div>
            <div className="row an-buttons">
              <Button variant="secondary" onClick={() => move({ ...win, start: win.start - win.seconds / 2 })} data-testid="analyze-left">
                ◀ {t("analyze.detail.earlier")}
              </Button>
              <Button variant="secondary" onClick={() => move({ ...win, start: win.start + win.seconds / 2 })} data-testid="analyze-right">
                {t("analyze.detail.later")} ▶
              </Button>
              <Button variant="secondary" onClick={() => move({ start: win.start + win.seconds / 4, seconds: win.seconds / 2 })} data-testid="analyze-in">
                {t("analyze.detail.in")}
              </Button>
              <Button variant="secondary" onClick={() => move({ start: win.start - win.seconds / 2, seconds: win.seconds * 2 })} data-testid="analyze-out">
                {t("analyze.detail.out")}
              </Button>
              {occ && (
                <Button onClick={() => setPick({ offset: occ.center_offset_hz, width: Math.max(occ.bandwidth_hz * 2, 4 * (det?.bin_hz ?? 0)) })} data-testid="analyze-pick">
                  {t("analyze.detail.pick")}
                </Button>
              )}
              {pick.width > 0 && (
                <Button variant="link" onClick={() => setPick({ offset: 0, width: 0 })} data-testid="analyze-unpick">
                  {t("analyze.detail.unpick")}
                </Button>
              )}
              <Button variant="link" onClick={() => void cut()} data-testid="analyze-cut">
                {t("analyze.detail.cut")}
              </Button>
              {busy && <span className="spinner" aria-label={t("status.running")} />}
            </div>
            {made && (
              <p className="t-caption" data-testid="analyze-made">
                {t("analyze.detail.made")} <code>{made}</code>
              </p>
            )}

            {det && (
              <>
                {det.coarse && <Badge level="warn">{t("analyze.detail.coarse")}</Badge>}
                <dl className="facts t-caption an-facts" data-testid="analyze-facts">
                  {(
                    [
                      ["window", `${num(det.start_s, 5)} s + ${span(det.seconds)}`],
                      ["power", `${det.power_db.toFixed(1)} dBFS`],
                      ["peak", `${det.peak_db.toFixed(1)} dBFS`],
                      ...(occ ? [["at", `${mhz(over.file.center_hz + occ.center_offset_hz)} MHz (${occ.center_offset_hz >= 0 ? "+" : ""}${khz(occ.center_offset_hz)})`] as const, ["wide", khz(occ.bandwidth_hz)] as const] : []),
                      ...(mod ? [["kind", t(`analyze.mod.${mod.kind}`)] as const] : []),
                      ...(mod?.symbol_rate_hz ? [["symbol", `${span(mod.shortest_on_s ?? 0)} (${num(mod.symbol_rate_hz, 0)} /s)`] as const] : []),
                      ...(mod?.deviation_hz ? [["deviation", `±${khz(mod.deviation_hz)}`] as const] : []),
                    ] as const
                  ).map(([k, v]) => (
                    <div key={k}>
                      <dt className="muted">{t(`analyze.fact.${k}`)}</dt>
                      <dd>{v}</dd>
                    </div>
                  ))}
                </dl>
                {mod && mod.kind !== "unknown" && <p className="t-caption muted">{t(`analyze.mod.${mod.kind}.why`)}</p>}

                <h4 className="t-caption-strong">{t("analyze.plot.spectrogram")}</h4>
                <Heat grid={det.spectrogram} band={band} onSelect={(a, b) => move({ start: det.start_s + a * det.seconds, seconds: (b - a) * det.seconds })} label={t("analyze.plot.spectrogram")} testid="analyze-heat" />
                <div className="an-axis t-caption muted">
                  <span>{num(det.start_s, 5)} s</span>
                  <span>{t("analyze.detail.heat_hint")}</span>
                  <span>+{span(det.seconds)}</span>
                </div>

                <h4 className="t-caption-strong">{t("analyze.plot.spectrum")}</h4>
                <Trace
                  lines={spectrum}
                  sel={band}
                  onPick={(at) => setPick({ offset: Math.round(det.spectrum.lo_hz + at * (det.spectrum.hi_hz - det.spectrum.lo_hz)), width: pick.width || Math.max((occ?.bandwidth_hz ?? 0) * 2, 8 * det.bin_hz) })}
                  onSelect={(a, b) => {
                    const lo = det.spectrum.lo_hz + a * (det.spectrum.hi_hz - det.spectrum.lo_hz);
                    const hi = det.spectrum.lo_hz + b * (det.spectrum.hi_hz - det.spectrum.lo_hz);
                    setPick({ offset: Math.round((lo + hi) / 2), width: Math.round(hi - lo) });
                  }}
                  label={t("analyze.plot.spectrum")}
                  testid="analyze-spectrum"
                />
                <div className="an-axis t-caption muted">
                  <span>{mhz(over.file.center_hz + det.spectrum.lo_hz)} MHz</span>
                  <span>{t("analyze.detail.spectrum_hint", { bin: khz(det.bin_hz) })}</span>
                  <span>{mhz(over.file.center_hz + det.spectrum.hi_hz)} MHz</span>
                </div>

                <h4 className="t-caption-strong">{t(pick.width > 0 ? "analyze.plot.wave_picked" : "analyze.plot.wave")}</h4>
                <Trace lines={wave} zero onSelect={(a, b) => move({ start: det.start_s + a * det.seconds, seconds: (b - a) * det.seconds })} label={t("analyze.plot.wave")} testid="analyze-wave" />
                {det.wave.i && (
                  <>
                    <h4 className="t-caption-strong">{t("analyze.plot.iq")}</h4>
                    <Trace lines={iq} onSelect={(a, b) => move({ start: det.start_s + a * det.seconds, seconds: (b - a) * det.seconds })} label={t("analyze.plot.iq")} testid="analyze-iq" />
                  </>
                )}
                {det.inst_freq_hz && (
                  <>
                    <h4 className="t-caption-strong">{t("analyze.plot.freq")}</h4>
                    <Trace lines={freq} onSelect={(a, b) => move({ start: det.start_s + a * det.seconds, seconds: (b - a) * det.seconds })} label={t("analyze.plot.freq")} testid="analyze-freq" />
                    <p className="t-caption muted center">{t("analyze.plot.freq.note")}</p>
                  </>
                )}
                <h4 className="t-caption-strong">{t("analyze.bits.title")}</h4>
                <div className="row an-buttons" data-testid="analyze-bits-controls">
                  <label className="record-export t-caption">
                    <span className="muted">{t("analyze.bits.kind")}</span>
                    <select value={demodKind} onChange={(e) => setDemodKind(e.target.value)} data-testid="analyze-bits-kind">
                      {["auto", "ook", "fsk"].map((k) => (
                        <option key={k} value={k}>
                          {t(`analyze.bits.kind.${k}`)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <Field label={t("analyze.bits.baud")}>{(f) => <input {...f} inputMode="decimal" value={baud} onChange={(e) => setBaud(e.target.value)} data-testid="analyze-bits-baud" />}</Field>
                  <Button onClick={() => void demod()} disabled={demodding || pick.width <= 0 || det.coarse} data-testid="analyze-bits-go">
                    {demodding ? t("analyze.bits.busy") : t("analyze.bits.go")}
                  </Button>
                </div>
                {pick.width <= 0 && <p className="t-caption muted">{t("analyze.bits.need")}</p>}
                {bits && (
                  <div data-testid="analyze-bits">
                    <p className="t-caption">
                      {t("analyze.bits.summary", { kind: t(`analyze.mod.${bits.kind}`), rate: num(bits.symbol_rate_hz, 0), symbol: span(bits.symbol_s), n: bits.packets_total })}
                    </p>
                    {bits.packets.map((p, k) => (
                      <div className="an-packet" key={k} data-testid={`analyze-packet-${k}`}>
                        <div className="t-caption muted">
                          {t("analyze.bits.packet", { no: k + 1, at: num(p.start_s, 4), len: span(p.seconds), bits: p.bits.length })}
                          {p.repeats > 1 ? ` · ${t("analyze.bits.repeats", { n: p.repeats })}` : ""}
                        </div>
                        <code className="an-bits">{p.bits.replace(/(.{8})/g, "$1 ").trim()}</code>
                        <code className="an-bits">HEX {p.hex.replace(/(.{2})/g, "$1 ").trim()}</code>
                        {p.manchester && (
                          <>
                            <div className="t-caption muted">{t("analyze.bits.manchester", { bits: p.manchester.bits.length })}</div>
                            <code className="an-bits">{p.manchester.bits.replace(/(.{8})/g, "$1 ").trim()}</code>
                            <code className="an-bits">HEX {p.manchester.hex.replace(/(.{2})/g, "$1 ").trim()}</code>
                          </>
                        )}
                      </div>
                    ))}
                    <p className="t-caption muted">{t("analyze.bits.note")}</p>
                  </div>
                )}
                {det.constellation && (
                  <>
                    <h4 className="t-caption-strong">{t("analyze.plot.constellation")}</h4>
                    <div className="an-scatter-wrap">
                      <Scatter i={det.constellation.i} q={det.constellation.q} label={t("analyze.plot.constellation")} />
                      <p className="t-caption muted">{t("analyze.plot.constellation.note")}</p>
                    </div>
                  </>
                )}
              </>
            )}
          </div>
        )}
        <p className="t-caption muted center">{t("analyze.notice")}</p>
      </Tile>
    </>
  );
}

/** 버스트를 앞뒤로 조금 여유를 두고 보는 구간 */
function around(startS: number, seconds: number, total: number): Window {
  const pad = Math.max(seconds * 0.15, 1e-3);
  const start = Math.max(0, startS - pad);
  return { start, seconds: Math.min(seconds + 2 * pad, total - start) };
}
