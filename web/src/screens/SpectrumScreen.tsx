import { useCallback, useEffect, useRef, useState } from "react";
import type { DeviceInfo, SurveyChannel, SurveyDevice, SurveyResult } from "../api";
import { SubNav, Tile, TileHead } from "../components/layout";
import { linear, ticks } from "../components/plots/scale";
import { Badge, Button, Chip, Empty, Field } from "../components/ui";
import { t } from "../i18n";
import { useStore } from "../state/store";
import { SpectrumView, type SpectrumViewHandle } from "./SpectrumView";

type Stat = "median_dbfs" | "mean_dbfs";
/** 기준: 채널 이름 → 그때의 중앙값·평균. 어느 값을 보고 있든 같은 종류끼리 비교한다. */
type Baseline = Record<string, Record<Stat, number>>;
const REPEAT_MS = 2000;

const mhz = (hz: number) => (hz / 1e6).toFixed(hz % 1e6 === 0 ? 0 : 2);
const num = (v: number | undefined) => (v === undefined ? "—" : v.toFixed(1));

/** 채널별 세기 막대 그림. 기준이 있으면 막대마다 기준 높이에 가로선을 긋는다. */
export function SurveyBars({ rows, stat, baseline }: { rows: SurveyChannel[]; stat: Stat; baseline: Baseline | null }) {
  const W = 720;
  const H = 300;
  const m = { l: 48, r: 12, t: 16, b: 44 };
  const values = [...rows.flatMap((r) => (r.measured ? [r[stat] ?? 0] : [])), ...Object.values(baseline ?? {}).map((b) => b[stat])];
  const lo = values.length ? Math.floor(Math.min(...values) / 10) * 10 - 10 : -100;
  const hi = values.length ? Math.max(lo + 20, Math.ceil(Math.max(...values) / 10) * 10) : 0;
  const y = linear(lo, hi, H - m.b, m.t);
  const slot = (W - m.l - m.r) / Math.max(1, rows.length);
  const bar = Math.max(4, slot * 0.7);
  const every = Math.ceil(rows.length / 14);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t("spectrum.chart.label")} data-testid="survey-chart" className="survey-chart">
      {ticks(lo, hi, 5).map((v) => (
        <g key={v} className="plot-axis">
          <line className="plot-gridline" x1={m.l} x2={W - m.r} y1={y(v)} y2={y(v)} />
          <text x={m.l - 6} y={y(v) + 4} textAnchor="end">
            {v}
          </text>
        </g>
      ))}
      {rows.map((r, i) => {
        const x = m.l + i * slot + (slot - bar) / 2;
        const v = r[stat];
        const base = baseline?.[r.name]?.[stat];
        return (
          <g key={r.name} data-testid={`survey-bar-${r.name}`} data-state={!r.measured ? "missing" : r.clipped ? "clipped" : "ok"}>
            {r.measured && v !== undefined ? (
              <rect className="survey-bar" x={x} y={y(v)} width={bar} height={Math.max(1, y(lo) - y(v))}>
                <title>{`${r.name} · ${mhz(r.center_hz)} MHz · ${v.toFixed(1)} dBFS`}</title>
              </rect>
            ) : (
              <rect className="survey-bar-missing" x={x} y={m.t} width={bar} height={H - m.b - m.t}>
                <title>{`${r.name} · ${t("spectrum.unmeasured")}`}</title>
              </rect>
            )}
            {base !== undefined && <line className="survey-base" x1={x - 2} x2={x + bar + 2} y1={y(base)} y2={y(base)} />}
            {i % every === 0 && (
              <text className="plot-label" x={x + bar / 2} y={H - m.b + 16} textAnchor="middle">
                {r.name}
              </text>
            )}
          </g>
        );
      })}
      <text className="plot-label" x={m.l} y={H - 6}>
        {t("spectrum.axis.x")}
      </text>
      <text className="plot-label" x={W - m.r} y={H - 6} textAnchor="end">
        {t("spectrum.axis.y")}
      </text>
    </svg>
  );
}

