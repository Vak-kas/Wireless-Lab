import { useEffect, useRef, useState } from "react";
import type { TxRequest, TxStatus } from "../api";
import { SubNav, Tile, TileHead } from "../components/layout";
import { Badge, Button, Chip, Empty, Field } from "../components/ui";
import { isSim, useUsableDevices } from "../devices/DeviceHub";
import { takeTxDevice } from "../devices/intent";
import { t } from "../i18n";
import { useStore } from "../state/store";

type Kind = "tone" | "file";
const n = (s: string) => Number(s);

/**
 * 실험용 송신. 시작할 때마다 경고창에서 책임과 환경을 확인해야 나간다(서버도 확인이 없는 요청을 거부한다).
 * 내보낼 수 있는 것은 시험 톤과 사용자가 준 파형 파일뿐이고, 길이가 정해진 송신만 한다.
 */
export function TxScreen() {
  const { api, fail } = useStore();
  const hub = useUsableDevices();
  const real = (hub.devices ?? []).filter((d) => !isSim(d));
  const [status, setStatus] = useState<TxStatus | null>(null);
  const [wanted] = useState(takeTxDevice);
  const [picked, setPicked] = useState("");
  const device = real.some((d) => d.id === picked) ? picked : (real.find((d) => d.id === wanted)?.id ?? real[0]?.id ?? "");
  const [center, setCenter] = useState("");
  const [rate, setRate] = useState("1");
  const [gain, setGain] = useState("");
  const [seconds, setSeconds] = useState("2");
  const [kind, setKind] = useState<Kind>("tone");
  const [offset, setOffset] = useState("100");
  const [amplitude, setAmplitude] = useState("0.3");
  const [path, setPath] = useState("");
  const [asking, setAsking] = useState<TxRequest | null>(null);
  const [agree, setAgree] = useState(false);
  const [closed, setClosed] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<{ seconds: number; stopped: boolean; underruns: number } | null>(null);
  const sendingRef = useRef(false);

  useEffect(() => {
    void api.txStatus().then(setStatus, () => setStatus({ available: false }));
  }, [api]);

  // 창을 닫거나 떠나면 나가던 송신을 멈춘다
  useEffect(() => {
    const stop = () => {
      if (sendingRef.current) navigator.sendBeacon?.("/api/tx/stop");
    };
    window.addEventListener("beforeunload", stop);
    return () => {
      window.removeEventListener("beforeunload", stop);
      if (sendingRef.current) void api.txStop().catch(() => undefined);
    };
  }, [api]);

  const gainDb = gain.trim() ? n(gain) : (status?.default_gain_db ?? 0);

  const ask = () => {
    const req: TxRequest = {
      device,
      center_hz: n(center) * 1e6,
      sample_rate_hz: n(rate) * 1e6,
      gain_db: gainDb,
      seconds: n(seconds),
      waveform: kind === "tone" ? { kind, offset_hz: n(offset) * 1e3, amplitude: n(amplitude) } : { kind, path: path.trim() },
    };
    if (!device || !(req.center_hz > 0) || !(req.sample_rate_hz > 0) || !(req.seconds > 0) || !Number.isFinite(req.gain_db) || (kind === "file" && !path.trim())) {
      setError(t("tx.error.inputs"));
      return;
    }
    setError("");
    setAgree(false);
    setClosed(false);
    setDone(null);
    setAsking(req);
  };

  const send = async () => {
    if (!asking || !agree || !closed || !status?.warning_version) return;
    const req = asking;
    setAsking(null);
    setSending(true);
    sendingRef.current = true;
    try {
      setDone(
        await api.txStart({
          ...req,
          confirm: {
            accepted: true,
            closed_setup: true,
            version: status.warning_version,
            shown: { device: req.device, center_hz: req.center_hz, gain_db: req.gain_db, seconds: req.seconds },
          },
        }),
      );
    } catch (e) {
      fail(String(e instanceof Error ? e.message : e));
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  };

  const label = (id: string) => real.find((d) => d.id === id)?.label ?? id;

  return (
    <>
      <SubNav title={t("tx.nav")} />
      <Tile tone="light">
        <TileHead eyebrow={t("tx.eyebrow")} title={t("tx.title")} lead={t("tx.lead")} />
        <p className="center-row row">
          <Badge level="warn">{t("tx.strip")}</Badge>
        </p>
        {status && !status.available && <Empty>{t("tx.unavailable")}</Empty>}
        {status?.available && real.length === 0 && <Empty>{t("sim.no_real")}</Empty>}
        {status?.available && real.length > 0 && (
          <div className="card view-controls" data-testid="tx-form">
            <div className="chips" role="group" aria-label={t("start.device.pick")}>
              {real.map((d) => (
                <Chip key={d.id} selected={d.id === device} onSelect={() => setPicked(d.id)} disabled={sending}>
                  {d.label}
                </Chip>
              ))}
            </div>
            <div className="row">
              <Field label={t("view.center")} error={error || undefined}>
                {(f) => <input {...f} inputMode="decimal" value={center} onChange={(e) => setCenter(e.target.value)} disabled={sending} data-testid="tx-center" />}
              </Field>
              <Field label={t("tx.rate")}>{(f) => <input {...f} inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} disabled={sending} data-testid="tx-rate" />}</Field>
            </div>
            <div className="row">
              <Field label={t("tx.gain", { max: status.max_gain_db ?? 0 })}>
                {(f) => (
                  <input {...f} inputMode="decimal" value={gain} placeholder={String(status.default_gain_db ?? 0)} onChange={(e) => setGain(e.target.value)} disabled={sending} data-testid="tx-gain" />
                )}
              </Field>
              <Field label={t("tx.seconds", { max: status.max_seconds ?? 30 })}>
                {(f) => <input {...f} inputMode="decimal" value={seconds} onChange={(e) => setSeconds(e.target.value)} disabled={sending} data-testid="tx-seconds" />}
              </Field>
            </div>
            <div className="chips" role="group" aria-label={t("tx.waveform")}>
              {(["tone", "file"] as const).map((k) => (
                <Chip key={k} selected={k === kind} onSelect={() => setKind(k)} disabled={sending}>
                  {t(`tx.waveform.${k}`)}
                </Chip>
              ))}
            </div>
            {kind === "tone" ? (
              <div className="row">
                <Field label={t("tx.tone.offset")}>{(f) => <input {...f} inputMode="decimal" value={offset} onChange={(e) => setOffset(e.target.value)} disabled={sending} />}</Field>
                <Field label={t("tx.tone.amplitude")}>{(f) => <input {...f} inputMode="decimal" value={amplitude} onChange={(e) => setAmplitude(e.target.value)} disabled={sending} />}</Field>
              </div>
            ) : (
              <Field label={t("tx.file.path")}>
                {(f) => <input {...f} className="input t-body" placeholder="/path/to/waveform.sigmf-meta" value={path} onChange={(e) => setPath(e.target.value)} disabled={sending} data-testid="tx-path" />}
              </Field>
            )}
            <p className="t-caption muted">{t("tx.note")}</p>
            <div className="row">
              {sending ? (
                <>
                  <span className="spinner" aria-hidden="true" />
                  <span className="t-body" role="status" data-testid="tx-sending">
                    {t("tx.sending")}
                  </span>
                  <Button variant="secondary" onClick={() => void api.txStop()} data-testid="tx-stop">
                    {t("spectrum.repeat.stop")}
                  </Button>
                </>
              ) : (
                <Button onClick={ask} data-testid="tx-ask">
                  {t("tx.ask")}
                </Button>
              )}
            </div>
            {done && (
              <p className="t-caption" role="status" data-testid="tx-done">
                {t(done.stopped ? "tx.done.stopped" : "tx.done", { s: done.seconds })}
                {done.underruns > 0 ? ` ${t("tx.done.underruns", { n: done.underruns })}` : ""}
              </p>
            )}
          </div>
        )}
      </Tile>

      {asking && (
        <div className="overlay" data-testid="tx-warning">
          <div className="dialog" role="alertdialog" aria-modal="true" aria-labelledby="tx-warning-title">
            <h2 id="tx-warning-title" className="t-display-md">
              {t("tx.warn.title")}
            </h2>
            <p className="t-body">{t("tx.warn.responsibility")}</p>
            <dl className="facts t-caption warn-facts">
              {(
                [
                  ["device", label(asking.device)],
                  ["center", `${asking.center_hz / 1e6} MHz`],
                  ["gain", `${asking.gain_db} dB`],
                  ["seconds", `${asking.seconds} s`],
                  ["waveform", asking.waveform.kind === "tone" ? t("tx.waveform.tone") : (asking.waveform.path ?? "")],
                ] as const
              ).map(([k, v]) => (
                <div key={k}>
                  <dt className="muted">{t(`tx.warn.${k}`)}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
            <label className="check t-caption">
              <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} data-testid="tx-agree" />
              {t("tx.warn.agree")}
            </label>
            <label className="check t-caption">
              <input type="checkbox" checked={closed} onChange={(e) => setClosed(e.target.checked)} data-testid="tx-closed" />
              {t("tx.warn.closed")}
            </label>
            <div className="dialog-actions">
              <Button variant="secondary" onClick={() => setAsking(null)} data-testid="tx-cancel" autoFocus>
                {t("tx.warn.cancel")}
              </Button>
              <Button onClick={() => void send()} disabled={!agree || !closed} data-testid="tx-confirm">
                {t("tx.warn.send")}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
