import { useEffect, useRef, useState } from "react";
import type { SurveyPlan, TxReceived, TxRequest, TxResult, TxStatus } from "../api";
import { SubNav, Tile, TileHead } from "../components/layout";
import { Badge, Button, Chip, Empty, Field } from "../components/ui";
import { isSim, useUsableDevices } from "../devices/DeviceHub";
import { takeTxDevice } from "../devices/intent";
import { t } from "../i18n";
import { useStore } from "../state/store";

type Kind = "tone" | "standard" | "file";
/** 주파수를 눌러 고를 수 있는 대역 (주파수 상태 화면의 채널 맵과 같은 자료) */
const BANDS = ["wifi-2g4", "wifi-5g", "wifi-6g", "ble"];
const RATES = [1, 2, 5, 10, 20];
const STANDARD_HINT: Record<string, string> = { "wifi-nonht": "wifi", "wifi-he": "wifi", "wifi-eht": "wifi", "ble-adv": "ble" };
const show = (v: number) => Number(v.toFixed(3)).toString();
const n = (s: string) => Number(s);

/** 받은 신호의 스펙트럼: 가로는 가운데 주파수 기준 위치, 세로는 세기. 시험 톤이면 보낸 자리에 세로선을 긋는다. */
function RxSpectrum({ rx }: { rx: TxReceived }) {
  const { offset_hz: f, db } = rx.spectrum;
  if (db.length < 2) return null;
  const W = 640;
  const H = 180;
  const left = 44;
  const bottom = 22;
  const lo = Math.floor(Math.min(...db) / 10) * 10;
  const hi = Math.max(lo + 10, Math.ceil(Math.max(...db) / 10) * 10);
  const fMin = f[0] ?? 0;
  const fMax = f[f.length - 1] ?? 1;
  const x = (hz: number) => left + ((hz - fMin) / (fMax - fMin)) * (W - left - 8);
  const y = (v: number) => 8 + ((hi - v) / (hi - lo)) * (H - bottom - 8);
  const mark = rx.check.kind === "tone" ? rx.check.expected_offset_hz : undefined;
  return (
    <figure className="nearby-chart" data-testid="tx-rx-spectrum">
      <figcaption className="t-caption-strong">{t("tx.rx.spectrum")}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t("tx.rx.spectrum.alt")}>
        {[lo, (lo + hi) / 2, hi].map((v) => (
          <g key={v}>
            <line className="grid" x1={left} x2={W - 8} y1={y(v)} y2={y(v)} />
            <text className="axis" x={left - 6} y={y(v) + 4} textAnchor="end">
              {v}
            </text>
          </g>
        ))}
        {[fMin, 0, fMax].map((hz) => (
          <text key={hz} className="axis" x={x(hz)} y={H - 6} textAnchor={hz === fMin ? "start" : hz === fMax ? "end" : "middle"}>
            {show(hz / 1e6)} MHz
          </text>
        ))}
        {mark !== undefined && <line className="mark" x1={x(mark)} x2={x(mark)} y1={8} y2={H - bottom} />}
        <polyline className="trace" points={db.map((v, i) => `${x(f[i] ?? 0).toFixed(1)},${y(v).toFixed(1)}`).join(" ")} />
      </svg>
    </figure>
  );
}