function DeviceFacts({ info }: { info: SurveyDevice }) {
  const d = info.device;
  const rep = info.reported ?? {};
  const range = (r?: number[], div = 1, unit = "") => (r && r.length === 2 ? `${(r[0]! / div).toFixed(0)} ~ ${(r[1]! / div).toFixed(0)}${unit}` : undefined);
  const facts: [string, string | undefined][] = [
    ["driver", d.driver],
    ["serial", d.serial],
    ["freq", d.freq_min_hz !== undefined && d.freq_max_hz !== undefined && d.driver !== "simulated" ? `${mhz(d.freq_min_hz)} ~ ${mhz(d.freq_max_hz)} MHz` : undefined],
    ["rate", d.max_sample_rate_hz ? `${mhz(d.max_sample_rate_hz)} Msps` : undefined],
    ["bits", d.bits ? String(d.bits) : undefined],
    ["clock", d.clock_ppm !== undefined && d.driver !== "simulated" ? `±${d.clock_ppm} ppm` : undefined],
    ["file_center", info.capture ? `${mhz(info.capture.center_freq_hz)} MHz` : undefined],
    ["file_rate", info.capture ? `${mhz(info.capture.sample_rate_hz)} Msps` : undefined],
    ["file_length", info.capture ? `${info.capture.duration_s} s` : undefined],
    ["antennas", rep.antennas?.join(", ")],
    ["gain", range(rep.gain_range_db, 1, " dB")],
    ["rep_rate", range(rep.sample_rate_range_hz, 1e6, " Msps")],
    ["rep_freq", range(rep.freq_range_hz, 1e6, " MHz")],
    ["clock_sources", rep.clock_sources?.join(", ")],
  ];
  return (
    <div className="card" data-testid="survey-device">
      <h3 className="t-tagline">{d.label}</h3>
      {d.note && <p className="t-caption muted">{d.note}</p>}
      <dl className="facts t-caption">
        {facts
          .filter(([, v]) => v)
          .map(([k, v]) => (
            <div key={k}>
              <dt className="muted">{t(`spectrum.fact.${k}`)}</dt>
              <dd>{v}</dd>
            </div>
          ))}
      </dl>
      {rep.error && <p className="t-caption muted">! {rep.error}</p>}
      {d.driver !== "simulated" && <p className="t-caption muted">{t("spectrum.fact.source")}</p>}
    </div>
  );
}

