import { useEffect, useState } from "react";
import type { Session } from "../api";
import { SubNav, Tile, TileHead } from "../components/layout";
import { Button } from "../components/ui";
import { t } from "../i18n";
import { go } from "../router";
import { useStore } from "../state/store";
import { DeviceCard, SearchNote, useUsableDevices } from "../devices/DeviceHub";
import { saveBench, type Pane } from "../devices/intent";
import { PhoneTile } from "./PhoneTile";

/** 1. 시작: 쓸 장비를 고르고 수신·송신(작업판)이나 시나리오로 들어간다. 준비 상태는 Settings, 지난 세션은 Sessions 에 있다. */
const TASK_ICONS: Record<string, React.ReactNode> = {
  // 파형을 들여다보는 돋보기
  analyze: (
    <>
      <path d="M3 13h2l1.5-5 2 9 2-7 1 3h1.5" />
      <circle cx="16.5" cy="14.5" r="3.5" />
      <path d="M19 17l2.5 2.5" />
    </>
  ),
  // 기지국 탑과 퍼지는 신호
  nr: (
    <>
      <path d="M12 21V10M8 21l4-11 4 11M9.5 17h5" />
      <path d="M8.5 7.5a5 5 0 0 1 7 0M6 5a8.5 8.5 0 0 1 12 0" />
    </>
  ),
  // 받는 신호: 아래로 향한 화살표와 주파수별 세기 곡선
  rx: (
    <>
      <path d="M12 3v8M8.5 7.5L12 11l3.5-3.5" />
      <path d="M3 20h18M4 17l3-1 2-3 2 3 2-2 2 2 2-3 3 4" />
    </>
  ),
  // 주변 Wi-Fi 망: 부채꼴과 목록
  "near-wifi": (
    <>
      <path d="M3 9a9 9 0 0 1 12 0M5.5 12a5.5 5.5 0 0 1 7 0" />
      <circle cx="9" cy="15" r="0.8" />
      <path d="M15 14h6M15 17h6M15 20h4" />
    </>
  ),
  // 주변 블루투스 기기: 가운데 점과 둘레의 점들
  "near-bt": (
    <>
      <circle cx="12" cy="12" r="2.2" />
      <circle cx="5" cy="7" r="1.2" />
      <circle cx="19" cy="8" r="1.2" />
      <circle cx="18" cy="18" r="1.2" />
      <circle cx="6" cy="18" r="1.2" />
      <path d="M12 12m-7 0a7 7 0 1 0 14 0a7 7 0 1 0-14 0" strokeDasharray="2 3" />
    </>
  ),
  // 모니터 모드: 지나가는 프레임들을 들여다보는 돋보기
  monitor: (
    <>
      <path d="M3 7h8M3 11h5M3 15h6" />
      <circle cx="15" cy="13" r="4.5" />
      <path d="M18.5 16.5L21 19" />
    </>
  ),
  // 내보내는 신호: 위로 향한 화살표와 파동
  tx: (
    <>
      <path d="M12 20V8M8 12l4-4 4 4" />
      <path d="M6 6a8.5 8.5 0 0 1 12 0" />
    </>
  ),
};

/** "이 장비로 할 일" 한 칸. soon 이면 아직 없는 기능이라 누를 수 없다. */
function Task({ id, onClick, disabled, soon, note }: { id: string; onClick?: () => void; disabled?: boolean; soon?: boolean; note?: string }) {
  return (
    <button type="button" className="task" onClick={onClick} disabled={disabled || soon} data-testid={`task-${id}`} data-soon={soon ? "true" : undefined}>
      <svg viewBox="0 0 24 24" aria-hidden="true">
        {TASK_ICONS[id]}
      </svg>
      <span className="t-body-strong">{t(`home.task.${id}`)}</span>
      <span className="t-caption muted">{t(`home.task.${id}.desc`)}</span>
      {soon && <span className="t-caption task-soon">{t("home.soon")}</span>}
      {note && <span className="t-caption muted">{note}</span>}
    </button>
  );
}

