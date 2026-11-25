import { useCallback, useEffect, useMemo, useState } from "react";
import type { TxGroupResult, TxRequest } from "../api";
import { SubNav, Tile } from "../components/layout";
import { Button, Chip, Empty } from "../components/ui";
import { isSim, useUsableDevices } from "../devices/DeviceHub";
import { loadBench, saveBench, type Pane } from "../devices/intent";
import { t } from "../i18n";
import { go } from "../router";
import { useStore } from "../state/store";
import { NearbyScreen } from "./NearbyScreen";
import { SpectrumScreen } from "./SpectrumScreen";
import { TxScreen } from "./TxScreen";

/**
 * 작업판: 장비마다 칸 하나. 칸마다 수신 또는 송신을 따로 한다.
 * 장비가 두 대면 한 칸은 A 대역 송신, 다른 칸은 B 대역 수신처럼 동시에 돌릴 수 있다(서버가 장비마다 따로 잠근다).
 * 한 장비는 한 칸에만 놓인다. 칸의 내용은 수신 화면·송신 화면을 그대로 쓴다.
 */
export function BenchScreen() {
  const { api, fail } = useStore();
  const hub = useUsableDevices();
  const devices = hub.devices ?? [];
  const [panes, setPanes] = useState<Pane[]>(loadBench);
  const [txReady, setTxReady] = useState(false);
  const [version, setVersion] = useState("");
  /** 송신 칸마다 지금 적혀 있는 요청(값이 모자란 칸은 없다) */
  const [drafts, setDrafts] = useState<Record<string, TxRequest>>({});
  const [asking, setAsking] = useState<TxRequest[] | null>(null);
  const [agree, setAgree] = useState(false);
  const [closed, setClosed] = useState(false);
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState<TxGroupResult | null>(null);
  /** 칸을 놓는 법: 나란히(side) / 하나씩(tabs). 하나씩일 때는 고른 칸만 보이고 나머지는 뒤에서 계속 돈다 */
  const [layout, setLayout] = useState<"side" | "tabs">("side");
  const [active, setActive] = useState("");
  /** 지금 받고 있는 칸들 */
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  /** "모두 멈추기"를 누를 때마다 하나씩 올라간다. 칸들이 이 값이 바뀐 것을 보고 멈춘다 */
  const [stopSignal, setStopSignal] = useState(0);

  useEffect(() => {
    void api.txStatus().then(
      (s) => {
        setTxReady(s.available);
        setVersion(s.warning_version ?? "");
      },
      () => setTxReady(false),
    );
  }, [api]);

  /** 칸마다 한 번만 만들어지는 "내 요청 알리기" 함수(매번 새로 만들면 칸이 끝없이 다시 알린다) */
  const reporters = useMemo(() => new Map<string, (req: TxRequest | null) => void>(), []);
  const reporter = useCallback(
    (device: string) => {
      if (!reporters.has(device)) {
        reporters.set(device, (req) =>
          setDrafts((old) => {
            const next = { ...old };
            if (req) next[device] = req;
            else delete next[device];
            return next;
          }),
        );
      }
      return reporters.get(device)!;
    },
    [reporters],
  );

  const busyOf = useMemo(() => new Map<string, (b: boolean) => void>(), []);
  const busyReporter = (device: string) => {
    if (!busyOf.has(device)) busyOf.set(device, (b) => setBusy((old) => (old[device] === b ? old : { ...old, [device]: b })));
    return busyOf.get(device)!;
  };
  const shown = panes.some((p) => p.device === active) ? active : (panes[0]?.device ?? "");
  const anyBusy = panes.some((p) => busy[p.device]) || sending;
  const stopAll = () => {
    setStopSignal((n) => n + 1);
    void api.txStop().catch(() => undefined);
  };

  const together = panes.filter((p) => p.mode === "tx" && drafts[p.device]).map((p) => drafts[p.device]!);
  const txPanes = panes.filter((p) => p.mode === "tx").length;

  const askTogether = () => {
    setAgree(false);
    setClosed(false);
    setDone(null);
    setAsking(together);
  };

  const sendTogether = async () => {
    if (!asking || !agree || !closed || !version) return;
    const items = asking.map((req) => ({
      ...req,
      confirm: { accepted: true, closed_setup: true, version, shown: { device: req.device, center_hz: req.center_hz, gain_db: req.gain_db, seconds: req.seconds } },
    }));
    setAsking(null);
    setSending(true);
    try {
      setDone(await api.txStartGroup(items));
    } catch (e) {
      fail(String(e instanceof Error ? e.message : e));
    } finally {
      setSending(false);
    }
  };

  const keep = (next: Pane[]) => {
    setPanes(next);
    saveBench(next);
  };
  const adapterOf = (id: string) => hub.adapters.find((a) => a.id === id);
  const label = (id: string) => devices.find((d) => d.id === id)?.label ?? (adapterOf(id) ? `${adapterOf(id)!.label} · ${t(`hub.attach.${adapterOf(id)!.attach}`)}` : id);
  const canSend = (id: string) => txReady && devices.some((d) => d.id === id && !isSim(d));
  const free = devices.filter((d) => !isSim(d) && !panes.some((p) => p.device === d.id));
  const freeAdapters = hub.adapters.filter((a) => !panes.some((p) => p.device === a.id));

  return (
    <>
      <SubNav
        title={t("nav.bench")}
        action={
          panes.length > 0 ? (
            <div className="bench-bar" data-testid="bench-bar">
              {/* 칸 이름표: 받는 중이면 점이 켜진다. 누르면 그 칸으로 간다(하나씩 보기에서는 그 칸을 보여 준다) */}
              {panes.map((p) => (
                <button
                  key={p.device}
                  type="button"
                  className="bench-tab t-caption"
                  aria-pressed={layout === "tabs" && shown === p.device}
                  data-busy={busy[p.device] ? "true" : "false"}
                  onClick={() => {
                    setActive(p.device);
                    if (layout === "side") document.getElementById(`pane-${p.device}`)?.scrollIntoView?.({ block: "start" });
                  }}
                  data-testid={`bench-tab-${p.device}`}
                >
                  <span className="bench-dot" aria-hidden="true" />
                  {label(p.device)}
                  <span className="sr-only">{busy[p.device] ? t("bench.busy") : t("bench.idle")}</span>
                </button>
              ))}
              {panes.length > 1 && (
                <div className="segments" role="group" aria-label={t("bench.layout")}>
                  {(["side", "tabs"] as const).map((x) => (
                    <button key={x} type="button" className="segment t-caption" aria-pressed={layout === x} onClick={() => setLayout(x)} data-testid={`bench-layout-${x}`}>
                      {t(`bench.layout.${x}`)}
                    </button>
                  ))}
                </div>
              )}
              <Button variant="secondary" onClick={stopAll} disabled={!anyBusy} data-testid="bench-stop-all">
                {t("bench.stop_all")}
              </Button>
            </div>
          ) : undefined
        }
      />
      <Tile tone="light">
        {panes.length === 0 && (
          <Empty
            action={
              <Button variant="secondary" onClick={() => go("start")}>
                {t("bench.to_home")}
              </Button>
            }
          >
            {t("bench.empty")}
          </Empty>
        )}
        <div className="bench" data-testid="bench" data-count={panes.length} data-layout={panes.length > 1 ? layout : "side"}>
          {panes.map((p) => (
            <section className="bench-pane" key={p.device} id={`pane-${p.device}`} data-testid={`pane-${p.device}`} aria-label={label(p.device)} data-active={shown === p.device}>
              <header className="bench-head">
                <span className="t-body-strong">{label(p.device)}</span>
                <div className="segments" role="group" aria-label={t("bench.mode")}>
                  {(["rx", "tx"] as const).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      className="segment t-caption"
                      aria-pressed={p.mode === mode}
                      disabled={mode === "tx" && !canSend(p.device)}
                      onClick={() => keep(panes.map((x) => (x.device === p.device ? { ...x, mode } : x)))}
                      data-testid={`pane-mode-${mode}`}
                    >
                      {t(`bench.mode.${mode}`)}
                    </button>
                  ))}
                </div>
                <Button variant="link" onClick={() => keep(panes.filter((x) => x.device !== p.device))} data-testid="pane-close">
                  {t("bench.close")}
                </Button>
              </header>
              {p.kind === "adapter" ? (
                hub.adaptersReady && !adapterOf(p.device) ? (
                  <Empty>{t("bench.gone")}</Empty>
                ) : (
                  <NearbyScreen adapter={p.device} embedded stopSignal={stopSignal} onBusy={busyReporter(p.device)} />
                )
              ) : hub.devices !== null && !devices.some((d) => d.id === p.device) ? (
                <Empty>{t("bench.gone")}</Empty>
              ) : p.mode === "rx" ? (
                <SpectrumScreen key="rx" device={p.device} embedded stopSignal={stopSignal} onBusy={busyReporter(p.device)} />
              ) : (
                <TxScreen key="tx" device={p.device} embedded onDraft={reporter(p.device)} />
              )}
            </section>
          ))}
        </div>
        {free.length + freeAdapters.length > 0 && (
          <div className="bench-add" data-testid="bench-add">
            <span className="t-caption muted">{t("bench.add")}</span>
            <div className="chips">
              {free.map((d) => (
                <Chip key={d.id} selected={false} onSelect={() => keep([...panes, { device: d.id, mode: "rx" }])}>
                  + {d.label}
                </Chip>
              ))}
              {freeAdapters.map((a) => (
                <Chip key={a.id} selected={false} onSelect={() => keep([...panes, { device: a.id, mode: "rx", kind: "adapter" }])}>
                  + {a.label} · {t(`hub.attach.${a.attach}`)}
                </Chip>
              ))}
            </div>
          </div>
        )}
        {txPanes > 1 && (
          <div className="card bench-together" data-testid="bench-together">
            <h3 className="t-tagline">{t("bench.together.title")}</h3>
            <p className="t-caption muted">{t("bench.together.lead")}</p>
            <div className="row">
              <Button onClick={askTogether} disabled={sending || together.length < 2} data-testid="together-start">
                {sending ? t("bench.together.sending") : t("bench.together.start", { n: together.length })}
              </Button>
              {sending && (
                <Button variant="secondary" onClick={() => void api.txStop().catch(() => undefined)} data-testid="together-stop">
                  {t("bench.together.stop")}
                </Button>
              )}
            </div>
            {together.length < txPanes && <p className="t-caption muted">{t("bench.together.incomplete", { n: txPanes - together.length })}</p>}
            {done && (
              <div role="status" data-testid="together-done">
                <p className="t-caption">{t(done.aligned === "pps" ? "bench.together.aligned.pps" : "bench.together.aligned.host")}</p>
                <ul className="t-caption">
                  {done.streams.map((s) => (
                    <li key={s.id}>
                      {label(s.device)}: {t("bench.together.row", { s: s.seconds, u: s.underruns })}
                      {s.stopped ? ` · ${t("bench.together.stopped")}` : ""}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
        {panes.length > 1 && <p className="t-caption muted center">{t("bench.hint")}</p>}
      </Tile>
      {asking && (
        <div className="overlay" data-testid="together-warning">
          <div className="dialog" role="alertdialog" aria-modal="true" aria-labelledby="together-title">
            <h2 id="together-title" className="t-display-md">
              {t("tx.warn.title")}
            </h2>
            <p className="t-body">{t("tx.warn.responsibility")}</p>
            <p className="t-caption">{t("bench.together.warn", { n: asking.length })}</p>
            {asking.map((req) => (
              <dl className="facts t-caption warn-facts" key={req.device}>
                {(
                  [
                    ["device", label(req.device)],
                    ["center", `${req.center_hz / 1e6} MHz`],
                    ["gain", `${req.gain_db} dB`],
                    ["seconds", `${req.seconds} s`],
                  ] as const
                ).map(([k, v]) => (
                  <div key={k}>
                    <dt className="muted">{t(`tx.warn.${k}`)}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
            ))}
            <label className="check t-caption">
              <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} data-testid="together-agree" />
              {t("tx.warn.agree")}
            </label>
            <label className="check t-caption">
              <input type="checkbox" checked={closed} onChange={(e) => setClosed(e.target.checked)} data-testid="together-closed" />
              {t("tx.warn.closed")}
            </label>
            <div className="dialog-actions">
              <Button variant="secondary" onClick={() => setAsking(null)} data-testid="together-cancel" autoFocus>
                {t("tx.warn.cancel")}
              </Button>
              <Button onClick={() => void sendTogether()} disabled={!agree || !closed} data-testid="together-confirm">
                {t("tx.warn.send")}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
