import { useEffect, useState } from "react";
import type { DoctorReport, Scenario, Session } from "../api";
import { SubNav, Tile, TileHead } from "../components/layout";
import { Badge, Button, Chip, Empty, Field } from "../components/ui";
import { t } from "../i18n";
import { go, href } from "../router";
import { useStore } from "../state/store";
import { AdapterCard, DeviceCard, SearchNote, useUsableDevices } from "../devices/DeviceHub";
import { saveIntent, saveNearby, saveTxDevice, type SpectrumIntent } from "../devices/intent";
import { OaiCard } from "./OaiCard";
import { PhoneTile } from "./PhoneTile";

const DOCTOR_LEVEL = { ok: "ok", warn: "warn", missing: "error" } as const;

/** 1. 시작: 입력 소스 선택(연습 / 파일 / 장비), 장비 상태, 최근 세션. */
const TASK_ICONS: Record<string, React.ReactNode> = {
  // 기지국 탑과 퍼지는 신호
  nr: (
    <>
      <path d="M12 21V10M8 21l4-11 4 11M9.5 17h5" />
      <path d="M8.5 7.5a5 5 0 0 1 7 0M6 5a8.5 8.5 0 0 1 12 0" />
    </>
  ),
  // 부채꼴로 퍼지는 무선 신호
  wifi: (
    <>
      <path d="M4 10a11.5 11.5 0 0 1 16 0M7 13.5a7.5 7.5 0 0 1 10 0M10 17a3.2 3.2 0 0 1 4 0" />
      <circle cx="12" cy="19.5" r="0.8" />
    </>
  ),
  // 주파수별 세기 곡선
  view: <path d="M3 19h18M4 16l3-1 2-8 2 8 2-3 2 3 2-5 3 6" />,
  // 근거리 무선: 이어진 두 점
  bt: (
    <>
      <circle cx="7" cy="12" r="2.5" />
      <circle cx="17" cy="12" r="2.5" />
      <path d="M9.5 12h5M12 6v2M12 16v2" />
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
      {note && <span className="t-fine-print muted">{note}</span>}
    </button>
  );
}