export function StartScreen() {
  const { api, start } = useStore();
  const hub = useUsableDevices();
  const devices = hub.devices ?? [];
  const [busy, setBusy] = useState(false);
  const [txReady, setTxReady] = useState(false);

  useEffect(() => {
    void api.txStatus().then((s) => setTxReady(s.available), () => setTxReady(false));
  }, [api]);

  const real = devices.filter((d) => d.driver !== "simulated");
  const locked = hub.locked;

  const { isPicked } = hub;
  const chosen = real.filter((d) => isPicked(d.id, false));
  const chosenAdapters = hub.adapters.filter((a) => isPicked(a.id, true));
  const total = chosen.length + chosenAdapters.length;

  /** 고른 장비마다 칸 하나씩 놓고 작업판을 연다. SDR 칸의 수신·송신은 작업판에서 바꿀 수 있다. 어댑터는 받기(주변 보기)만 한다. */
  const openBench = (mode: "rx" | "tx") => {
    const panes: Pane[] = chosen.map((d) => ({ device: d.id, mode }));
    if (mode === "rx") panes.push(...chosenAdapters.map((a) => ({ device: a.id, mode: "rx" as const, kind: "adapter" as const })));
    saveBench(panes);
    go("bench");
  };

  const begin = async (fn: () => Promise<Session>) => {
    setBusy(true);
    try {
      const s = await fn();
      go("scan", s.id);
    } finally {
      setBusy(false);
    }
  };


  return (
    <>
      <SubNav title={t("nav.start")} />
      <Tile tone="light">
        <TileHead title={t("home.title")} lead={t("home.lead")} />
        {locked.map((d) => (
          <div className="card home-device" key={d.id} data-testid={`home-locked-${d.id}`}>
            <DeviceCard device={d} />
            <h3 className="t-tagline">{t("home.tasks.pro")}</h3>
            <div className="tasks">
              {["rx", "tx", "nr"].map((id) => (
                <Task key={id} id={id} disabled />
              ))}
            </div>
          </div>
        ))}
        {real.length === 0 && locked.length > 0 ? null : real.length === 0 ? (
          <div className="card home-empty" data-testid="home-no-device">
            {hub.mode === "none" ? <p className="t-body">{t("hub.none_mode")}</p> : <SearchNote search={hub.search} onRescan={hub.rescan} onReset={hub.reset} />}
            <div>
              <Button variant="secondary" onClick={hub.connect} data-testid="home-connect">
                {t("hub.mine.reconnect")}
              </Button>
            </div>
            {hub.search !== null && hub.search.backends.length === 0 && (
              <p className="t-caption" data-testid="home-pro-hint">
                {t("home.pro_hint")}
              </p>
            )}
            <p className="t-caption muted">{t("home.empty_hint")}</p>
          </div>
        ) : null}
        {real.length + hub.adapters.length > 0 && (
          <>
            {/* 쓸 장비: 이름만 한 줄로. 자세한 정보와 설정은 "내 장비" 칸에 있다 */}
            <div className="home-picks" data-testid="home-picks">
              <span className="t-caption muted">{t("home.devices")}</span>
              <div className="chips">
                {real.map((d) => (
                  <button key={d.id} type="button" className="chip t-caption" aria-pressed={isPicked(d.id, false)} onClick={() => hub.flip(d.id)} data-testid={`home-pick-${d.id}`}>
                    {isPicked(d.id, false) ? "✓ " : ""}
                    {d.label}
                  </button>
                ))}
                {hub.adapters.map((a) => (
                  <button key={a.id} type="button" className="chip t-caption" aria-pressed={isPicked(a.id, true)} onClick={() => hub.flip(a.id)} data-testid={`home-pick-${a.id}`}>
                    {isPicked(a.id, true) ? "✓ " : ""}
                    {a.label} · {t(`hub.attach.${a.attach}`)}
                  </button>
                ))}
              </div>
              <Button variant="link" onClick={hub.showMine} data-testid="home-mine">
                {t("home.devices.more")}
              </Button>
            </div>
            <div className="tasks" data-testid="home-tasks">
              <Task id="rx" disabled={busy || total === 0} onClick={() => openBench("rx")} />
              <Task id="tx" soon={!txReady} disabled={busy || chosen.length === 0} onClick={() => openBench("tx")} />
            </div>
            <p className="t-caption muted home-note">{total > 1 ? t("home.what.many") : t("home.what.hint")}</p>
            {real.length > 0 && (
              <>
                <h3 className="t-tagline home-group">{t("home.scenarios")}</h3>
                <div className="tasks">
                  <Task
                    id="nr"
                    disabled={busy || chosen.length === 0}
                    onClick={() => void begin(() => start({ kind: "device", device: chosen[0]!.id, device_label: chosen[0]!.label }))}
                    note={chosen[0] && Object.values(chosen[0].stages ?? {}).some((v) => v !== "ok") ? chosen[0].note : undefined}
                  />
                </div>
              </>
            )}
          </>
        )}
        {/* 저장해 둔 파일로 하는 일: 장비가 없어도 된다 */}
        <h3 className="t-tagline home-group">{t("home.files")}</h3>
        <div className="tasks" data-testid="home-file-tasks">
          <Task id="analyze" onClick={() => go("analyze")} />
        </div>
        {!hub.adaptersReady && (
          <p className="searching t-caption" data-testid="home-adapters-loading">
            <span className="spinner" aria-hidden="true" /> {t("home.adapters.loading")}
          </p>
        )}
      </Tile>

      <Tile tone="parchment" id="without-device">
        <TileHead eyebrow={t("home.without.eyebrow")} title={t("home.simlink.title")} lead={t("home.simlink.lead")} />
        <p className="center-row row">
          <Button onClick={() => go("sim")} data-testid="home-sim">
            {t("home.simlink.button")}
          </Button>
        </p>
      </Tile>

      <PhoneTile devices={devices} />
    </>
  );
}
