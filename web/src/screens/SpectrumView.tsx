import { useCallback, useEffect, useImperativeHandle, useRef, useState, type ReactNode, type Ref } from "react";
import type { Plot, SpectrumView as View, SurveyDevice } from "../api";
import { Tile, TileHead } from "../components/layout";
import { GridPlot } from "../components/plots/GridPlot";
import { LinePlot } from "../components/plots/LinePlot";
import { Badge, Button, Field } from "../components/ui";
import { t } from "../i18n";
import { useStore } from "../state/store";
import { LiveResults, useLiveStream } from "./LiveStream";

const mhz = (hz: number, digits = 3) => Number((hz / 1e6).toFixed(digits)).toString();

export interface SpectrumViewHandle {
  /** 다른 곳(채널 표)에서 "이 채널 들여다보기"를 눌렀을 때: 칸을 채우고 바로 본다 */
  look(centerHz: number, bandwidthHz: number): void;
  /** 칸만 채운다. 보기는 사용자가 단추로 한다 */
  set(centerHz: number, bandwidthHz: number): void;
}

export function plots(v: View): { line: Plot; fall: Plot } {
  const x = v.freq_hz.map((f) => f / 1e6);
  return {
    line: {
      id: "view-spectrum",
      type: "spectrum",
      title: t("view.plot.spectrum"),
      x: { label: t("view.axis.freq"), unit: "MHz" },
      y: { label: t("view.axis.level"), unit: "dBFS" },
      series: [
        { name: t("view.series.max"), x, y: v.max_db, role: "muted", mode: "line" },
        { name: t("view.series.mean"), x, y: v.mean_db, role: "primary", mode: "line" },
      ],
      annotations: [],
    },
    fall: {
      id: "view-waterfall",
      type: "waterfall",
      title: t("view.plot.waterfall"),
      grid: { rows: v.waterfall.rows, cols: v.waterfall.cols, values: v.waterfall.values, row_label: t("view.axis.freq_bin"), col_label: t("view.axis.time_bin") },
      annotations: [],
    },
  };
}

/**
 * 한 대역을 받아서 보여 준다: 한 번 보기, 계속 보기, 실시간으로 받기(끊김 없이), 녹화.
 *
 * - selector 를 주면(수신 화면) 그 "어디를 볼까요" 칸과 보기 단추를 한 칸에 담고, 볼 대역은 target 으로 받는다.
 * - selector 가 없으면(채널 모니터링 중) 가운데 주파수와 대역폭을 직접 넣는 칸이 나온다.
 * - paused: 채널 모니터가 장비를 쓰는 중이면 여기서 따로 받을 수 없다(장비는 하나).
 */
