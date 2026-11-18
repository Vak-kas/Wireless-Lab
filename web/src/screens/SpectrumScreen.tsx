import { useCallback, useEffect, useRef, useState } from "react";
import type { MonitorState, SurveyDevice, SurveyPlan, WifiAp } from "../api";
import { SubNav, Tile, TileHead } from "../components/layout";
import { linear, ticks } from "../components/plots/scale";
import { Badge, Button, Chip, Empty, Field } from "../components/ui";
import { t } from "../i18n";
import { useStore } from "../state/store";
import { useUsableDevices } from "../devices/DeviceHub";
import { DevicePicker } from "./DevicePicker";
import { SpectrumView, type SpectrumViewHandle } from "./SpectrumView";
import { ApTable, BandwidthWatch, countByWidth, dominant, type UsigSample } from "./WifiPanels";

type Stat = "median_dbfs" | "mean_dbfs";
const PAUSE_MS = 200;
const USIG_KEEP_MS = 60_000;
/** 처음 자리 잡은 폭을 정할 때 필요한 PPDU 수 */
const USIG_REFERENCE_MIN = 10;

const mhz = (hz: number) => (hz / 1e6).toFixed(hz % 1e6 === 0 ? 0 : 2);
const num = (v: number | null | undefined, sign = false) => (v === undefined || v === null ? "—" : `${sign && v >= 0 ? "+" : ""}${(Math.round(v * 10) / 10 || 0).toFixed(1)}`);

export interface Bar {
  name: string;
  value?: number;
  /** 기준선 높이 (세기 그림) */
  base?: number;
  state: "ok" | "clipped" | "missing" | "raised";
  title: string;
}

/** 채널별 막대 그림. zero=true 면 0 을 가운데 둔 증가량 그림, 아니면 아래에서 솟는 세기 그림. */
export function Bars({ bars, label, yLabel, zero, testid }: { bars: Bar[]; label: string; yLabel: string; zero?: boolean; testid: string }) {
  const W = 720;
  const H = zero ? 220 : 300;
  const m = { l: 48, r: 12, t: 16, b: 44 };
  const values = bars.flatMap((b) => [...(b.value !== undefined ? [b.value] : []), ...(b.base !== undefined ? [b.base] : [])]);
  let lo = values.length ? Math.floor(Math.min(...values) / 10) * 10 - (zero ? 0 : 10) : zero ? -10 : -100;
  let hi = values.length ? Math.ceil(Math.max(...values) / 10) * 10 : zero ? 10 : 0;
  if (zero) {
    lo = Math.min(lo, -10);
    hi = Math.max(hi, 10);
  } else hi = Math.max(hi, lo + 20);
  const y = linear(lo, hi, H - m.b, m.t);
  const floor = zero ? 0 : lo;
  const slot = (W - m.l - m.r) / Math.max(1, bars.length);
  const bar = Math.max(4, slot * 0.7);
  const every = Math.ceil(bars.length / 14);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} data-testid={testid} className="survey-chart">
      {ticks(lo, hi, 5).map((v) => (
        <g key={v} className="plot-axis">
          <line className="plot-gridline" x1={m.l} x2={W - m.r} y1={y(v)} y2={y(v)} />
          <text x={m.l - 6} y={y(v) + 4} textAnchor="end">
            {v}
          </text>
        </g>
      ))}
      {bars.map((b, i) => {
        const x = m.l + i * slot + (slot - bar) / 2;
        const top = b.value !== undefined ? Math.min(y(b.value), y(floor)) : 0;
        const height = b.value !== undefined ? Math.max(1, Math.abs(y(b.value) - y(floor))) : 0;
        return (
          <g key={b.name} data-testid={`${testid}-${b.name}`} data-state={b.state}>
            {b.value !== undefined ? (
              <rect className="survey-bar" x={x} y={top} width={bar} height={height}>
                <title>{b.title}</title>
              </rect>
            ) : (
              <rect className="survey-bar-missing" x={x} y={m.t} width={bar} height={H - m.b - m.t}>
                <title>{b.title}</title>
              </rect>
            )}
            {b.base !== undefined && <line className="survey-base" x1={x - 2} x2={x + bar + 2} y1={y(b.base)} y2={y(b.base)} />}
            {i % every === 0 && (
              <text className="plot-label" x={x + bar / 2} y={H - m.b + 16} textAnchor="middle">
                {b.name}
              </text>
            )}
          </g>
        );
      })}
      <text className="plot-label" x={m.l} y={H - 6}>
        {t("spectrum.axis.x")}
      </text>
      <text className="plot-label" x={W - m.r} y={H - 6} textAnchor="end">
        {yLabel}
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

