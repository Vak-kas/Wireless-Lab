import { useEffect, useState } from "react";
import type { Scenario, Session } from "../api";
import { SubNav, Tile, TileHead } from "../components/layout";
import { Badge, Button, Chip, Field } from "../components/ui";
import { isSim, useUsableDevices } from "../devices/DeviceHub";
import { saveIntent, type SpectrumIntent } from "../devices/intent";
import { t } from "../i18n";
import { go } from "../router";
import { useStore } from "../state/store";
import { OaiCard } from "./OaiCard";

/** 시뮬레이션: 장비 없이 해 보는 것들 — 연습 모드, 저장 파일, OAI 시뮬레이터(있을 때), 모의 장비. */
export function SimScreen() {
  const { api, start, stageDef } = useStore();
  const hub = useUsableDevices();
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenario, setScenario] = useState<string>("");
  const [simPick, setSim] = useState<string>("");
  const [path, setPath] = useState("");
  const [testbed, setTestbed] = useState(false);
  const [pathError, setPathError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api.scenarios().then((list) => {
      setScenarios(list);
      setScenario((list.find((s) => s.recommended) ?? list[0])?.id ?? "");
    });
  }, [api]);

  const sims = (hub.devices ?? []).filter(isSim);
  const sim = sims.some((d) => d.id === simPick) ? simPick : (sims[0]?.id ?? "");

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
      <SubNav title={t("nav.sim")} />
      <Tile tone="light" id="without-device">
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
    </>
  );
}