export function StartScreen() {
  const { api, start, stageDef } = useStore();
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenario, setScenario] = useState<string>("");
  const hub = useUsableDevices();
  const devices = hub.devices ?? [];
  const [simPick, setSim] = useState<string>("");
  const [doctor, setDoctor] = useState<DoctorReport | null>(null);
  const [recent, setRecent] = useState<Session[]>([]);
  const [path, setPath] = useState("");
  const [testbed, setTestbed] = useState(false);
  const [pathError, setPathError] = useState("");
  const [busy, setBusy] = useState(false);
  const [txReady, setTxReady] = useState(false);

  useEffect(() => {
    void api.scenarios().then((list) => {
      setScenarios(list);
      setScenario((list.find((s) => s.recommended) ?? list[0])?.id ?? "");
    });
    void api.doctor(true).then(setDoctor);
    void api.txStatus().then((s) => setTxReady(s.available), () => setTxReady(false));
    void api.listSessions().then(setRecent);
  }, [api]);

  const real = devices.filter((d) => d.driver !== "simulated");
  const sims = devices.filter((d) => d.driver === "simulated");
  const sim = sims.some((d) => d.id === simPick) ? simPick : (sims[0]?.id ?? "");

  /** 주파수 상태 화면으로 넘어가며 "이 장비로, 이 대역을" 미리 골라 둔다. */
  const openSpectrum = (intent: SpectrumIntent) => {
    saveIntent(intent);
    go("spectrum");
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

  const openFile = () => {
    if (!/\.sigmf-meta$/.test(path.trim())) {
      setPathError(t("start.file.error"));
      return;
    }
    setPathError("");
    void begin(() => start({ kind: "file", path: path.trim(), testbed }));
  };

  const picked = scenarios.find((s) => s.id === scenario);

  return (
    <>
      <SubNav title={t("nav.start")} />
      <Tile tone="light">
        <TileHead title={t("home.title")} lead={t("home.lead")} />
        {real.length === 0 ? (
          <div className="card home-empty" data-testid="home-no-device">
            {hub.mode === "none" ? <p className="t-body">{t("hub.none_mode")}</p> : <SearchNote search={hub.search} onRescan={hub.rescan} onReset={hub.reset} />}
            <div>
              <Button variant="secondary" onClick={hub.connect} data-testid="home-connect">
                {t("hub.mine.reconnect")}
              </Button>
            </div>
            <p className="t-caption muted">{t("home.empty_hint")}</p>
          </div>
        ) : (
          real.map((d) => (
            <div className="card home-device" key={d.id} data-testid={`home-device-${d.id}`}>
              <DeviceCard device={d} />
              <h3 className="t-tagline">{t("home.tasks")}</h3>
              <div className="tasks">
                <Task
                  id="nr"
                  disabled={busy}
                  onClick={() => void begin(() => start({ kind: "device", device: d.id, device_label: d.label }))}
                  note={Object.values(d.stages ?? {}).some((v) => v !== "ok") ? d.note : undefined}
                />
                <Task id="wifi" disabled={busy} onClick={() => openSpectrum({ device: d.id, plan: "wifi-5g" })} />
                <Task id="view" disabled={busy} onClick={() => openSpectrum({ device: d.id, focus: "view" })} />
                <Task id="bt" disabled={busy} onClick={() => openSpectrum({ device: d.id, plan: "ble" })} />
                <Task
                  id="tx"
                  soon={!txReady}
                  disabled={busy}
                  onClick={() => {
                    saveTxDevice(d.id);
                    go("tx");
                  }}
                />
              </div>
            </div>
          ))
        )}
        {hub.adapters.length > 0 && (
          <>
            <h3 className="t-tagline home-group" data-testid="home-adapters">
              {t("home.adapters.title")}
            </h3>
            <p className="t-caption muted">{t("home.adapters.lead")}</p>
            {hub.adapters.map((a) => (
              <div className="card home-device" key={a.id} data-testid={`home-adapter-${a.id}`}>
                <AdapterCard adapter={a} />
                <h3 className="t-tagline">{t("home.tasks")}</h3>
                <div className="tasks">
                  <Task
                    id={a.kind === "wifi" ? "near-wifi" : "near-bt"}
                    disabled={busy}
                    onClick={() => {
                      saveNearby(a.id);
                      go("nearby");
                    }}
                  />
                </div>
              </div>
            ))}
          </>
        )}
      </Tile>

      <Tile tone="parchment" id="without-device">
        <TileHead eyebrow={t("home.without.eyebrow")} title={t("home.without.title")} lead={t("home.without.lead")} />
        <div className="source-grid">
          <div className="card" data-testid="source-practice">
            <h3 className="t-tagline">{t("start.practice.title")}</h3>
            <p className="t-caption muted">{t("start.practice.desc")}</p>
            <div className="chips" role="group" aria-label={t("start.practice.pick")}>
              {scenarios.map((s) => (
                <Chip key={s.id} selected={s.id === scenario} onSelect={() => setScenario(s.id)}>
                  {s.title}
                </Chip>
              ))}
            </div>
            {picked && <p className="t-caption">{picked.description}</p>}
            <div>
              <Button
                data-testid="start-practice"
                disabled={busy || !scenario}
                onClick={() => void begin(() => start({ kind: "synthetic", scenario, band: picked?.band }, { practice: true, name: picked?.title }))}
              >
                {t("start.practice.button")}
              </Button>
            </div>
          </div>

          <div className="card" data-testid="source-file">
            <h3 className="t-tagline">{t("start.file.title")}</h3>
            <p className="t-caption muted">{t("start.file.desc")}</p>
            <Field label={t("start.file.path")} error={pathError}>
              {(p) => (
                <input
                  className="input t-body"
                  placeholder="/path/to/capture.sigmf-meta"
                  value={path}
                  onChange={(e) => setPath(e.target.value)}
                  {...p}
                />
              )}
            </Field>
            <label className="check t-caption">
              <input type="checkbox" checked={testbed} onChange={(e) => setTestbed(e.target.checked)} />
              {t("start.file.testbed")}
            </label>
            <div>
              <Button variant="secondary" disabled={busy} onClick={openFile} data-testid="start-file">
                {t("start.file.button")}
              </Button>
            </div>
          </div>

          <OaiCard />

          {sims.length > 0 && (
            <div className="card" data-testid="source-device">
              <h3 className="t-tagline">{t("home.sim.title")}</h3>
              <p className="t-caption muted">{t("home.sim.desc")}</p>
              <div className="chips" role="group" aria-label={t("start.device.pick")}>
                {sims.map((d) => (
                  <Chip key={d.id} selected={d.id === sim} onSelect={() => setSim(d.id)}>
                    {d.id.replace(/^simulated:/, "")}
                  </Chip>
                ))}
              </div>
              {sims
                .filter((d) => d.id === sim)
                .map((d) => (
                  <div key={d.id} className="t-caption" data-testid="device-capability">
                    <div className="row">
                      {Object.entries(d.stages ?? {}).map(([stage, level]) => (
                        <Badge key={stage} level={level === "ok" ? "ok" : level === "limited" ? "warn" : "error"}>
                          {stageDef(stage)?.label ?? stage} · {t(`device.stage.${level}`)}
                        </Badge>
                      ))}
                    </div>
                  </div>
                ))}
              <div className="row">
                <Button
                  variant="secondary"
                  data-testid="start-device"
                  disabled={busy || !sim}
                  onClick={() => void begin(() => start({ kind: "device", device: sim, device_label: sims.find((d) => d.id === sim)?.label }))}
                >
                  {t("home.sim.follow")}
                </Button>
                <Button variant="link" disabled={busy || !sim} onClick={() => openSpectrum({ device: sim })} data-testid="start-spectrum">
                  {t("home.sim.spectrum")}
                </Button>
              </div>
            </div>
          )}
        </div>
      </Tile>

      <Tile tone="dark">
        <TileHead title={t("start.status.title")} lead={t("start.status.lead")}>
          <a href={href("settings")}>{t("start.status.more")}</a>
        </TileHead>
        <div className="cards" data-testid="doctor-summary">
          {(doctor?.checks ?? []).map((c) => (
            <div className="card" key={c.id}>
              <div className="t-caption muted">{c.label}</div>
              <div className="t-body-strong">{c.detail}</div>
              <div style={{ marginTop: "var(--space-xs)" }}>
                <Badge level={DOCTOR_LEVEL[c.status]}>{t(`doctor.${c.status}`)}</Badge>
              </div>
            </div>
          ))}
        </div>
      </Tile>

      <PhoneTile devices={devices} />

      <Tile tone="parchment">
        <TileHead title={t("start.recent.title")}>
          <a href={href("sessions")}>{t("start.recent.all")}</a>
        </TileHead>
        {recent.length === 0 ? (
          <Empty>{t("start.recent.none")}</Empty>
        ) : (
          <div className="cards">
            {recent.slice(0, 6).map((s) => (
              <a className="card" key={s.id} href={href("follow", s.id)}>
                <div className="t-body-strong">{s.name}</div>
                <div className="t-caption muted">
                  {t(`source.${s.source.kind}`)} · {new Date(s.created_at).toLocaleString()}
                </div>
              </a>
            ))}
          </div>
        )}
      </Tile>
    </>
  );
}