/** 채널 맵: 칸을 누르면 그 칸이 속한 묶음(누르는 단위)을 한꺼번에 고르거나 푼다. */
function ChannelMap({ plan, picked, onChange, disabled }: { plan: SurveyPlan; picked: string[]; onChange: (names: string[]) => void; disabled?: boolean }) {
  const [unit, setUnit] = useState(20);
  const cells = plan.map ?? [];
  const reachable = new Set(cells.filter((c) => c.reachable).map((c) => c.name));
  const click = (name: string) => {
    const group = (plan.groups?.[String(unit)]?.find((g) => g.includes(name)) ?? [name]).filter((n) => reachable.has(n));
    const all = group.every((n) => picked.includes(n));
    onChange(all ? picked.filter((n) => !group.includes(n)) : [...picked, ...group.filter((n) => !picked.includes(n))]);
  };
  return (
    <div data-testid="channel-map">
      {(plan.widths?.length ?? 0) > 1 && (
        <div className="chips" role="group" aria-label={t("monitor.unit")}>
          {plan.widths!.map((w) => (
            <Chip key={w} selected={w === unit} onSelect={() => setUnit(w)} disabled={disabled}>
              {t("monitor.unit.mhz", { w })}
            </Chip>
          ))}
        </div>
      )}
      <div className="chmap" role="group" aria-label={t("monitor.map")}>
        {cells.map((c) => (
          <button
            key={c.name}
            type="button"
            className="chmap-cell t-caption"
            aria-pressed={picked.includes(c.name)}
            disabled={disabled || !c.reachable}
            title={`${mhz(c.center_hz)} MHz`}
            onClick={() => click(c.name)}
            data-testid={`cell-${c.name}`}
          >
            {c.name}
          </button>
        ))}
      </div>
      <div className="row">
        <Button variant="link" onClick={() => onChange([...reachable])} disabled={disabled}>
          {t("monitor.pick_all")}
        </Button>
        <Button variant="link" onClick={() => onChange([])} disabled={disabled}>
          {t("monitor.pick_none")}
        </Button>
        <span className="t-caption muted">{t("monitor.picked", { n: picked.length })}</span>
      </div>
      {cells.some((c) => !c.reachable) && <p className="t-caption muted">{t("monitor.unreachable")}</p>}
    </div>
  );
}

/**
 * 주파수 상태: ① 장비와 대역·채널을 고르고 ② 모니터링한다. 모니터링 중에 "설정으로 돌아가기"로 다시 고를 수 있다.
 */
