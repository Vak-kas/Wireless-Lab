import { useCallback, useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";
import type { Plot, SpectrumView as View, SurveyDevice } from "../api";
import { Tile, TileHead } from "../components/layout";
import { GridPlot } from "../components/plots/GridPlot";
import { LinePlot } from "../components/plots/LinePlot";
import { Badge, Button, Field } from "../components/ui";
import { t } from "../i18n";
import { useStore } from "../state/store";

const REPEAT_MS = 1500;
const mhz = (hz: number, digits = 3) => Number((hz / 1e6).toFixed(digits)).toString();

export interface SpectrumViewHandle {
  /** 다른 곳(채널 표)에서 "이 채널 들여다보기"를 눌렀을 때 */
  look(centerHz: number, bandwidthHz: number): void;
}

function plots(v: View): { line: Plot; fall: Plot } {
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

/** 가운데 주파수와 대역폭을 정해 그 대역을 들여다본다: 주파수별 세기(평균·최대)와 시간에 따른 변화. */
export function SpectrumView({ info, gain, ref }: { info: SurveyDevice; gain: string; ref?: Ref<SpectrumViewHandle> }) {
  const { api, fail } = useStore();
  const sim = info.device.driver === "simulated";
  const [center, setCenter] = useState(sim && info.capture ? mhz(info.capture.center_freq_hz) : "");
  const [width, setWidth] = useState(sim && info.capture ? mhz(info.capture.sample_rate_hz) : "");
  const [view, setView] = useState<View | null>(null);
  const [busy, setBusy] = useState(false);
  const [repeat, setRepeat] = useState(false);
  const [error, setError] = useState("");
  const running = useRef(false);
  const tile = useRef<HTMLDivElement>(null);

  const look = useCallback(
    async (c: string, w: string) => {
      if (running.current) return;
      if (!sim && !(Number(c) > 0 && Number(w) > 0)) {
        setError(t("view.error.inputs"));
        setRepeat(false);
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
        setRepeat(false);
        fail(String(e instanceof Error ? e.message : e));
      } finally {
        running.current = false;
        setBusy(false);
      }
    },
    [api, fail, gain, info.device.id, sim],
  );

  useImperativeHandle(ref, () => ({
    look(centerHz, bandwidthHz) {
      const c = mhz(centerHz);
      const w = mhz(bandwidthHz);
      setCenter(c);
      setWidth(w);
      tile.current?.scrollIntoView?.({ block: "start" });
      void look(c, w);
    },
  }));

  useEffect(() => {
    if (!repeat) return;
    void look(center, width);
    const timer = setInterval(() => void look(center, width), REPEAT_MS);
    return () => clearInterval(timer);
  }, [repeat, look, center, width]);

  const max = info.device.max_sample_rate_hz;
  const p = view ? plots(view) : null;

  return (
    <div ref={tile}>
      <Tile tone="light" id="spectrum-view">
        <TileHead eyebrow={t("view.eyebrow")} title={t("view.title")} lead={sim ? t("view.lead_sim") : t("view.lead")} />
        <div className="card view-controls" data-testid="view-controls">
          <div className="row">
            <Field label={t("view.center")} error={error || undefined}>
              {(f) => <input {...f} inputMode="decimal" value={center} disabled={sim} onChange={(e) => setCenter(e.target.value)} data-testid="view-center" />}
            </Field>
            <Field label={t("view.width")}>
              {(f) => <input {...f} inputMode="decimal" value={width} disabled={sim} onChange={(e) => setWidth(e.target.value)} data-testid="view-width" />}
            </Field>
          </div>
          {!sim && max !== undefined && <p className="t-caption muted">{t("view.max_width", { mhz: mhz(max) })}</p>}
          <div className="row">
            <Button onClick={() => void look(center, width)} disabled={busy || repeat} data-testid="view-run">
              {busy && !repeat ? t("spectrum.busy") : t("view.run")}
            </Button>
            <Button variant="secondary" onClick={() => setRepeat(!repeat)} aria-pressed={repeat} data-testid="view-repeat">
              {repeat ? t("spectrum.repeat.stop") : t("view.repeat")}
            </Button>
          </div>
        </div>
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
      </Tile>
    </div>
  );
}
