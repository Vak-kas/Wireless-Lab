import { useEffect, useState } from "react";
import type { RelayState, SpectrumView as View } from "../api";
import { LinePlot } from "../components/plots/LinePlot";
import { Spectrogram } from "../components/plots/Spectrogram";
import { Badge, Button } from "../components/ui";
import { t } from "../i18n";
import { useStore } from "../state/store";
import { RelayTargetLine } from "./RelayTarget";
import { plots } from "./SpectrumView";

/**
 * 중계 서버에서 받기: 방의 받는 쪽에 붙어, 다른 곳에서 보내는 I/Q 를 그림으로 보고 SigMF 파일로 남긴다.
 * 남긴 파일은 "분석하기"로 이 화면에서 바로 연다. 받은 것으로 하는 일은 보기·저장·분석까지다(다시 내보내는 길은 없다).
 * 서버에 이 기능이 없으면(공개판) 아무것도 그리지 않는다.
 */

const POLL_MS = 500;
const mb = (bytes: number) => (bytes / 1e6).toFixed(1);
const mhz = (hz: number | undefined) => (hz ? (hz / 1e6).toFixed(3) : "?");

export function RelayReceive({ onOpen }: { onOpen: (path: string) => void }) {
  const { api } = useStore();
  const [state, setState] = useState<RelayState | null>(null);
  const [record, setRecord] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    void api.relayState().then(
      (s) => alive && setState(s),
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, [api]);

  const running = state?.recv?.running ?? false;
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => {
      api.relayState().then(setState, () => undefined);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [api, running]);

  if (!state?.available) return null;
  const target = state.recv_target ?? null;
  const recv = state.recv ?? null;
  const sig = recv?.signal ?? null;
  const p = recv?.view ? plots(recv.view as View) : null;

  const run = async (work: () => Promise<RelayState>) => {
    setBusy(true);
    setError("");
    try {
      setState(await work());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relay-box t-caption" data-testid="relay-recv">
      <RelayTargetLine
        id="relay-recv"
        title={t("relay.recv.from")}
        none={t("relay.recv.none")}
        target={target}
        example="wss://smjgallery.kr/relay/ws/…/iq/recv?token=…"
        tokenLabel={t("relay.recv.token")}
        locked={busy || running}
        onSave={async (body) => setState(await api.relayRecvTarget(body))}
        onForget={async () => setState(await api.relayRecvForget())}
      />
      {target && (
        <div className="relay-line">
          {running ? (
            <Button variant="secondary" onClick={() => void run(() => api.relayRecvStop())} disabled={busy} data-testid="relay-recv-stop">
              ■ {t("relay.recv.stop")}
            </Button>
          ) : (
            <>
              <Button onClick={() => void run(() => api.relayRecvStart(record))} disabled={busy} data-testid="relay-recv-start">
                ▼ {t("relay.recv.start")}
              </Button>
              <label className="relay-tick">
                <input type="checkbox" checked={record} onChange={(e) => setRecord(e.target.checked)} data-testid="relay-recv-record" />
                {t("relay.recv.record")}
              </label>
            </>
          )}
          {recv && (
            <span role="status" data-testid="relay-recv-status">
              <Badge level={running && recv.sending ? "info" : running ? "warn" : "ok"}>{t(!running ? "relay.recv.stopped" : recv.sending ? "relay.recv.coming" : "relay.recv.waiting")}</Badge>{" "}
              {t("relay.recv.got", { s: recv.seconds.toFixed(1), mb: mb(recv.bytes) })}
              {recv.gaps > 0 ? ` · ${t("relay.recv.gaps", { n: recv.gaps, lost: recv.lost_samples })}` : ""}
            </span>
          )}
        </div>
      )}
      {sig && (
        <p className="muted" data-testid="relay-recv-signal">
          {t("relay.recv.signal", { center: mhz(sig.center_hz), rate: (sig.sample_rate_hz / 1e6).toString(), format: sig.format })}
          {sig.name ? ` · ${sig.name}` : ""}
          {sig.source ? ` · ${t(`relay.recv.source.${sig.source === "file" ? "file" : "device"}`)}` : ""}
        </p>
      )}
      {recv?.note && <p className="muted">{recv.note}</p>}
      {recv?.error && <p role="alert">! {recv.error}</p>}
      {error && <p role="alert">! {error}</p>}
      {p && recv?.view && (
        <>
          <div className="card">
            <LinePlot plot={p.line} />
            <p className="t-caption muted center">{t("view.caption.spectrum")}</p>
          </div>
          <div className="card">
            <Spectrogram grid={recv.view.waterfall} label={t("view.plot.waterfall")} />
            <p className="t-caption muted center">{t("live.caption.waterfall", { s: ((recv.view.waterfall.cols * recv.view.waterfall.col_ms) / 1e3).toFixed(1) })}</p>
          </div>
        </>
      )}
      {recv && recv.files.length > 0 && (
        <ul className="relay-files" data-testid="relay-recv-files">
          {recv.files.map((f) => (
            <li key={f.meta_path}>
              <code title={f.data_path}>{f.data_path}</code>
              <span className="muted">
                {t("relay.recv.file", { s: f.seconds.toFixed(1), mb: mb(f.bytes) })}
                {f.gaps > 0 ? ` · ${t("relay.recv.file.gaps", { n: f.gaps })}` : ""}
                {f.full ? ` · ${t("relay.recv.file.full")}` : ""}
              </span>
              <Button variant="link" onClick={() => onOpen(f.meta_path)} disabled={!f.done} data-testid="relay-recv-open">
                {t(f.done ? "relay.recv.analyze" : "relay.recv.writing")}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