export function SpectrumScreen() {
  const { api, fail } = useStore();
  const [device, setDevice] = useState("");
  const [info, setInfo] = useState<SurveyDevice | null>(null);
  const [plan, setPlan] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [custom, setCustom] = useState({ center: "", span: "", step: "" });
  const [gain, setGain] = useState("");
  const [mon, setMon] = useState<MonitorState | null>(null);
  const [running, setRunning] = useState(false);
  const [starting, setStarting] = useState(false);
  const alive = useRef(false);
  /** 사용자가 장비를 직접 골랐는가 */
  const chosen = useRef(false);
  const [wifi, setWifi] = useState(false);
  const [aps, setAps] = useState<WifiAp[] | null>(null);
  const [finding, setFinding] = useState(false);
  const [usigChannel, setUsigChannel] = useState("");
  const [usig, setUsig] = useState<UsigSample[]>([]);
  const [usigRef, setUsigRef] = useState<number | null>(null);
  const usigOn = useRef({ channel: "", plan: "", gain: "" });
  const viewer = useRef<SpectrumViewHandle>(null);

  // 사용자가 직접 고르기 전에는 실제 장비만 기본으로 고른다(모의 장비는 "모의 실험하기"를 눌러야 쓴다).
  // USRP 는 몇 초 늦게 나타나므로, 나타나면 그때 고른다.
  const { devices, mode, connect } = useUsableDevices();
  useEffect(() => {
    if (!devices) return;
    const real = devices.find((d) => d.driver !== "simulated");
    setDevice((cur) => (chosen.current && (cur === "" || devices.some((d) => d.id === cur)) ? cur : (real?.id ?? "")));
  }, [devices]);

  useEffect(() => {
    void api.wifiStatus().then((w) => setWifi(w.available), () => setWifi(false));
  }, [api]);

  const choosePlan = useCallback((p: SurveyPlan | undefined) => {
    setPlan(p?.id ?? "");
    // 파일 대역은 전부, 나머지는 사용자가 채널 맵에서 고른다
    setPicked(p?.id === "capture" ? (p.map ?? []).map((c) => c.name) : []);
    setAps(null);
  }, []);

  useEffect(() => {
    setInfo(null);
    if (!device) return;
    void api.surveyDevice(device).then(
      (i) => {
        setInfo(i);
        choosePlan(i.plans.find((p) => p.available));
      },
      (e: unknown) => fail(String(e instanceof Error ? e.message : e)),
    );
  }, [api, device, fail, choosePlan]);

  // 모니터링: 한 바퀴가 끝나면 잠깐 쉬고 다음 바퀴를 잰다. 화면을 떠나면 멈추고 서버의 모니터를 지운다.
  const monId = mon?.id;
  useEffect(() => {
    if (!running || !monId) return;
    alive.current = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const next = await api.monitorSweep(monId);
        if (!alive.current) return;
        setMon(next);
        // 실제 송신 대역폭 보기가 켜져 있으면 한 바퀴마다 그 채널을 짧게 받아 PPDU 머리말을 읽는다
        const u = usigOn.current;
        if (u.channel) {
          const res = await api.wifiUsig({ device: next.device, plan: u.plan, channel: u.channel, gain_db: u.gain.trim() ? Number(u.gain) : undefined });
          if (!alive.current) return;
          const at = Date.now();
          setUsig((old) => {
            const kept = [...old.filter((x) => at - x.at < USIG_KEEP_MS), { at, ppdus: res.ppdus }];
            setUsigRef((ref) => {
              if (ref !== null) return ref;
              const rows = countByWidth(kept, at, USIG_KEEP_MS);
              return rows.reduce((a, r) => a + r.count, 0) >= USIG_REFERENCE_MIN ? dominant(rows) : null;
            });
            return kept;
          });
        }
        timer = setTimeout(() => void tick(), PAUSE_MS);
      } catch (e) {
        if (!alive.current) return;
        setRunning(false);
        fail(String(e instanceof Error ? e.message : e));
      }
    };
    void tick();
    return () => {
      alive.current = false;
      clearTimeout(timer);
    };
  }, [api, fail, monId, running]);

  useEffect(
    () => () => {
      if (monId) void api.monitorStop(monId).catch(() => undefined);
    },
    [api, monId],
  );

  const current = info?.plans.find((p) => p.id === plan);
  const real = info?.device.driver !== "simulated";
  const mhzIn = (s: string) => (s.trim() ? Number(s) * 1e6 : undefined);
  const canStart = Boolean(plan) && (plan === "custom" ? Boolean(custom.center && custom.span && custom.step) : picked.length > 0);

  const begin = async () => {
    setStarting(true);
    try {
      const order = (current?.map ?? []).map((c) => c.name);
      setMon(
        await api.monitorStart({
          device,
          plan,
          channels: plan === "custom" ? undefined : [...picked].sort((a, b) => order.indexOf(a) - order.indexOf(b)),
          gain_db: gain.trim() ? Number(gain) : undefined,
          center_hz: mhzIn(custom.center),
          span_hz: mhzIn(custom.span),
          step_hz: mhzIn(custom.step),
        }),
      );
      setRunning(true);
    } catch (e) {
      fail(String(e instanceof Error ? e.message : e));
    } finally {
      setStarting(false);
    }
  };

  const back = () => {
    setRunning(false);
    setMon(null);
    watchUsig("");
  };

  const watchUsig = (name: string) => {
    usigOn.current = { channel: name, plan, gain };
    setUsigChannel(name);
    setUsig([]);
    setUsigRef(null);
  };

  const findAps = async () => {
    setFinding(true);
    try {
      setAps((await api.wifiAps({ device, plan, channels: picked, gain_db: gain.trim() ? Number(gain) : undefined })).aps);
    } catch (e) {
      fail(String(e instanceof Error ? e.message : e));
    } finally {
      setFinding(false);
    }
  };

  /** AP 가 쓰는 채널들(P20 이 속한 운용 폭 묶음)을 채널 맵에서 고른다. */
  const pickAp = (ap: WifiAp) => {
    const group = current?.groups?.[String(ap.width_mhz ?? 20)]?.find((g) => g.includes(ap.primary)) ?? [ap.primary];
    const ok = new Set((current?.map ?? []).filter((c) => c.reachable).map((c) => c.name));
    setPicked(group.filter((n) => ok.has(n)));
  };

  const patch = (body: { auto?: boolean; stat?: Stat; baseline?: "save" | "clear" }) => {
    if (!mon) return;
    void api.monitorPatch(mon.id, body).then(setMon, (e: unknown) => fail(String(e instanceof Error ? e.message : e)));
  };

  if (mon && info) {
    const stat = mon.stat;
    const rows = mon.channels;
    const waiting = rows.filter((r) => r.settle_s !== undefined && r.rise_db === undefined);
    const levelBars: Bar[] = rows.map((r) => ({
      name: r.name,
      value: r.measured ? (r[stat] ?? undefined) : undefined,
      base: r.baseline_dbfs,
      state: !r.measured ? "missing" : r.clipped ? "clipped" : "ok",
      title: r.measured ? `${r.name} · ${mhz(r.center_hz)} MHz · ${num(r[stat])} dBFS` : `${r.name} · ${t("spectrum.unmeasured")}`,
    }));
    const riseBars: Bar[] = rows.map((r) => ({
      name: r.name,
      value: r.rise_db,
      state: r.rise_db === undefined ? "missing" : r.raised ? "raised" : "ok",
      title: r.rise_db === undefined ? `${r.name} · ${t("monitor.no_baseline")}` : `${r.name} · ${num(r.rise_db, true)} dB`,
    }));
    return (
      <>
        <SubNav title={t("nav.spectrum")} action={<Button variant="secondary" onClick={back} data-testid="monitor-back">{`← ${t("monitor.back")}`}</Button>} />
        <Tile tone="light">
          <TileHead eyebrow={`${info.device.label} · ${t(`spectrum.plan.${mon.plan}`)}`} title={t("monitor.title", { n: rows.length })} lead={t("monitor.lead", { n: mon.smooth })}>
            <Button onClick={() => setRunning(!running)} data-testid="monitor-toggle">
              {running ? t("spectrum.repeat.stop") : t("monitor.resume")}
            </Button>
            <div className="chips" role="group" aria-label={t("spectrum.stat.label")}>
              {(["median_dbfs", "mean_dbfs"] as const).map((s) => (
                <Chip key={s} selected={s === stat} onSelect={() => patch({ stat: s })}>
                  {t(`spectrum.stat.${s}`)}
                </Chip>
              ))}
            </div>
          </TileHead>
          <div className="row center-row" data-testid="monitor-status">
            <Badge level="info">{t("monitor.sweeps", { n: mon.sweeps, s: mon.sweep_s ?? "—" })}</Badge>
            {mon.raised.length > 0 && <Badge level="warn">{t("monitor.raised", { names: mon.raised.join(", "), db: mon.rise_threshold_db })}</Badge>}
            {rows.some((r) => r.clipped) && <Badge level="warn">{t("spectrum.clipped")}</Badge>}
            {mon.baseline_note && <Badge level="ok">{t(`monitor.baseline.${mon.baseline_note}`)}</Badge>}
            {mon.forced.length > 0 && <Badge level="warn">{t("monitor.forced", { names: mon.forced.join(", ") })}</Badge>}
            {waiting.length > 0 && <Badge level="info">{t("monitor.settling", { s: Math.ceil(Math.max(...waiting.map((r) => r.settle_s ?? 0))) })}</Badge>}
          </div>
          <div className="row center-row">
            <label className="t-caption">
              <input type="checkbox" checked={mon.auto} onChange={(e) => patch({ auto: e.target.checked })} data-testid="monitor-auto" /> {t("monitor.auto")}
            </label>
            <Button variant="secondary" onClick={() => patch({ baseline: "save" })} disabled={mon.sweeps === 0} data-testid="monitor-save">
              {t("spectrum.baseline.save")}
            </Button>
            <Button variant="link" onClick={() => patch({ baseline: "clear" })} disabled={!mon.has_baseline} data-testid="monitor-clear">
              {t("spectrum.baseline.clear")}
            </Button>
          </div>
          {mon.sweeps === 0 ? (
            <Empty>{t("monitor.first")}</Empty>
          ) : (
            <>
              <div className="card">
                <Bars bars={levelBars} label={t("spectrum.chart.label")} yLabel={t("spectrum.axis.y")} testid="survey-bar" />
                <p className="t-caption muted center">{mon.has_baseline ? t("spectrum.chart.caption_base") : t("spectrum.chart.caption")}</p>
              </div>
              <div className="card stack-gap">
                <Bars bars={riseBars} label={t("monitor.rise.label")} yLabel={t("monitor.rise.axis")} zero testid="rise-bar" />
                <p className="t-caption muted center">{mon.has_baseline ? t("monitor.rise.caption", { db: mon.rise_threshold_db }) : t("monitor.rise.none")}</p>
              </div>
              <div className="table-wrap">
                <table className="data t-caption" data-testid="survey-table">
                  <caption className="sr-only">{t("spectrum.chart.label")}</caption>
                  <thead>
                    <tr>
                      {["name", "center", "median", "mean", "peak", "rise", ...(real ? ["look"] : [])].map((c) => (
                        <th key={c} scope="col" className={`t-caption-strong ${c === "name" ? "" : "right"}`}>
                          {t(`spectrum.col.${c}`)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
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
                        <td className="right">{num(r.rise_db, true)}</td>
                        {real && (
                          <td className="right">
                            <Button variant="link" onClick={() => viewer.current?.look(r.center_hz, r.width_hz)} data-testid={`survey-look-${r.name}`}>
                              {t("spectrum.look")}
                            </Button>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          {wifi && real && mon.plan.startsWith("wifi-") && (
            <BandwidthWatch channels={rows.map((r) => r.name)} channel={usigChannel} onChannel={watchUsig} samples={usig} reference={usigRef} now={Date.now()} />
          )}
          <details className="fold">
            <summary className="t-body">{t("spectrum.how.title")}</summary>
            <div className="fold-body t-caption">
              {["dwell", "mean", "median", "peak", "unit", "smooth", "auto"].map((k) => (
                <p key={k}>{t(`spectrum.how.${k}`, { ms: 20, n: mon.smooth })}</p>
              ))}
            </div>
          </details>
        </Tile>
        {real && <SpectrumView key={info.device.id} info={info} gain={gain} ref={viewer} paused={running} />}
      </>
    );
  }

  return (
    <>
      <SubNav title={t("nav.spectrum")} />
      <Tile tone="light">
        <TileHead title={t("spectrum.title")} lead={t("spectrum.lead")} />
        {mode === "none" && (
          <p className="t-caption muted" data-testid="no-device-mode">
            {t("hub.none_mode")}{" "}
            <Button variant="link" onClick={connect}>
              {t("hub.mine.reconnect")}
            </Button>
          </p>
        )}
        {devices !== null && (
          <DevicePicker
            devices={devices}
            device={device}
            disabled={starting}
            center
            onPick={(id) => {
              chosen.current = true;
              setDevice(id);
            }}
          />
        )}
        {info && (
          <div className="source-grid">
            <DeviceFacts info={info} />
            <div className="card" data-testid="survey-controls">
              <h3 className="t-tagline">{t("spectrum.plan.title")}</h3>
              <div className="chips" role="group" aria-label={t("spectrum.plan.title")}>
                {/* 이 장비로 쓸 수 있는 것만 보여 준다: 모의 장비에는 파일 대역만, 실제 장비에는 실제 대역만 */}
                {info.plans.filter((p) => p.available).map((p) => (
                  <Chip key={p.id} selected={p.id === plan} onSelect={() => choosePlan(p)} disabled={starting}>
                    {t(`spectrum.plan.${p.id}`)}
                  </Chip>
                ))}
              </div>
              <p className="t-caption muted">{real ? t("spectrum.plan.hint_real") : t("spectrum.plan.hint_sim")}</p>
              {current && plan !== "custom" && <ChannelMap key={plan} plan={current} picked={picked} onChange={setPicked} disabled={starting} />}
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
                <Button onClick={() => void begin()} disabled={starting || finding || !canStart} data-testid="monitor-start">
                  {t("monitor.start")}
                </Button>
                {wifi && real && plan.startsWith("wifi-") && (
                  <Button variant="secondary" onClick={() => void findAps()} disabled={finding || starting || picked.length === 0} data-testid="ap-find">
                    {finding ? t("wifi.aps.busy", { n: picked.length }) : t("wifi.aps.find")}
                  </Button>
                )}
              </div>
              {wifi && real && plan.startsWith("wifi-") && <p className="t-caption muted">{t("wifi.aps.hint")}</p>}
              {aps && <ApTable aps={aps} onPick={pickAp} />}
            </div>
          </div>
        )}
      </Tile>
      {info && <SpectrumView key={info.device.id} info={info} gain={gain} ref={viewer} />}
    </>
  );
}