export function SpectrumView({
  info,
  gain,
  ref,
  paused,
  selector,
  target,
  stopSignal,
  onLive,
}: {
  info: SurveyDevice;
  gain: string;
  ref?: Ref<SpectrumViewHandle>;
  paused?: boolean;
  selector?: ReactNode;
  /** 위에서 고른 대역. null 이면 아직 고르지 않았다 */
  target?: { center_hz: number; width_hz: number } | null;
  /** 값이 바뀌면 실시간 받기를 멈춘다(작업판의 "모두 멈추기") */
  stopSignal?: number;
  /** 실시간으로 받는 중인지 바깥에 알린다 */
  onLive?: (running: boolean) => void;
}) {
  const { api, fail } = useStore();
  const sim = info.device.driver === "simulated";
  const [center, setCenter] = useState(sim && info.capture ? mhz(info.capture.center_freq_hz) : "");
  const [width, setWidth] = useState(sim && info.capture ? mhz(info.capture.sample_rate_hz) : "");
  const [view, setView] = useState<View | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const running = useRef(false);
  const max = info.device.max_sample_rate_hz;
  const tile = useRef<HTMLDivElement>(null);
  const live = useLiveStream(info.device.id);
  const liveRunning = live.running;
  const stopLive = live.stop;
  useEffect(() => onLive?.(liveRunning), [liveRunning, onLive]);
  useEffect(() => {
    if (stopSignal) void stopLive();
    // 신호가 바뀔 때만 멈춘다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stopSignal]);

  const look = useCallback(
    async (c: string, w: string) => {
      if (running.current) return;
      if (paused) {
        setError(t("view.error.paused"));
        return;
      }
      if (!sim && !(Number(c) > 0 && Number(w) > 0)) {
        setError(t(selector ? "view.target.none" : "view.error.inputs"));
        return;
      }
      setError("");
      running.current = true;
      setBusy(true);
      try {
        setView(
          await api.surveySpectrum({
            device: info.device.id,
            center_hz: sim ? undefined : Number(c) * 1e6,
            bandwidth_hz: sim ? undefined : Number(w) * 1e6,
            gain_db: gain.trim() ? Number(gain) : undefined,
          }),
        );
      } catch (e) {
        fail(String(e instanceof Error ? e.message : e));
      } finally {
        running.current = false;
        setBusy(false);
      }
    },
    [api, fail, gain, info.device.id, sim, paused, selector],
  );

  /** 볼 대역을 정한다. 폭이 장비가 받을 수 있는 것보다 넓으면 가운데 부분만 본다. run 이면 바로 한 번 본다 */
  const fill = (centerHz: number, bandwidthHz: number, run = false) => {
    const c = mhz(centerHz);
    const w = mhz(max !== undefined ? Math.min(bandwidthHz, max) : bandwidthHz);
    setCenter(c);
    setWidth(w);
    setError("");
    if (run) void look(c, w);
  };

  // 위에서 고른 대역이 바뀌면 따라간다
  const targetCenter = target?.center_hz;
  const targetWidth = target?.width_hz;
  useEffect(() => {
    if (target === undefined || sim) return;
    if (targetCenter && targetWidth) {
      setCenter(mhz(targetCenter));
      setWidth(mhz(max !== undefined ? Math.min(targetWidth, max) : targetWidth));
    } else {
      setCenter("");
      setWidth("");
    }
    setError("");
    // target 은 값(가운데·폭)으로만 본다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetCenter, targetWidth, sim, max]);

  /** 계속 받기: 지금 대역을 멈출 때까지 끊김 없이 받으면서, 맞는 풀이를 모두 돌린다 */
  const goLive = (record = false) => {
    if (paused) return setError(t("view.error.paused"));
    if (!sim && !(Number(center) > 0 && Number(width) > 0)) return setError(t(selector ? "view.target.none" : "view.error.inputs"));
    setError("");
    setView(null);
    void live.start({ device: info.device.id, center_hz: sim ? 0 : Number(center) * 1e6, bandwidth_hz: sim ? 0 : Number(width) * 1e6, gain_db: gain.trim() ? Number(gain) : undefined }, record);
  };
  const recordTap = live.state?.taps.record;
  const recording = live.running && recordTap !== undefined && !recordTap.ended;
  /** 녹화 단추: 받는 중이면 그때부터 저장을 시작하거나 멈추고, 받는 중이 아니면 받기와 저장을 함께 시작한다 */
  const toggleRecord = () => (live.running ? void live.tap("record", !recording) : goLive(true));

  useImperativeHandle(ref, () => ({
    look(centerHz, bandwidthHz) {
      tile.current?.scrollIntoView?.({ block: "start" });
      fill(centerHz, bandwidthHz, true);
    },
    set: fill,
  }));

  const p = view ? plots(view) : null;
  const clipped = !sim && max !== undefined && targetWidth !== undefined && targetWidth > max;

  const controls = (
    <div className={selector ? "card view-one" : "card view-controls"} data-testid="view-controls">
      {selector}
      {selector ? (
        !sim && (
          <p className="t-body view-target" role="status" data-testid="view-target">
            {center && width ? t("view.target", { c: center, w: width }) : t("view.target.none")}
            {clipped && <span className="t-caption muted"> {t("view.target.clipped", { mhz: mhz(max!) })}</span>}
          </p>
        )
      ) : (
        <>
          <div className="row">
            <Field label={t("view.center")} error={error || undefined}>
              {(f) => <input {...f} inputMode="decimal" value={center} disabled={sim} onChange={(e) => setCenter(e.target.value)} data-testid="view-center" />}
            </Field>
            <Field label={t("view.width")}>
              {(f) => <input {...f} inputMode="decimal" value={width} disabled={sim} onChange={(e) => setWidth(e.target.value)} data-testid="view-width" />}
            </Field>
          </div>
          {!sim && max !== undefined && <p className="t-caption muted">{t("view.max_width", { mhz: mhz(max) })}</p>}
        </>
      )}
      {selector && error && (
        <p className="t-caption" role="alert" data-testid="view-error">
          ! {error}
        </p>
      )}
      <div className="row">
        {live.can && (
          <>
            <Button onClick={() => (live.running ? void live.stop() : goLive())} disabled={live.starting || busy} aria-pressed={live.running} data-testid="live-toggle">
              {live.running ? t("live.stop") : live.starting ? t("live.starting") : t("live.start")}
            </Button>
            <Button variant="secondary" onClick={toggleRecord} disabled={live.starting || busy} aria-pressed={recording} data-testid="live-record-toggle">
              {recording ? `■ ${t("live.record.stop")}` : `● ${t("live.record")}`}
            </Button>
          </>
        )}
        <Button variant="secondary" onClick={() => void look(center, width)} disabled={busy || live.running} data-testid="view-run">
          {busy ? t("spectrum.busy") : t("view.run")}
        </Button>
      </div>
      {live.can && <p className="t-caption muted">{t("live.hint")}</p>}
    </div>
  );
  const results = (
    <>
      {live.state && <LiveResults state={live.state} />}
        {view && p && (
          <>
            <dl className="facts t-caption view-facts" data-testid="view-facts">
              {(
                [
                  ["center", `${mhz(view.center_hz)} MHz`],
                  ["width", `${mhz(view.sample_rate_hz)} MHz`],
                  ["total", `${view.total_dbfs.toFixed(1)} dBFS`],
                  ["peak", `${view.peak_dbfs.toFixed(1)} dBFS`],
                  ["resolution", `${(view.bin_hz / 1e3).toFixed(1)} kHz`],
                ] as const
              ).map(([k, v]) => (
                <div key={k}>
                  <dt className="muted">{t(`view.fact.${k}`)}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
            {view.clipped && <Badge level="warn">{t("spectrum.clipped")}</Badge>}
            <div className="card">
              <LinePlot plot={p.line} />
              <p className="t-caption muted center">{t("view.caption.spectrum")}</p>
            </div>
            <div className="card">
              <GridPlot plot={p.fall} />
              <p className="t-caption muted center">
                {t("view.caption.waterfall", { ms: Math.round(view.waterfall.cols * view.waterfall.col_ms), lo: view.waterfall.floor_db, hi: view.waterfall.ceil_db })}
              </p>
            </div>
          </>
        )}
    </>
  );


  if (selector) {
    return (
      <div ref={tile} id="spectrum-view">
        {controls}
        {results}
      </div>
    );
  }
  return (
    <div ref={tile}>
      <Tile tone="light" id="spectrum-view">
        <TileHead eyebrow={t("view.eyebrow")} title={t("view.title")} lead={sim ? t("view.lead_sim") : t("view.lead")} />
        {controls}
        {results}
      </Tile>
    </div>
  );
}