/** 주파수 상태: 장비를 고르면 장비 정보가 나오고, 채널별 수신 세기를 잰다. */
export function SpectrumScreen() {
  const { api, fail } = useStore();
  const [devices, setDevices] = useState<DeviceInfo[] | null>(null);
  const [device, setDevice] = useState("");
  const [info, setInfo] = useState<SurveyDevice | null>(null);
  const [plan, setPlan] = useState("");
  const [custom, setCustom] = useState({ center: "", span: "", step: "" });
  const [gain, setGain] = useState("");
  const [stat, setStat] = useState<Stat>("median_dbfs");
  const [result, setResult] = useState<SurveyResult | null>(null);
  const [baseline, setBaseline] = useState<Baseline | null>(null);
  const [busy, setBusy] = useState(false);
  const [repeat, setRepeat] = useState(false);
  const running = useRef(false);
  const viewer = useRef<SpectrumViewHandle>(null);

  useEffect(() => {
    void api.devices().then(
      (list) => {
        setDevices(list);
        setDevice((cur) => cur || list[0]?.id || "");
      },
      () => setDevices([]),
    );
  }, [api]);

  useEffect(() => {
    if (!device) return;
    setInfo(null);
    setResult(null);
    setBaseline(null);
    setRepeat(false);
    void api.surveyDevice(device).then(
      (i) => {
        setInfo(i);
        setPlan(i.plans.find((p) => p.available)?.id ?? "");
      },
      (e: unknown) => fail(String(e instanceof Error ? e.message : e)),
    );
  }, [api, device, fail]);

  const measure = useCallback(async () => {
    if (running.current || !device || !plan) return;
    running.current = true;
    setBusy(true);
    try {
      const mhzIn = (s: string) => (s.trim() ? Number(s) * 1e6 : undefined);
      setResult(
        await api.surveyRun({
          device,
          plan,
          gain_db: gain.trim() ? Number(gain) : undefined,
          center_hz: mhzIn(custom.center),
          span_hz: mhzIn(custom.span),
          step_hz: mhzIn(custom.step),
        }),
      );
    } catch (e) {
      setRepeat(false);
      fail(String(e instanceof Error ? e.message : e));
    } finally {
      running.current = false;
      setBusy(false);
    }
  }, [api, custom, device, fail, gain, plan]);

  useEffect(() => {
    if (!repeat) return;
    void measure();
    const timer = setInterval(() => void measure(), REPEAT_MS);
    return () => clearInterval(timer);
  }, [repeat, measure]);

  const rows = result?.channels ?? [];
  const measured = rows.filter((r) => r.measured);
  const strongest = measured.reduce<SurveyChannel | null>((a, r) => (!a || (r[stat] ?? -999) > (a[stat] ?? -999) ? r : a), null);
  const real = info?.device.driver !== "simulated";

  return (
    <>
      <SubNav title={t("nav.spectrum")} />
      <Tile tone="light">
        <TileHead title={t("spectrum.title")} lead={t("spectrum.lead")} />
        {devices !== null && devices.length === 0 && <Empty>{t("start.device.none")}</Empty>}
        {devices && devices.length > 0 && (
          <div className="chips center-row" role="group" aria-label={t("start.device.pick")}>
            {devices.map((d) => (
              <Chip key={d.id} selected={d.id === device} onSelect={() => setDevice(d.id)} disabled={busy}>
                {d.label}
              </Chip>
            ))}
          </div>
        )}
        {info && (
          <div className="source-grid">
            <DeviceFacts info={info} />
            <div className="card" data-testid="survey-controls">
              <h3 className="t-tagline">{t("spectrum.plan.title")}</h3>
              <div className="chips" role="group" aria-label={t("spectrum.plan.title")}>
                {info.plans.map((p) => (
                  <Chip key={p.id} selected={p.id === plan} onSelect={() => setPlan(p.id)} disabled={busy || !p.available}>
                    {t(`spectrum.plan.${p.id}`)}
                  </Chip>
                ))}
              </div>
              <p className="t-caption muted">{real ? t("spectrum.plan.hint_real") : t("spectrum.plan.hint_sim")}</p>
              {plan === "custom" && (
                <div className="row">
                  {(["center", "span", "step"] as const).map((k) => (
                    <Field key={k} label={t(`spectrum.custom.${k}`)}>
                      {(p) => <input {...p} inputMode="decimal" value={custom[k]} onChange={(e) => setCustom({ ...custom, [k]: e.target.value })} />}
                    </Field>
                  ))}
                </div>
              )}
              {real && (
                <Field label={t("spectrum.gain")}>
                  {(p) => <input {...p} inputMode="decimal" value={gain} onChange={(e) => setGain(e.target.value)} />}
                </Field>
              )}
              <div className="row">
                <Button onClick={() => void measure()} disabled={busy || repeat || !plan} data-testid="survey-run">
                  {busy && !repeat ? t("spectrum.busy") : t("spectrum.run")}
                </Button>
                <Button variant="secondary" onClick={() => setRepeat(!repeat)} disabled={!plan} data-testid="survey-repeat" aria-pressed={repeat}>
                  {repeat ? t("spectrum.repeat.stop") : t("spectrum.repeat.start")}
                </Button>
              </div>
            </div>
          </div>
        )}
      </Tile>

      {info && <SpectrumView key={info.device.id} info={info} gain={gain} ref={viewer} />}

      {result && (
        <Tile tone="parchment">
          <TileHead
            eyebrow={t("spectrum.result.eyebrow")}
            title={strongest ? t(strongest.name === mhz(strongest.center_hz) ? "spectrum.result.title_freq" : "spectrum.result.title", { name: strongest.name, mhz: mhz(strongest.center_hz) }) : t("spectrum.result.none")}
            lead={t("spectrum.result.lead")}
          >
            <div className="chips" role="group" aria-label={t("spectrum.stat.label")}>
              {(["median_dbfs", "mean_dbfs"] as const).map((s) => (
                <Chip key={s} selected={s === stat} onSelect={() => setStat(s)}>
                  {t(`spectrum.stat.${s}`)}
                </Chip>
              ))}
            </div>
            <Button
              variant="secondary"
              data-testid="survey-baseline"
              onClick={() => setBaseline(baseline ? null : Object.fromEntries(measured.map((r) => [r.name, { median_dbfs: r.median_dbfs ?? 0, mean_dbfs: r.mean_dbfs ?? 0 }])))}
            >
              {baseline ? t("spectrum.baseline.clear") : t("spectrum.baseline.save")}
            </Button>
          </TileHead>
          {rows.some((r) => r.clipped) && <Badge level="warn">{t("spectrum.clipped")}</Badge>}
          <div className="card">
            <SurveyBars rows={rows} stat={stat} baseline={baseline} />
            <p className="t-caption muted center">{baseline ? t("spectrum.chart.caption_base") : t("spectrum.chart.caption")}</p>
          </div>
          <div className="table-wrap">
            <table className="data t-caption" data-testid="survey-table">
              <caption className="sr-only">{t("spectrum.chart.label")}</caption>
              <thead>
                <tr>
                  {["name", "center", "median", "mean", "peak", ...(baseline ? ["rise"] : []), ...(real ? ["look"] : [])].map((c) => (
                    <th key={c} scope="col" className={`t-caption-strong ${c === "name" ? "" : "right"}`}>
                      {t(`spectrum.col.${c}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const base = baseline?.[r.name]?.[stat];
                  const v = r[stat];
                  const rise = base !== undefined && v !== undefined ? Math.round((v - base) * 10) / 10 : undefined;
                  return (
                    <tr key={r.name}>
                      <td>{r.name}</td>
                      <td className="right">{mhz(r.center_hz)}</td>
                      {r.measured ? (
                        <>
                          <td className="right">{num(r.median_dbfs)}</td>
                          <td className="right">{num(r.mean_dbfs)}</td>
                          <td className="right">{num(r.peak_dbfs)}</td>
                        </>
                      ) : (
                        <td className="right muted" colSpan={3}>
                          {t("spectrum.unmeasured")}
                        </td>
                      )}
                      {baseline && <td className="right">{rise !== undefined ? `${rise >= 0 ? "+" : ""}${(rise === 0 ? 0 : rise).toFixed(1)}` : "—"}</td>}
                      {real && (
                        <td className="right">
                          <Button variant="link" onClick={() => viewer.current?.look(r.center_hz, r.width_hz)} data-testid={`survey-look-${r.name}`}>
                            {t("spectrum.look")}
                          </Button>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <details className="fold">
            <summary className="t-body">{t("spectrum.how.title")}</summary>
            <div className="fold-body t-caption">
              {["dwell", "mean", "median", "peak", "unit"].map((k) => (
                <p key={k}>{t(`spectrum.how.${k}`, { ms: Math.round(result.dwell_s * 1000) })}</p>
              ))}
            </div>
          </details>
        </Tile>
      )}
    </>
  );
}
