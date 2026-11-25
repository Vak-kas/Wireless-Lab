import { useEffect, useState } from "react";
import { SubNav, Tile } from "../components/layout";
import { Button, Chip, Empty } from "../components/ui";
import { isSim, useUsableDevices } from "../devices/DeviceHub";
import { loadBench, saveBench, type Pane } from "../devices/intent";
import { t } from "../i18n";
import { go } from "../router";
import { useStore } from "../state/store";
import { SpectrumScreen } from "./SpectrumScreen";
import { TxScreen } from "./TxScreen";

/**
 * 작업판: 장비마다 칸 하나. 칸마다 수신 또는 송신을 따로 한다.
 * 장비가 두 대면 한 칸은 A 대역 송신, 다른 칸은 B 대역 수신처럼 동시에 돌릴 수 있다(서버가 장비마다 따로 잠근다).
 * 한 장비는 한 칸에만 놓인다. 칸의 내용은 수신 화면·송신 화면을 그대로 쓴다.
 */
export function BenchScreen() {
  const { api } = useStore();
  const hub = useUsableDevices();
  const devices = hub.devices ?? [];
  const [panes, setPanes] = useState<Pane[]>(loadBench);
  const [txReady, setTxReady] = useState(false);

  useEffect(() => {
    void api.txStatus().then((s) => setTxReady(s.available), () => setTxReady(false));
  }, [api]);

  const keep = (next: Pane[]) => {
    setPanes(next);
    saveBench(next);
  };
  const label = (id: string) => devices.find((d) => d.id === id)?.label ?? id;
  const canSend = (id: string) => txReady && devices.some((d) => d.id === id && !isSim(d));
  const free = devices.filter((d) => !isSim(d) && !panes.some((p) => p.device === d.id));

  return (
    <>
      <SubNav title={t("nav.bench")} />
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
        <div className="bench" data-testid="bench" data-count={panes.length}>
          {panes.map((p) => (
            <section className="bench-pane" key={p.device} data-testid={`pane-${p.device}`} aria-label={label(p.device)}>
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
              {hub.devices !== null && !devices.some((d) => d.id === p.device) ? (
                <Empty>{t("bench.gone")}</Empty>
              ) : p.mode === "rx" ? (
                <SpectrumScreen key="rx" device={p.device} embedded />
              ) : (
                <TxScreen key="tx" device={p.device} embedded />
              )}
            </section>
          ))}
        </div>
        {free.length > 0 && (
          <div className="bench-add" data-testid="bench-add">
            <span className="t-caption muted">{t("bench.add")}</span>
            <div className="chips">
              {free.map((d) => (
                <Chip key={d.id} selected={false} onSelect={() => keep([...panes, { device: d.id, mode: "rx" }])}>
                  + {d.label}
                </Chip>
              ))}
            </div>
          </div>
        )}
        {panes.length > 1 && <p className="t-caption muted center">{t("bench.hint")}</p>}
      </Tile>
    </>
  );
}
