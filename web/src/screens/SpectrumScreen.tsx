import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { BleDevice, MonitorState, StreamTapInfo, SurveyDevice, SurveyPlan, WifiAp } from "../api";
import { SubNav, Tile, TileHead } from "../components/layout";
import { linear, ticks } from "../components/plots/scale";
import { Badge, Button, Chip, Empty, Field, Fold } from "../components/ui";
import { t } from "../i18n";
import { useStore } from "../state/store";
import { useUsableDevices } from "../devices/DeviceHub";
import { takeIntent } from "../devices/intent";
import { DEFAULT_WIDTH_MHZ, loadBands, saveBands, type Band } from "./bands";
import { BleTable } from "./BlePanel";
import { DevicePicker } from "./DevicePicker";
import { SpectrumView, type SpectrumViewHandle } from "./SpectrumView";
import { ApTable, BandwidthWatch, countByWidth, dominant, FrameKinds, type UsigSample } from "./WifiPanels";

type Stat = "median_dbfs" | "mean_dbfs";
const PAUSE_MS = 200;
const USIG_KEEP_MS = 60_000;
/** 실시간 Wi-Fi 풀이를 하는 간격. 채널을 하나씩 돌아가며 받는다(풀이에 1초쯤 걸려 매 바퀴 하면 세기 그림이 느려진다) */
const LIVE_EVERY_MS = 2000;
/** 이 시간 동안 다시 안 잡힌 AP 는 목록에서 뺀다 */
const AP_KEEP_MS = 30_000;
const BLE_ADV = [37, 38, 39];
/** 수신이 이만큼 잇달아 실패하면 모니터링을 멈춘다(한두 번의 샘플 유실로는 멈추지 않는다) */
const MAX_FAILS = 3;
type Tab = "level" | "near" | "frames";
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

/**
 * 채널 맵: 칸을 누르면 그 칸이 속한 묶음(고르는 폭)을 한꺼번에 고르거나 푼다.
 * 폭을 바꾸면 이미 고른 채널이 새 폭의 묶음으로 넓어진다(반쪽만 고른 묶음이 남지 않게). 묶음은 테두리로 묶어 보여 준다.
 */