/** 보내면서 받은 결과: 받았는지 한 줄, 근거가 된 숫자, 스펙트럼. */
function RxResult({ rx }: { rx: TxReceived }) {
  const c = rx.check;
  const found = c.found || rx.decoded?.found === true;
  return (
    <div className="stack" data-testid="tx-rx">
      <p className="row">
        <Badge level={found ? "ok" : "warn"}>{t(found ? "tx.rx.found" : "tx.rx.missing")}</Badge>
      </p>
      <dl className="facts t-caption">
        <div>
          <dt className="muted">{t("tx.rx.level")}</dt>
          <dd>{rx.power_dbfs === null ? "—" : `${rx.power_dbfs} dBFS`}</dd>
        </div>
        {c.kind === "tone" && c.found_offset_hz !== undefined && (
          <div>
            <dt className="muted">{t("tx.rx.tone")}</dt>
            <dd data-testid="tx-rx-tone">
              {t("tx.rx.tone.value", { found: show(c.found_offset_hz / 1e3), expected: show((c.expected_offset_hz ?? 0) / 1e3), db: c.above_floor_db ?? 0 })}
            </dd>
          </div>
        )}
        {c.kind === "waveform" && c.match !== undefined && (
          <div>
            <dt className="muted">{t("tx.rx.match")}</dt>
            <dd data-testid="tx-rx-match">{t("tx.rx.match.value", { v: c.match.toFixed(2) })}</dd>
          </div>
        )}
        {rx.decoded && (
          <div>
            <dt className="muted">{t("tx.rx.decoded")}</dt>
            <dd data-testid="tx-rx-decoded">{t(rx.decoded.found ? "tx.rx.decoded.ok" : "tx.rx.decoded.no", { n: rx.decoded.packets, bad: rx.decoded.crc_failed })}</dd>
          </div>
        )}
        <div>
          <dt className="muted">{t("tx.rx.file")}</dt>
          <dd>{rx.meta_path}</dd>
        </div>
      </dl>
      {rx.clipped && <p className="t-caption notice">! {t("tx.rx.clipped")}</p>}
      {rx.overflows > 0 && <p className="t-caption muted">{t("tx.rx.overflows", { n: rx.overflows })}</p>}
      {c.reason && <p className="t-caption muted">{t(`tx.rx.reason.${c.reason}`)}</p>}
      {!found && !c.reason && <p className="t-caption muted">{t("tx.rx.missing.hint")}</p>}
      <RxSpectrum rx={rx} />
      <p className="t-caption muted">{t(c.kind === "tone" ? "tx.rx.how.tone" : "tx.rx.how.waveform")}</p>
    </div>
  );
}

/**
 * 실험용 송신. 시작할 때마다 경고창에서 책임과 환경을 확인해야 나간다(서버도 확인이 없는 요청을 거부한다).
 * 내보낼 수 있는 것은 시험 톤과 사용자가 준 파형 파일뿐이고, 길이가 정해진 송신만 한다.
 */
