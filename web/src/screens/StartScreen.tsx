import { useEffect, useRef, useState } from "react";
import type { DoctorReport, Scenario, Session } from "../api";
import { SubNav, Tile, TileHead } from "../components/layout";
import { Badge, Button, Chip, Empty, Field } from "../components/ui";
import { t } from "../i18n";
import { go, href } from "../router";
import { useStore } from "../state/store";
import { useDevices } from "../state/useDevices";
import { DevicePicker } from "./DevicePicker";
import { OaiCard } from "./OaiCard";
import { PhoneTile } from "./PhoneTile";

const DOCTOR_LEVEL = { ok: "ok", warn: "warn", missing: "error" } as const;

/** 1. 시작: 입력 소스 선택(연습 / 파일 / 장비), 장비 상태, 최근 세션. */
export function StartScreen() {
  const { api, start, stageDef } = useStore();
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenario, setScenario] = useState<string>("");
  const devices = useDevices(api) ?? [];
  /** 사용자가 장비를 직접 골랐는가 (모의 실험을 켠 것 포함) */
  const chosen = useRef(false);
  const [device, setDevice] = useState<string>("");
  const [doctor, setDoctor] = useState<DoctorReport | null>(null);
  const [recent, setRecent] = useState<Session[]>([]);
  const [path, setPath] = useState("");
  const [testbed, setTestbed] = useState(false);
  const [pathError, setPathError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api.scenarios().then((list) => {
      setScenarios(list);
      setScenario((list.find((s) => s.recommended) ?? list[0])?.id ?? "");
    });
    void api.doctor(true).then(setDoctor);
    void api.listSessions().then(setRecent);
  }, [api]);

  // 실제 장비가 (늦게라도) 나타나면 기본으로 고른다. 직접 고른 뒤에는 건드리지 않는다.
  const deviceIds = devices.map((d) => `${d.driver}:${d.id}`).join();
  useEffect(() => {
    if (chosen.current) return;
    setDevice(devices.find((d) => d.driver !== "simulated")?.id ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 목록의 내용이 바뀔 때만
  }, [deviceIds]);

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
        <TileHead title={t("start.title")} lead={t("start.lead")} />
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

          <div className="card" data-testid="source-device">
            <h3 className="t-tagline">{t("start.device.title")}</h3>
            <p className="t-caption muted">{t("start.device.desc")}</p>
            {devices.length === 0 ? (
              <Empty action={<a href={href("settings")}>{t("start.device.check")}</a>}>{t("start.device.none")}</Empty>
            ) : (
              <>
                <DevicePicker
                  devices={devices}
                  device={device}
                  disabled={busy}
                  onPick={(id) => {
                    chosen.current = true;
                    setDevice(id);
                  }}
                />
                {devices
                  .filter((d) => d.id === device)
                  .map((d) => (
                    <div key={d.id} className="t-caption" data-testid="device-capability">
                      <p className="muted">{d.note}</p>
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
                    disabled={busy || !device}
                    onClick={() => void begin(() => start({ kind: "device", device, device_label: devices.find((d) => d.id === device)?.label }))}
                  >
                    {t("start.device.button")}
                  </Button>
                  <a href={href("spectrum")} data-testid="start-spectrum">
                    {t("start.device.spectrum")}
                  </a>
                </div>
              </>
            )}
          </div>
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