function ChannelMap({ plan, picked, onChange, disabled }: { plan: SurveyPlan; picked: string[]; onChange: (names: string[]) => void; disabled?: boolean }) {
  const [unit, setUnit] = useState(20);
  const cells = plan.map ?? [];
  const reachable = new Set(cells.filter((c) => c.reachable).map((c) => c.name));
  const groupOf = (name: string, width: number) => (plan.groups?.[String(width)]?.find((g) => g.includes(name)) ?? [name]).filter((n) => reachable.has(n));
  const click = (name: string) => {
    const group = groupOf(name, unit);
    const all = group.every((n) => picked.includes(n));
    onChange(all ? picked.filter((n) => !group.includes(n)) : [...picked, ...group.filter((n) => !picked.includes(n))]);
  };
  const changeUnit = (width: number) => {
    setUnit(width);
    const wider = new Set(picked.flatMap((n) => groupOf(n, width)));
    if (wider.size !== picked.length) onChange(cells.map((c) => c.name).filter((n) => wider.has(n)));
  };
  // 그리는 순서: 채널 맵 순서대로, 같은 묶음은 한 상자에
  const blocks: (typeof cells)[] = [];
  const placed = new Set<string>();
  for (const c of cells) {
    if (placed.has(c.name)) continue;
    const names = plan.groups?.[String(unit)]?.find((g) => g.includes(c.name)) ?? [c.name];
    const block = cells.filter((x) => names.includes(x.name));
    block.forEach((x) => placed.add(x.name));
    blocks.push(block);
  }
  const cell = (c: (typeof cells)[number]) => (
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
  );
  return (
    <div data-testid="channel-map" className="chmap-box">
      {(plan.widths?.length ?? 0) > 1 && (
        <div className="chmap-unit">
          <span className="t-caption muted">{t("monitor.unit")}</span>
          <div className="segments" role="group" aria-label={t("monitor.unit")}>
            {plan.widths!.map((w) => (
              <button key={w} type="button" className="segment t-caption" aria-pressed={w === unit} onClick={() => changeUnit(w)} disabled={disabled}>
                {t("monitor.unit.mhz", { w })}
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="chmap" role="group" aria-label={t("monitor.map")}>
        {blocks.map((block) =>
          block.length > 1 ? (
            <div key={block[0]!.name} className="chmap-group">
              {block.map(cell)}
            </div>
          ) : (
            cell(block[0]!)
          ),
        )}
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
/** device 를 주면 그 장비로 고정하고, embedded 면 작업판의 칸 안이라 화면 머리와 장비 고르기를 그리지 않는다. */
/** stopSignal: 값이 바뀌면 하던 받기를 멈춘다. onBusy: 받는 중인지 바깥에 알린다(둘 다 작업판이 쓴다). */
/** startSignal: 값이 바뀌면 지금 설정해 둔 대로 시작한다(작업판의 "모두 시작"). */
export function SpectrumScreen({
  device: fixed,
  embedded,
  stopSignal,
  startSignal,
  onBusy,
}: { device?: string; embedded?: boolean; stopSignal?: number; startSignal?: number; onBusy?: (busy: boolean) => void } = {}) {
  const { api, fail } = useStore();
  const [info, setInfo] = useState<SurveyDevice | null>(null);
  const [plan, setPlan] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  /** 사용자가 추가한 "볼 곳"들과, + 를 눌러 여는 추가 칸(닫혀 있으면 null) */
  const [bands, setBands] = useState(loadBands);
  const [adding, setAdding] = useState<{ name: string; center: string; width: string } | null>(null);
  /** 볼 대역을 사용자가 칸에 직접 적는 중인가. 그동안에는 위에서 고른 것으로 칸을 덮어쓰지 않는다 */
  const [typed, setTyped] = useState(false);
  /**
   * 이 칸에서 하는 일. 어느 것도 특정 통신 방식에 묶이지 않는다(볼 곳은 채널로 골라도, 주파수를 적어도 된다).
   *   live    실시간 보기: 한 대역을 계속 받아 그린다
   *   levels  세기 비교: 여러 곳(고른 채널들, 또는 적은 범위를 나눈 칸들)의 세기를 돌아가며 재서 비교한다
   *   decode  신호 해석: 그 대역에 맞는 풀이가 있으면 풀어서 보여 준다(Wi-Fi 비콘 → AP, 블루투스 광고 → 기기 …)
   */
  const [job, setJob] = useState<"live" | "levels" | "decode">("live");
  /** 사용자가 칸에 적은 가운데 주파수와 대역폭(MHz) */
  const [entered, setEntered] = useState({ center: 0, width: 0 });
  /** 세기 비교에서 적은 범위를 몇 칸으로 나눌지 */
  const [parts, setParts] = useState(8);
  /** 신호 해석: 이 대역에 풀이마다 맞는지와 안 맞는 이유(서버의 풀이 목록에서 온다) */
  const [fits, setFits] = useState<{ key: string; taps: StreamTapInfo[] }>({ key: "", taps: [] });
  const [bleFound, setBleFound] = useState<{ devices: BleDevice[]; directed: Record<string, number>; broken: number } | null>(null);
  const [gain, setGain] = useState("");
  const [mon, setMon] = useState<MonitorState | null>(null);
  const [running, setRunning] = useState(false);
  const [starting, setStarting] = useState(false);
  const alive = useRef(false);
  /** 첫 화면에서 넘어올 때 받은 쪽지(어느 장비로, 어느 대역을) */
  const [intent] = useState(takeIntent);
  /** 사용자가 장비를 직접 골랐는가 (쪽지로 넘어온 것도 고른 것으로 친다) */
  const chosen = useRef(intent !== null || fixed !== undefined);
  const [device, setDevice] = useState(fixed ?? intent?.device ?? "");
  const [wifi, setWifi] = useState(false);
  const wifiReady = useRef(false);
  const [aps, setAps] = useState<WifiAp[] | null>(null);
  const [finding, setFinding] = useState(false);
  const [usigChannel, setUsigChannel] = useState("");
  const [usig, setUsig] = useState<UsigSample[]>([]);
  const [usigRef, setUsigRef] = useState<number | null>(null);
  const [liveOn, setLiveOn] = useState(true);
  const [liveAps, setLiveAps] = useState<(WifiAp & { at: number })[]>([]);
  const live = useRef({ on: true, gain: "", next: 0, last: 0 });
  const [tab, setTab] = useState<Tab>("level");
  const [bleDevs, setBleDevs] = useState<(BleDevice & { at: number })[]>([]);
  const [bleOther, setBleOther] = useState<{ directed: Record<string, number>; broken: number }>({ directed: {}, broken: 0 });
  const [hiccup, setHiccup] = useState("");
  const fails = useRef(0);
  const viewer = useRef<SpectrumViewHandle>(null);
  const [liveOnAir, setLiveOnAir] = useState(false);
  useEffect(() => onBusy?.(running || liveOnAir), [running, liveOnAir, onBusy]);
  useEffect(() => {
    if (stopSignal) setRunning(false);
  }, [stopSignal]);

  // 사용자가 직접 고르기 전에는 실제 장비만 기본으로 고른다(모의 장비는 "모의 실험하기"를 눌러야 쓴다).
  // USRP 는 몇 초 늦게 나타나므로, 나타나면 그때 고른다.
  const { devices, mode, connect } = useUsableDevices();
  useEffect(() => {
    if (!devices || fixed !== undefined) return;
    const real = devices.find((d) => d.driver !== "simulated");
    setDevice((cur) => (chosen.current && (cur === "" || devices.some((d) => d.id === cur)) ? cur : (real?.id ?? "")));
  }, [devices, fixed]);

  useEffect(() => {
    void api.wifiStatus().then(
      (w) => {
        wifiReady.current = w.available;
        setWifi(w.available);
      },
      () => setWifi(false),
    );
  }, [api]);

  const choosePlan = useCallback((p: SurveyPlan | undefined) => {
    setTyped(false);
    setPlan(p?.id ?? "");
    // 파일 대역은 전부, 나머지는 사용자가 채널 맵에서 고른다
    setPicked(p?.id === "capture" ? (p.map ?? []).map((c) => c.name) : p?.id === "ble" ? BLE_ADV.map((c) => `ch${c}`) : []);
    setAps(null);
  }, []);

  useEffect(() => {
    setInfo(null);
    if (!device) return;
    void api.surveyDevice(device).then(
      (i) => {
        setInfo(i);
        const wanted = intent?.device === i.device.id ? i.plans.find((p) => p.id === intent.plan && p.available) : undefined;
        choosePlan(wanted ?? i.plans.find((p) => p.available && p.id !== "custom"));
        if (intent?.device === i.device.id && intent.focus === "view") {
          setTimeout(() => document.getElementById("spectrum-view")?.scrollIntoView?.({ block: "start" }), 50);
        }
      },
      (e: unknown) => fail(String(e instanceof Error ? e.message : e)),
    );
    // fail 은 오류가 뜰 때마다 새 함수가 된다. 넣어 두면 오류 하나에 장비 정보를 다시 읽어 고른 것과 적은 값이 다 풀린다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, device, choosePlan, intent]);

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
        fails.current = 0;
        setMon(next);
        setHiccup(next.channels.find((c) => c.error)?.error ?? "");
        await liveStep(next);
        if (!alive.current) return;
        timer = setTimeout(() => void tick(), PAUSE_MS);
      } catch (e) {
        if (!alive.current) return;
        const message = String(e instanceof Error ? e.message : e);
        fails.current += 1;
        if (fails.current >= MAX_FAILS) {
          setRunning(false);
          fail(message);
        } else {
          setHiccup(message);
          timer = setTimeout(() => void tick(), PAUSE_MS * 3);
        }
      }
    };

    /** 실시간 풀이: 몇 초마다 채널 하나를 짧게 받아 Wi-Fi 는 비콘·프레임 머리말을, 블루투스는 광고를 읽는다. 실패해도 모니터링은 계속한다. */
    const liveStep = async (next: MonitorState) => {
      const lv = live.current;
      if (!lv.on || Date.now() - lv.last < LIVE_EVERY_MS) return;
      const gain_db = lv.gain.trim() ? Number(lv.gain) : undefined;
      try {
        if (next.plan === "ble") {
          const channel = BLE_ADV[lv.next % BLE_ADV.length]!;
          lv.next += 1;
          const res = await api.bleScan({ device: next.device, channel, gain_db });
          if (!alive.current) return;
          const at = Date.now();
          lv.last = at;
          setBleOther((old) => {
            const directed = { ...old.directed };
            for (const [k, v] of Object.entries(res.directed)) directed[k] = (directed[k] ?? 0) + v;
            return { directed, broken: old.broken + res.crc_failed };
          });
          setBleDevs((old) => {
            const map = new Map(old.filter((d) => at - d.at < AP_KEEP_MS).map((d) => [d.address, d]));
            for (const d of res.devices) {
              const cur = map.get(d.address);
              map.set(d.address, {
                ...d,
                name: d.name || cur?.name || "",
                company: d.company || cur?.company || "",
                company_id: d.company_id ?? cur?.company_id ?? null,
                pdu_types: [...new Set([...(cur?.pdu_types ?? []), ...d.pdu_types])],
                count: (cur?.count ?? 0) + d.count,
                power_db: Math.max(d.power_db, cur?.power_db ?? -999),
                channel: cur && cur.power_db > d.power_db ? cur.channel : d.channel,
                at,
              });
            }
            return [...map.values()].sort((x, y) => y.power_db - x.power_db);
          });
        } else if (wifiReady.current && next.plan.startsWith("wifi-")) {
          const names = next.channels.filter((c) => c.measured).map((c) => c.name);
          if (names.length === 0) return;
          const channel = names[lv.next % names.length]!;
          lv.next += 1;
          const res = await api.wifiLive({ device: next.device, plan: next.plan, channel, gain_db });
          if (!alive.current) return;
          const at = Date.now();
          lv.last = at;
          setUsig((old) => [...old.filter((x) => at - x.at < USIG_KEEP_MS), { at, channel, ppdus: res.ppdus }]);
          setLiveAps((old) => {
            // 같은 AP 가 여러 채널에서 잡히면 가장 센 쪽을 남긴다. 한동안 안 잡힌 AP 는 뺀다.
            const map = new Map(old.filter((ap) => at - ap.at < AP_KEEP_MS).map((ap) => [ap.bssid, ap]));
            for (const ap of res.aps) {
              const cur = map.get(ap.bssid);
              map.set(ap.bssid, { ...(cur && cur.power_db > ap.power_db ? cur : ap), at });
            }
            return [...map.values()].sort((x, y) => y.power_db - x.power_db);
          });
        }
      } catch (e) {
        if (!alive.current) return;
        lv.last = Date.now();
        setHiccup(String(e instanceof Error ? e.message : e));
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
  /** 고른 것이 사용자가 추가한 대역이면 그것 (plan 이 "band:<id>") */
  const band = bands.find((x) => `band:${x.id}` === plan);

  // 지금 볼 대역: 추가한 대역이면 그 값, 채널을 골랐으면 고른 채널들의 한가운데와 전체 폭
  const cellsPicked = (current?.map ?? []).filter((c) => picked.includes(c.name));
  const lo = cellsPicked.length ? Math.min(...cellsPicked.map((c) => c.center_hz - c.width_hz / 2)) : 0;
  const hi = cellsPicked.length ? Math.max(...cellsPicked.map((c) => c.center_hz + c.width_hz / 2)) : 0;
  const targetCenter = band ? band.center_mhz * 1e6 : cellsPicked.length ? (lo + hi) / 2 : 0;
  const targetWidth = band ? band.width_mhz * 1e6 : hi - lo;
  const target = useMemo(() => (targetCenter > 0 && targetWidth > 0 ? { center_hz: targetCenter, width_hz: targetWidth } : null), [targetCenter, targetWidth]);

  /**
   * 사용자가 가운데 주파수와 대역폭을 직접 적었다. 그 범위가 어느 대역의 채널(들)과 딱 맞으면 그 채널을 체크하고,
   * 맞지 않으면 아무 채널도 체크하지 않는다(적은 값 그대로 본다).
   */
  const matchTyped = (centerMhz: number, widthMhz: number) => {
    setTyped(true);
    setEntered({ center: centerMhz, width: widthMhz });
    setAps(null);
    const lo = (centerMhz - widthMhz / 2) * 1e6;
    const hi = (centerMhz + widthMhz / 2) * 1e6;
    const tol = 0.6e6;
    const plans = [...(current ? [current] : []), ...(info?.plans ?? []).filter((p) => p.available && p.id !== "custom" && p.id !== current?.id)];
    if (centerMhz > 0 && widthMhz > 0) {
      for (const p of plans) {
        const inside = (p.map ?? []).filter((c) => c.reachable && c.center_hz - c.width_hz / 2 >= lo - tol && c.center_hz + c.width_hz / 2 <= hi + tol);
        if (inside.length === 0) continue;
        const first = Math.min(...inside.map((c) => c.center_hz - c.width_hz / 2));
        const last = Math.max(...inside.map((c) => c.center_hz + c.width_hz / 2));
        if (Math.abs(first - lo) <= tol && Math.abs(last - hi) <= tol) {
          setPlan(p.id);
          setPicked(inside.map((c) => c.name));
          return;
        }
      }
    }
    setPicked([]);
    // 채널과 딱 맞지는 않는다. 적은 주파수가 어느 대역 안이면 그 대역만 고른 채로 두고(채널은 체크하지 않는다),
    // 어느 대역에도 들지 않으면 대역 단추의 선택도 푼다. 한 글자씩 적는 동안 풀렸던 대역도 값이 다 적히면 여기서 돌아온다.
    const hz = centerMhz * 1e6;
    const home = plans.find((p) => {
      const cells = p.map ?? [];
      return cells.length > 0 && hz >= Math.min(...cells.map((c) => c.center_hz - c.width_hz / 2)) && hz <= Math.max(...cells.map((c) => c.center_hz + c.width_hz / 2));
    });
    setPlan(home?.id ?? "");
  };

  // 지금 볼 범위: 고른 것(채널·추가한 곳)이 있으면 그것, 없으면 칸에 적은 값
  const rangeCenter = target ? target.center_hz : typed && entered.center > 0 && entered.width > 0 ? entered.center * 1e6 : 0;
  const rangeWidth = target ? target.width_hz : typed && entered.center > 0 && entered.width > 0 ? entered.width * 1e6 : 0;
  const hasRange = rangeCenter > 0 && rangeWidth > 0;
  /** 세기 비교를 채널로 하는가(채널을 골랐다), 범위를 나눠서 하는가(주파수를 적었거나 추가한 곳을 골랐다) */
  const byChannels = Boolean(current) && !band && picked.length > 0;
  const canStart = byChannels || (real && hasRange);
  const doing = real ? job : "live";
  /** 이 대역을 푸는 방법: 대역(채널 계획)에 묶인 풀이가 있으면 그것 */
  const decoder = plan.startsWith("wifi-") && wifi ? "wifi" : plan === "ble" ? "ble" : null;
  const fitKey = `${device}|${rangeCenter}|${rangeWidth}`;
  useEffect(() => {
    if (job !== "decode" || !device || !(rangeCenter > 0) || !(rangeWidth > 0)) return;
    let on = true;
    const key = `${device}|${rangeCenter}|${rangeWidth}`;
    const timer = setTimeout(() => {
      void api.streamTaps({ device, center_hz: rangeCenter, bandwidth_hz: rangeWidth }).then(
        (r) => on && setFits({ key, taps: r.taps.filter((x) => x.name !== "spectrum" && x.name !== "record") }),
        () => on && setFits({ key, taps: [] }),
      );
    }, 300);
    return () => {
      on = false;
      clearTimeout(timer);
    };
  }, [api, job, device, rangeCenter, rangeWidth]);
  const fitTaps = fits.key === fitKey ? fits.taps : [];
  const gainField = real ? (
    <Field label={t("spectrum.gain")}>
      {(p) => <input {...p} inputMode="decimal" value={gain} onChange={(e) => setGain(e.target.value)} data-testid="rx-gain" />}
    </Field>
  ) : null;

  // "모두 시작": 세기 비교를 골라 둔 칸은 그것을 시작한다(실시간 보기는 아래의 SpectrumView 가 시작한다). 멈춰 둔 모니터가 있으면 다시 돌린다
  useEffect(() => {
    if (!startSignal) return;
    if (mon) setRunning(true);
    else if (doing === "levels" && canStart && !starting) void begin();
    // 신호가 바뀔 때만 시작한다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startSignal]);

  const keepBands = (next: Band[]) => {
    setBands(next);
    saveBands(next);
  };
  /** + 칸에 적은 것을 "볼 곳"으로 추가하고 바로 고른다. 대역폭을 비우면 DEFAULT_WIDTH_MHZ, 이름을 비우면 주파수가 이름이 된다 */
  const addBand = () => {
    if (!adding || !(Number(adding.center) > 0)) return;
    const center = Number(adding.center);
    const width = Number(adding.width) > 0 ? Number(adding.width) : DEFAULT_WIDTH_MHZ;
    const made: Band = { id: String(Date.now()), name: adding.name.trim() || `${center} MHz`, center_mhz: center, width_mhz: width };
    keepBands([...bands, made]);
    setAdding(null);
    setTyped(false);
    setPlan(`band:${made.id}`);
    setPicked([]);
    setAps(null);
  };
  const removeBand = (id: string) => {
    keepBands(bands.filter((x) => x.id !== id));
    if (plan === `band:${id}`) choosePlan(info?.plans.find((x) => x.available && x.id !== "custom"));
  };

  const begin = async () => {
    setStarting(true);
    try {
      const order = (current?.map ?? []).map((c) => c.name);
      const gain_db = gain.trim() ? Number(gain) : undefined;
      setMon(
        await api.monitorStart(
          byChannels
            ? { device, plan, channels: [...picked].sort((a, b) => order.indexOf(a) - order.indexOf(b)), gain_db }
            : // 채널이 없는 곳: 적은 범위를 같은 폭의 칸으로 나눠 칸마다 잰다
              { device, plan: "custom", center_hz: rangeCenter, span_hz: rangeWidth, step_hz: rangeWidth / parts, gain_db },
        ),
      );
      live.current = { on: liveOn, gain, next: 0, last: 0 };
      fails.current = 0;
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
    setUsigChannel("");
    setUsigRef(null);
    setUsig([]);
    setLiveAps([]);
    setBleDevs([]);
    setBleOther({ directed: {}, broken: 0 });
    setHiccup("");
    setTab("level");
  };

  // 처음 자리 잡은 송신 폭: 지켜보는 범위에서 Wi-Fi 7 다운링크 프레임이 충분히 모였을 때 가장 많던 폭
  useEffect(() => {
    if (usigRef !== null || usig.length === 0) return;
    const scope = usigChannel ? usig.filter((x) => x.channel === usigChannel) : usig;
    const counted = countByWidth(scope, Date.now(), USIG_KEEP_MS);
    if (counted.reduce((a, r) => a + r.count, 0) >= USIG_REFERENCE_MIN) setUsigRef(dominant(counted));
  }, [usig, usigChannel, usigRef]);

  const watchUsig = (name: string) => {
    setUsigChannel(name);
    setUsigRef(null);
  };
  const toggleLive = (on: boolean) => {
    live.current.on = on;
    setLiveOn(on);
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

  /** 블루투스 LE: 광고 채널 셋을 차례로 받아 주변 기기를 모은다(누구나 받으라고 보내는 광고만 읽는다) */
  const findBle = async () => {
    setFinding(true);
    try {
      const devices = new Map<string, BleDevice>();
      const directed: Record<string, number> = {};
      let broken = 0;
      for (const channel of BLE_ADV) {
        const res = await api.bleScan({ device, channel, gain_db: gain.trim() ? Number(gain) : undefined });
        broken += res.crc_failed;
        for (const [k, v] of Object.entries(res.directed)) directed[k] = (directed[k] ?? 0) + v;
        for (const d of res.devices) {
          const seen = devices.get(d.address);
          devices.set(d.address, seen ? { ...(d.power_db > seen.power_db ? d : seen), name: d.name || seen.name, count: seen.count + d.count } : d);
        }
      }
      setBleFound({ devices: [...devices.values()].sort((a, b) => b.power_db - a.power_db), directed, broken });
    } catch (e) {
      fail(String(e instanceof Error ? e.message : e));
    } finally {
      setFinding(false);
    }
  };

  /** AP 가 쓰는 채널들(P20 이 속한 운용 폭 묶음)을 채널 맵에서 고른다. */
  const pickAp = (ap: WifiAp) => {
    setTyped(false);
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
    const isBle = mon.plan === "ble";
    const tabs: Tab[] = isBle && real ? ["level", "near"] : wifi && real && mon.plan.startsWith("wifi-") ? ["level", "near", "frames"] : ["level"];
    const riseBars: Bar[] = rows.map((r) => ({
      name: r.name,
      value: r.rise_db,
      state: r.rise_db === undefined ? "missing" : r.raised ? "raised" : "ok",
      title: r.rise_db === undefined ? `${r.name} · ${t("monitor.no_baseline")}` : `${r.name} · ${num(r.rise_db, true)} dB`,
    }));
    return (
      <>
        {embedded ? (
          <p className="row">
            <Button variant="secondary" onClick={back} data-testid="monitor-back">{`← ${t("monitor.back")}`}</Button>
          </p>
        ) : (
          <SubNav title={t("nav.spectrum")} action={<Button variant="secondary" onClick={back} data-testid="monitor-back">{`← ${t("monitor.back")}`}</Button>} />
        )}
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
            {waiting.length > 0 &&
              (Math.max(...waiting.map((r) => r.settle_s ?? 0)) > 0 ? (
                <Badge level="info">{t("monitor.settling", { s: Math.ceil(Math.max(...waiting.map((r) => r.settle_s ?? 0))) })}</Badge>
              ) : (
                <Badge level="info">{t("monitor.shaky", { names: waiting.map((r) => r.name).join(", ") })}</Badge>
              ))}
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
          {hiccup && (
            <p className="t-caption muted center" role="status" data-testid="monitor-hiccup">
              ! {t("monitor.hiccup", { message: hiccup })}
            </p>
          )}
          <div className="tabs" role="tablist" aria-label={t("monitor.tabs")}>
            {tabs.map((id) => (
              <button key={id} type="button" role="tab" aria-selected={tab === id} className="tab t-body" onClick={() => setTab(id)} data-testid={`tab-${id}`}>
                {t(`monitor.tab.${id}${id === "near" && isBle ? ".ble" : ""}`)}
                {id === "near" && <span className="tab-count">{isBle ? bleDevs.length : liveAps.length}</span>}
              </button>
            ))}
            {tabs.length > 1 && (
              <label className="t-caption tab-toggle">
                <input type="checkbox" checked={liveOn} onChange={(e) => toggleLive(e.target.checked)} data-testid="wifi-live-toggle" /> {t("wifi.live.on")}
              </label>
            )}
          </div>

          {tab === "level" &&
            (mon.sweeps === 0 ? (
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
                            {c === "look" ? <span className="sr-only">{t("spectrum.look")}</span> : t(`spectrum.col.${c}`)}
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
            ))}

          {tab === "near" && (
            <div className="card live" data-testid="wifi-live">
              <p className="t-caption muted">{isBle ? t("ble.desc") : t("wifi.live.desc")}</p>
              {!liveOn ? (
                <p className="t-caption muted">{t("wifi.live.off")}</p>
              ) : isBle ? (
                <BleTable devices={bleDevs} directed={bleOther.directed} broken={bleOther.broken} />
              ) : (
                <ApTable aps={liveAps} empty={t("wifi.live.no_aps")} />
              )}
            </div>
          )}

          {tab === "frames" && (
            <div className="card live" data-testid="wifi-frames">
              <p className="t-caption muted">{t("wifi.live.desc")}</p>
              {!liveOn ? (
                <p className="t-caption muted">{t("wifi.live.off")}</p>
              ) : (
                <>
                  <h4 className="t-caption-strong">{t("wifi.kinds.title")}</h4>
                  <FrameKinds samples={usig} now={Date.now()} order={rows.map((r) => r.name)} />
                  <BandwidthWatch
                    channels={rows.map((r) => r.name)}
                    channel={usigChannel}
                    onChannel={watchUsig}
                    samples={usigChannel ? usig.filter((x) => x.channel === usigChannel) : usig}
                    reference={usigRef}
                    now={Date.now()}
                  />
                </>
              )}
            </div>
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
        {real && <SpectrumView key={info.device.id} info={info} gain={gain} ref={viewer} paused={running} stopSignal={stopSignal} onLive={setLiveOnAir} />}
      </>
    );
  }

  return (
    <>
      {!embedded && <SubNav title={t("nav.spectrum")} />}
      <Tile tone="light">
        {!embedded && <TileHead title={t("spectrum.title")} lead={t("spectrum.lead")} />}
        {!embedded && mode === "none" && (
          <p className="t-caption muted" data-testid="no-device-mode">
            {t("hub.none_mode")}{" "}
            <Button variant="link" onClick={connect}>
              {t("hub.mine.reconnect")}
            </Button>
          </p>
        )}
        {!embedded && devices !== null && (
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
          <>
            <SpectrumView
              key={info.device.id}
              info={info}
              gain={gain}
              ref={viewer}
              target={real && !typed ? target : undefined}
              onEdit={matchTyped}
              gainField={gainField}
              actions={
                doing === "levels" ? (
                  <div data-testid="levels-go">
                    {!byChannels && hasRange && (
                      <div className="row job-go">
                        <span className="t-caption muted">{t("levels.split")}</span>
                        <div className="segments" role="group" aria-label={t("levels.split")}>
                          {[4, 8, 16].map((n) => (
                            <button key={n} type="button" className="segment t-caption" aria-pressed={parts === n} onClick={() => setParts(n)} data-testid={`levels-parts-${n}`}>
                              {n}
                            </button>
                          ))}
                        </div>
                        <span className="t-caption muted">{t("levels.split.each", { mhz: Number((rangeWidth / parts / 1e6).toFixed(3)) })}</span>
                      </div>
                    )}
                    <div className="row job-go">
                      <Button onClick={() => void begin()} disabled={starting || finding || !canStart} data-testid="monitor-start">
                        {t("monitor.start")}
                      </Button>
                    </div>
                    <p className="t-caption muted">{t(byChannels ? "levels.by_channels" : hasRange ? "levels.by_range" : "levels.need")}</p>
                  </div>
                ) : doing === "decode" ? (
                  <div data-testid="decode-go">
                    {decoder === "wifi" && (
                      <>
                        <p className="t-caption">{t("decode.fits", { name: t("decode.wifi") })}</p>
                        <div className="row job-go">
                          <Button onClick={() => void findAps()} disabled={finding || starting || picked.length === 0} data-testid="ap-find">
                            {finding ? t("wifi.aps.busy", { n: picked.length }) : t("wifi.aps.find")}
                          </Button>
                        </div>
                        <p className="t-caption muted">{t("wifi.aps.hint")}</p>
                        {aps && <ApTable aps={aps} onPick={pickAp} />}
                      </>
                    )}
                    {decoder === "ble" && (
                      <>
                        <p className="t-caption">{t("decode.fits", { name: t("decode.ble") })}</p>
                        <div className="row job-go">
                          <Button onClick={() => void findBle()} disabled={finding || starting} data-testid="ble-find">
                            {finding ? t("decode.ble.busy") : t("decode.ble.find")}
                          </Button>
                        </div>
                        {bleFound && <BleTable devices={bleFound.devices} directed={bleFound.directed} broken={bleFound.broken} />}
                      </>
                    )}
                    {decoder === null && (
                      <div data-testid="decode-none">
                        <p className="t-caption">{t(hasRange ? "decode.none" : "decode.need")}</p>
                        {fitTaps.length > 0 && (
                          <ul className="t-caption muted decode-list">
                            {fitTaps.map((x) => (
                              <li key={x.name}>
                                {t(`live.tap.${x.name}`)}: {x.ok ? t("decode.tap.ok") : x.reason}
                              </li>
                            ))}
                          </ul>
                        )}
                        <p className="t-caption muted">{t("decode.none.hint")}</p>
                      </div>
                    )}
                  </div>
                ) : undefined
              }
              stopSignal={stopSignal}
              startSignal={doing === "live" ? startSignal : undefined}
              onLive={setLiveOnAir}
              selector={
                <div className="selector" data-testid="survey-controls">
                  {real && (
                    <>
                      <div className="segments jobs" role="group" aria-label={t("job.label")}>
                        {(["live", "levels", "decode"] as const).map((j) => (
                          <button key={j} type="button" className="segment t-caption" aria-pressed={doing === j} disabled={starting} onClick={() => setJob(j)} data-testid={`job-${j}`}>
                            {t(`job.${j}`)}
                          </button>
                        ))}
                      </div>
                      <p className="t-caption muted">{t(`job.${doing}.hint`)}</p>
                    </>
                  )}
                  <h3 className="t-tagline">{t("spectrum.plan.title")}</h3>
                  <div className="chips" role="group" aria-label={t("spectrum.plan.title")}>
                    {/* 이 장비로 쓸 수 있는 것만: 모의 장비에는 파일 대역만, 실제 장비에는 실제 대역과 사용자가 추가한 곳 */}
                    {info.plans
                      .filter((p) => p.available && p.id !== "custom")
                      .map((p) => (
                        <Chip
                          key={p.id}
                          selected={p.id === plan && adding === null}
                          onSelect={() => {
                            setAdding(null);
                            choosePlan(p);
                          }}
                          disabled={starting}
                        >
                          {t(`spectrum.plan.${p.id}`)}
                        </Chip>
                      ))}
                    {real &&
                      bands.map((x) => (
                        <span key={x.id} className="chip-pair">
                          <Chip
                            selected={plan === `band:${x.id}` && adding === null}
                            onSelect={() => {
                              setAdding(null);
                              setTyped(false);
                              setPlan(`band:${x.id}`);
                              setPicked([]);
                              setAps(null);
                            }}
                            disabled={starting}
                          >
                            {x.name}
                          </Chip>
                          <button type="button" className="chip-remove t-caption" aria-label={t("view.band.remove", { name: x.name })} onClick={() => removeBand(x.id)}>
                            ×
                          </button>
                        </span>
                      ))}
                    {real && (
                      <button
                        type="button"
                        className="chip chip-add t-caption"
                        aria-pressed={adding !== null}
                        aria-label={t("view.band.add")}
                        title={t("view.band.add")}
                        onClick={() => setAdding(adding === null ? { name: "", center: "", width: "" } : null)}
                        data-testid="band-add"
                      >
                        +
                      </button>
                    )}
                  </div>
                  {adding !== null && (
                    <div className="card add-band" data-testid="band-form">
                      <div className="row">
                        <Field label={t("view.center")}>
                          {(f) => <input {...f} inputMode="decimal" autoFocus value={adding.center} onChange={(e) => setAdding({ ...adding, center: e.target.value })} onKeyDown={(e) => e.key === "Enter" && addBand()} data-testid="band-center" />}
                        </Field>
                        <Field label={t("view.band.width", { n: DEFAULT_WIDTH_MHZ })}>
                          {(f) => <input {...f} inputMode="decimal" value={adding.width} onChange={(e) => setAdding({ ...adding, width: e.target.value })} onKeyDown={(e) => e.key === "Enter" && addBand()} data-testid="band-width" />}
                        </Field>
                        <Field label={t("view.band.name")}>
                          {(f) => <input {...f} value={adding.name} onChange={(e) => setAdding({ ...adding, name: e.target.value })} onKeyDown={(e) => e.key === "Enter" && addBand()} data-testid="band-name" />}
                        </Field>
                      </div>
                      <div className="row">
                        <Button onClick={addBand} disabled={!(Number(adding.center) > 0)} data-testid="band-save">
                          {t("view.band.save")}
                        </Button>
                        <Button variant="link" onClick={() => setAdding(null)}>
                          {t("view.band.cancel")}
                        </Button>
                      </div>
                    </div>
                  )}
                  {/* + 로 볼 곳을 추가하는 동안에는 그 칸만 보인다(채널 맵과 안내는 대역을 골랐을 때의 것이다) */}
                  {!band && adding === null && <p className="t-caption muted">{t(real ? "spectrum.plan.hint_real" : "spectrum.plan.hint_sim")}</p>}
                  {current && !band && adding === null && (
                    <ChannelMap
                      key={plan}
                      plan={current}
                      picked={picked}
                      onChange={(names) => {
                        setTyped(false);
                        setPicked(names);
                      }}
                      disabled={starting}
                    />
                  )}
                  {!real && current && !band && (
                    <div className="row job-go">
                      <Button onClick={() => void begin()} disabled={starting || finding || !canStart} data-testid="monitor-start">
                        {t("monitor.start")}
                      </Button>
                    </div>
                  )}
                </div>
              }
            />
            <Fold title={t("spectrum.device_info", { label: info.device.label })}>
              <DeviceFacts info={info} />
            </Fold>
          </>
        )}
      </Tile>
    </>
  );
}