/** onDraft: 지금 칸에 적힌 대로의 송신 요청(값이 모자라면 null)을 바깥에 알린다. 작업판이 여러 칸을 함께 시작시킬 때 쓴다. */
export function TxScreen({ device: fixed, embedded, onDraft }: { device?: string; embedded?: boolean; onDraft?: (req: TxRequest | null) => void } = {}) {
  const { api, fail } = useStore();
  const hub = useUsableDevices();
  const real = (hub.devices ?? []).filter((d) => !isSim(d));
  const [status, setStatus] = useState<TxStatus | null>(null);
  const [wanted] = useState(takeTxDevice);
  const [picked, setPicked] = useState("");
  const device = fixed !== undefined ? (real.some((d) => d.id === fixed) ? fixed : "") : real.some((d) => d.id === picked) ? picked : (real.find((d) => d.id === wanted)?.id ?? real[0]?.id ?? "");
  const [center, setCenter] = useState("");
  const [rate, setRate] = useState("1");
  const [gain, setGain] = useState("");
  const [seconds, setSeconds] = useState("2");
  const [kind, setKind] = useState<Kind>("tone");
  const [offset, setOffset] = useState("100");
  const [amplitude, setAmplitude] = useState("0.3");
  const [path, setPath] = useState("");
  const [standard, setStandard] = useState("wifi-he");
  const [plans, setPlans] = useState<SurveyPlan[]>([]);
  const [band, setBand] = useState("");
  const [asking, setAsking] = useState<TxRequest | null>(null);
  const [agree, setAgree] = useState(false);
  const [closed, setClosed] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<TxResult | null>(null);
  const [rxOn, setRxOn] = useState(false);
  const [rxPicked, setRxPicked] = useState("");
  const [rxGain, setRxGain] = useState("");
  const [rxSeconds, setRxSeconds] = useState("0.2");
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

  // 대역·채널을 눌러 고르기 위한 채널 맵
  useEffect(() => {
    if (!device) return;
    void api.surveyDevice(device).then(
      (i) => setPlans(i.plans.filter((p) => BANDS.includes(p.id) && (p.map?.length ?? 0) > 0)),
      () => setPlans([]),
    );
  }, [api, device]);

  const standards = status?.standards ?? [];
  const usable = standards.filter((x) => x.source !== "planned" && !x.error);
  const chosen = standards.find((x) => x.id === standard);
  /** 내장 신호는 번역 문구로, 사용자가 넣은 생성기는 그 생성기가 알려 준 이름으로 */
  const nameOf = (id: string) => {
    const x = standards.find((y) => y.id === id);
    return x?.source === "plugin" ? (x.label ?? id) : x?.source === "planned" ? t(`tx.planned.${id}`) : t(`tx.standard.${id}`);
  };
  const standardRate = standards.find((x) => x.id === standard)?.sample_rate_hz;
  // 표준 시험 신호는 샘플레이트가 정해져 있다
  const rateMhz = kind === "standard" && standardRate ? show(standardRate / 1e6) : rate;
  const cells = plans.find((p) => p.id === band)?.map ?? [];

  const pickCell = (c: { center_hz: number; width_hz: number }) => {
    setCenter(show(c.center_hz / 1e6));
    setRate(show(c.width_hz / 1e6));
  };

  const gainDb = gain.trim() ? n(gain) : (status?.default_gain_db ?? 0);
  // 받는 장비: 따로 고르지 않았으면 보내는 장비가 아닌 것을 먼저, 한 대뿐이면 같은 장비
  const rxDevice = real.some((d) => d.id === rxPicked) ? rxPicked : (real.find((d) => d.id !== device)?.id ?? device);
  const rxGainDb = rxGain.trim() ? n(rxGain) : (status?.receive?.default_gain_db ?? 20);

  /** 지금 칸에 적힌 대로의 요청(보내면서 받기는 빼고). 값이 모자라면 null */
  const base: TxRequest = {
    device,
    center_hz: n(center) * 1e6,
    sample_rate_hz: n(rateMhz) * 1e6,
    gain_db: gainDb,
    seconds: n(seconds),
    waveform: kind === "tone" ? { kind, offset_hz: n(offset) * 1e3, amplitude: n(amplitude) } : kind === "standard" ? { kind, standard } : { kind, path: path.trim() },
  };
  const complete = Boolean(device) && base.center_hz > 0 && base.sample_rate_hz > 0 && base.seconds > 0 && Number.isFinite(base.gain_db) && !(kind === "file" && !path.trim());
  const draft = complete && status?.available ? JSON.stringify(base) : "";
  useEffect(() => {
    onDraft?.(draft ? (JSON.parse(draft) as TxRequest) : null);
  }, [draft, onDraft]);
  useEffect(() => () => onDraft?.(null), [onDraft]);

  const ask = () => {
    const req: TxRequest = { ...base, ...(rxOn ? { receive: { device: rxDevice, gain_db: rxGainDb, seconds: n(rxSeconds) } } : {}) };
    if (rxOn && (!(n(rxSeconds) > 0) || !Number.isFinite(rxGainDb))) {
      setError(t("tx.error.inputs"));
      return;
    }
    if (!complete) {
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
      {!embedded && <SubNav title={t("tx.nav")} />}
      <Tile tone="light">
        {!embedded && <TileHead eyebrow={t("tx.eyebrow")} title={t("tx.title")} lead={t("tx.lead")} />}
        <p className="center-row row">
          <Badge level="warn">{t("tx.strip")}</Badge>
        </p>
        {status && !status.available && <Empty>{t("tx.unavailable")}</Empty>}
        {status?.available && real.length === 0 && <Empty>{t("sim.no_real")}</Empty>}
        {status?.available && real.length > 0 && (
          <div className="card view-controls" data-testid="tx-form">
            {!embedded && (
              <div className="chips" role="group" aria-label={t("start.device.pick")}>
                {real.map((d) => (
                  <Chip key={d.id} selected={d.id === device} onSelect={() => setPicked(d.id)} disabled={sending}>
                    {d.label}
                  </Chip>
                ))}
              </div>
            )}
            <div>
              <div className="t-caption-strong">{t("tx.pick.title")}</div>
              <div className="chips" role="group" aria-label={t("tx.pick.title")}>
                <Chip selected={band === ""} onSelect={() => setBand("")} disabled={sending}>
                  {t("tx.pick.manual")}
                </Chip>
                {plans.map((p) => (
                  <Chip key={p.id} selected={p.id === band} onSelect={() => setBand(p.id)} disabled={sending}>
                    {t(`spectrum.plan.${p.id}`)}
                  </Chip>
                ))}
              </div>
              {cells.length > 0 && (
                <div className="chmap" role="group" aria-label={t("monitor.map")} data-testid="tx-map">
                  {cells.map((c) => (
                    <button
                      key={c.name}
                      type="button"
                      className="chmap-cell t-caption"
                      aria-pressed={show(c.center_hz / 1e6) === center}
                      disabled={sending || !c.reachable}
                      title={`${show(c.center_hz / 1e6)} MHz`}
                      onClick={() => pickCell(c)}
                      data-testid={`tx-cell-${c.name}`}
                    >
                      {c.name}
                    </button>
                  ))}
                </div>
              )}
              {band !== "" && <p className="t-caption muted">{t("tx.pick.hint")}</p>}
            </div>
            <div className="row">
              <Field label={t("view.center")} error={error || undefined}>
                {(f) => <input {...f} inputMode="decimal" value={center} onChange={(e) => setCenter(e.target.value)} disabled={sending} data-testid="tx-center" />}
              </Field>
              <Field label={t("tx.rate")}>
                {(f) => <input {...f} inputMode="decimal" value={rateMhz} onChange={(e) => setRate(e.target.value)} disabled={sending || kind === "standard"} data-testid="tx-rate" />}
              </Field>
            </div>
            {kind !== "standard" && (
              <div className="chips" role="group" aria-label={t("tx.rate")}>
                {RATES.map((r) => (
                  <Chip key={r} selected={String(r) === rate} onSelect={() => setRate(String(r))} disabled={sending}>
                    {r} MHz
                  </Chip>
                ))}
              </div>
            )}
            <p className="t-caption muted">{t("tx.rate.hint")}</p>
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
              {(["tone", ...(usable.length > 0 ? (["standard"] as const) : []), "file"] as const).map((k) => (
                <Chip key={k} selected={k === kind} onSelect={() => setKind(k)} disabled={sending}>
                  {t(`tx.waveform.${k}`)}
                </Chip>
              ))}
            </div>
            <p className="t-caption muted" data-testid="tx-kind-desc">
              {t(`tx.waveform.${kind}.desc`)}
            </p>
            {kind === "standard" ? (
              <>
                <div className="chips" role="group" aria-label={t("tx.waveform.standard")}>
                  {standards.map((x) => (
                    <Chip
                      key={x.id}
                      selected={x.id === standard}
                      onSelect={() => setStandard(x.id)}
                      disabled={sending || x.source === "planned" || Boolean(x.error)}
                    >
                      {nameOf(x.id)}
                      {x.source === "planned" ? ` · ${t("tx.planned.badge")}` : x.source === "plugin" ? ` · ${t("tx.plugin.badge")}` : ""}
                    </Chip>
                  ))}
                </div>
                <p className="t-caption muted">
                  {chosen?.source === "plugin" ? chosen.description || t("tx.plugin.hint") : t(`tx.standard.hint.${STANDARD_HINT[standard] ?? "wifi"}`)}
                </p>
                {chosen?.frames && (
                  <p className="t-caption muted" data-testid="tx-frames-hint">
                    {t("tx.plugin.frames.hint")}
                  </p>
                )}
                {standards.some((x) => x.source === "planned") && (
                  <p className="t-caption muted" data-testid="tx-planned-note">
                    {t("tx.planned.note")}
                  </p>
                )}
                {standards
                  .filter((x) => x.error)
                  .map((x) => (
                    <p key={x.id} className="t-caption" data-testid="tx-plugin-error">
                      ! {t("tx.plugin.error", { file: x.label ?? x.id, message: x.error ?? "" })}
                    </p>
                  ))}
              </>
            ) : kind === "tone" ? (
              <div className="row">
                <Field label={t("tx.tone.offset")}>{(f) => <input {...f} inputMode="decimal" value={offset} onChange={(e) => setOffset(e.target.value)} disabled={sending} />}</Field>
                <Field label={t("tx.tone.amplitude")}>{(f) => <input {...f} inputMode="decimal" value={amplitude} onChange={(e) => setAmplitude(e.target.value)} disabled={sending} />}</Field>
              </div>
            ) : (
              <Field label={t("tx.file.path")}>
                {(f) => <input {...f} className="input t-body" placeholder="/path/to/waveform.sigmf-meta" value={path} onChange={(e) => setPath(e.target.value)} disabled={sending} data-testid="tx-path" />}
              </Field>
            )}
            <div className="rx-option" data-testid="tx-rx-option">
              <label className="check t-body">
                <input type="checkbox" checked={rxOn} onChange={(e) => setRxOn(e.target.checked)} disabled={sending} data-testid="tx-rx-on" />
                {t("tx.rx.on")}
              </label>
              <p className="t-caption muted">{t("tx.rx.desc")}</p>
              {rxOn && (
                <>
                  <div className="chips" role="group" aria-label={t("tx.rx.device")}>
                    {real.map((d) => (
                      <Chip key={d.id} selected={d.id === rxDevice} onSelect={() => setRxPicked(d.id)} disabled={sending}>
                        {d.label}
                        {d.id === device ? ` · ${t("tx.rx.same")}` : ""}
                      </Chip>
                    ))}
                  </div>
                  <p className="t-caption muted" data-testid="tx-rx-wiring">
                    {t(rxDevice === device ? "tx.rx.wiring.same" : "tx.rx.wiring.two")}
                  </p>
                  <div className="row">
                    <Field label={t("tx.rx.gain")}>
                      {(f) => (
                        <input {...f} inputMode="decimal" value={rxGain} placeholder={String(status.receive?.default_gain_db ?? 20)} onChange={(e) => setRxGain(e.target.value)} disabled={sending} data-testid="tx-rx-gain" />
                      )}
                    </Field>
                    <Field label={t("tx.rx.seconds", { max: status.receive?.max_seconds ?? 1 })}>
                      {(f) => <input {...f} inputMode="decimal" value={rxSeconds} onChange={(e) => setRxSeconds(e.target.value)} disabled={sending} data-testid="tx-rx-seconds" />}
                    </Field>
                  </div>
                </>
              )}
            </div>
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
            {done?.received && <RxResult rx={done.received} />}
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
                  ["waveform", asking.waveform.kind === "tone" ? t("tx.waveform.tone") : asking.waveform.kind === "standard" ? nameOf(asking.waveform.standard) : asking.waveform.path],
                  ...(asking.receive ? ([["receive", `${label(asking.receive.device)} · ${asking.receive.gain_db} dB`]] as const) : []),
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
