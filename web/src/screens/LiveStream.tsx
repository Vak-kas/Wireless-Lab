import { useEffect, useState } from "react";
import type { SpectrumView as View, StreamState } from "../api";
import { Spectrogram } from "../components/plots/Spectrogram";
import { LinePlot } from "../components/plots/LinePlot";
import { Badge } from "../components/ui";
import { t } from "../i18n";
import { useStore } from "../state/store";
import { BleTable } from "./BlePanel";
import { LiveScope } from "./LiveScope";
import { RecordFile } from "./SavedFiles";
import { plots } from "./SpectrumView";
import { ApTable } from "./WifiPanels";

const POLL_MS = 400;

interface StartRequest {
  device: string;
  center_hz: number;
  bandwidth_hz: number;
  gain_db?: number;
}

/**
 * 계속 받기(끊김 없이 받으면서 푸는 것)를 시작·멈추고 1초마다 상태를 묻는다.
 * 서버에 이 기능이 없으면(can=false) 화면은 단추를 보이지 않는다. 화면을 떠나면 멈춘다.
 */
export function useLiveStream(device: string) {
  const { api, fail } = useStore();
  const [state, setState] = useState<StreamState | null>(null);
  const [starting, setStarting] = useState(false);
  const [can, setCan] = useState(false);
  const id = state?.id;
  const running = state?.running ?? false;

  useEffect(() => {
    let on = true;
    api.streamTaps({ device, center_hz: 0, bandwidth_hz: 0 }).then(
      () => on && setCan(true),
      () => on && setCan(false),
    );
    return () => {
      on = false;
    };
  }, [api, device]);

  useEffect(() => {
    if (!id || !running) return;
    const timer = setInterval(() => {
      api.streamState(id).then(setState, () => undefined); // 한 번 못 물어도 다음에 다시 묻는다
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [api, id, running]);

  useEffect(
    () => () => {
      if (id) void api.streamStop(id).catch(() => undefined);
    },
    [api, id],
  );

  /** 이 조건에 맞는 풀이를 모두 꽂아 시작한다. record=true 면 파일로도 남긴다. */
  const start = async (req: StartRequest, record: boolean) => {
    setStarting(true);
    try {
      const { taps } = await api.streamTaps(req);
      const names = taps.filter((x) => x.ok && (x.name !== "record" || record)).map((x) => x.name);
      setState(await api.streamStart({ ...req, taps: names }));
    } catch (e) {
      fail(String(e instanceof Error ? e.message : e));
    } finally {
      setStarting(false);
    }
  };

  const stop = async () => {
    if (!id) return;
    try {
      setState(await api.streamStop(id));
    } catch (e) {
      fail(String(e instanceof Error ? e.message : e));
    }
  };

  /** 받는 도중에 풀이를 꽂거나 뺀다(녹화 시작·멈춤) */
  const tap = async (name: string, on: boolean) => {
    if (!id) return;
    try {
      setState(await api.streamTap(id, name, on));
    } catch (e) {
      fail(String(e instanceof Error ? e.message : e));
    }
  };

  return { state, running, starting, can, start, stop, tap };
}

/** 계속 받기의 상태 줄과, 꽂힌 풀이들의 결과. */
export function LiveResults({ state }: { state: StreamState }) {
  const taps = state.taps;
  const view = taps.spectrum?.view;
  const p = view ? plots(view as View) : null;
  const wifi = taps.wifi;
  const ble = taps.ble;
  const record = taps.record;
  const formats = Object.entries(wifi?.formats ?? {}).sort((a, b) => b[1] - a[1]);
  return (
    <div data-testid="live-results">
      <div className="row center-row" role="status" data-testid="live-status">
        <Badge level={state.running ? "info" : "ok"}>{t(state.running ? "live.running" : "live.stopped", { s: state.seconds.toFixed(1) })}</Badge>
        {state.continuous ? (
          <Badge level={state.lost_samples > 0 ? "warn" : "ok"}>{state.lost_samples > 0 ? t("live.lost", { n: state.lost_samples, o: state.overflows }) : t("live.no_loss")}</Badge>
        ) : (
          <Badge level="warn">{t("live.gapped")}</Badge>
        )}
        {Object.entries(taps).map(([name, tap]) => (
          <Badge key={name} level={tap.error || tap.skipped > 0 ? "warn" : "info"}>
            {t(`live.tap.${name}`)} · {tap.skipped > 0 ? t("live.tap.skipped", { done: tap.done, skipped: tap.skipped }) : t("live.tap.done", { done: tap.done })}
          </Badge>
        ))}
      </div>
      {state.error && <p className="t-caption muted center">! {state.error}</p>}
      {Object.entries(taps)
        .filter(([, tap]) => tap.error)
        .map(([name, tap]) => (
          <p key={name} className="t-caption muted center">
            ! {t(`live.tap.${name}`)}: {tap.error}
          </p>
        ))}
      {record?.data_path && (
        <div className="center" data-testid="live-record-box">
          <p className="t-caption" data-testid="live-record">
            {t(record.ended || !state.running ? "live.record.status" : "live.record.going", { s: record.seconds ?? 0, mb: ((record.bytes ?? 0) / 1e6).toFixed(1), gaps: record.gaps ?? 0 })}
            <br />
            <code>{record.data_path}</code>
          </p>
          <RecordFile dataPath={record.data_path} metaPath={record.meta_path} done={Boolean(record.ended) || !state.running} />
        </div>
      )}
      {wifi && (
        <div className="card live" data-testid="live-wifi">
          <h4 className="t-caption-strong">{t("live.wifi.title", { channel: wifi.channel ?? "" })}</h4>
          <ApTable aps={wifi.aps ?? []} empty={t("live.wifi.no_aps")} />
          {(wifi.frames_found ?? 0) > 0 && (
            <p className="t-caption muted" data-testid="live-wifi-frames">
              {wifi.frames_decoded === wifi.frames_found ? t("live.wifi.all", { n: wifi.frames_found ?? 0 }) : t("live.wifi.some", { n: wifi.frames_found ?? 0, m: wifi.frames_decoded ?? 0 })}
            </p>
          )}
          {formats.length > 0 && (
            <p className="t-caption muted">
              {t("live.wifi.formats")} {formats.map(([f, n]) => `${f} ${n}`).join(" · ")}
            </p>
          )}
        </div>
      )}
      {ble && (
        <div className="card live" data-testid="live-ble">
          <h4 className="t-caption-strong">{t("live.ble.title", { channel: ble.channel ?? "" })}</h4>
          <BleTable devices={ble.devices ?? []} directed={ble.directed ?? {}} broken={ble.crc_failed ?? 0} />
        </div>
      )}
      {state.scope ? (
        <LiveScope id={state.id} running={state.running} centerHz={state.center_hz} rateHz={state.sample_rate_hz} rowMs={state.scope.row_ms || 50} taps={state.taps} />
      ) : p && (
        <>
          <div className="card">
            <LinePlot plot={p.line} />
            <p className="t-caption muted center">{t("view.caption.spectrum")}</p>
          </div>
          <div className="card">
            <Spectrogram grid={view!.waterfall} label={t("view.plot.waterfall")} />
            <p className="t-caption muted center">{t("live.caption.waterfall", { s: ((view!.waterfall.cols * view!.waterfall.col_ms) / 1e3).toFixed(1) })}</p>
          </div>
        </>
      )}
    </div>
  );
}
