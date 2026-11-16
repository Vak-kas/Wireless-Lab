import { useCallback, useEffect, useState } from "react";
import type { DeviceInfo, DoctorReport, Session, Settings } from "../api";
import { SubNav, Tile, TileHead } from "../components/layout";
import { Badge, Button, Chip, Empty, Field } from "../components/ui";
import { setLang, t } from "../i18n";
import { href } from "../router";
import { useStore } from "../state/store";

const DOCTOR_LEVEL = { ok: "ok", warn: "warn", missing: "error" } as const;

/** 6. 세션: 기록 목록, 재생(다시 열기), 리포트 내보내기. */
export function SessionsScreen() {
  const { api, session: current, close } = useStore();
  const [list, setList] = useState<Session[] | null>(null);
  const load = useCallback(() => void api.listSessions().then(setList), [api]);
  useEffect(load, [load]);

  const remove = async (s: Session) => {
    if (!window.confirm(t("sessions.confirm_delete", { name: s.name }))) return;
    await api.deleteSession(s.id);
    if (current?.id === s.id) close();
    load();
  };

  return (
    <>
      <SubNav title={t("nav.sessions")} />
      <Tile tone="light" wide>
        <TileHead title={t("sessions.title")} lead={t("sessions.lead")} />
        {list && list.length === 0 && <Empty action={<a href="#/">{t("sessions.goto_start")}</a>}>{t("sessions.none")}</Empty>}
        {list && list.length > 0 && (
          <div className="table-wrap">
            <table className="data t-caption" data-testid="sessions-table">
              <thead>
                <tr>
                  <th scope="col">{t("sessions.name")}</th>
                  <th scope="col">{t("sessions.source")}</th>
                  <th scope="col">{t("sessions.created")}</th>
                  <th scope="col">{t("sessions.progress")}</th>
                  <th scope="col">
                    <span className="sr-only">{t("sessions.actions")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {list.map((s) => {
                  const done = s.stages.filter((x) => x.state === "done").length;
                  return (
                    <tr key={s.id}>
                      <td className="t-caption-strong">{s.name}</td>
                      <td>
                        {t(`source.${s.source.kind}`)}
                        {s.source.testbed ? ` · ${t("sessions.testbed")}` : ""}
                      </td>
                      <td>{new Date(s.created_at).toLocaleString()}</td>
                      <td className="num">{t("sessions.done", { done, total: s.stages.length })}</td>
                      <td>
                        <div className="row">
                          <a href={href("follow", s.id)}>{t("sessions.open")}</a>
                          <a href={api.reportUrl(s.id)} target="_blank" rel="noreferrer">
                            {t("sessions.report")}
                          </a>
                          <Button variant="link" onClick={() => void remove(s)}>
                            {t("sessions.delete")}
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Tile>
      <div className="page-end" />
    </>
  );
}

type NumKey = "lat" | "lon" | "alt_m";

/** 7. 설정 / 점검: 장비, 사용자 위치, 기준값, doctor 결과. */
export function SettingsScreen() {
  const { api } = useStore();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [saved, setSaved] = useState(false);
  const [doctor, setDoctor] = useState<DoctorReport | null>(null);
  const [checking, setChecking] = useState(false);
  const [devices, setDevices] = useState<DeviceInfo[]>([]);

  useEffect(() => {
    void api.settings().then(setSettings);
    void api.doctor(true).then(setDoctor);
    void api.devices().then(setDevices);
  }, [api]);

  const recheck = async () => {
    setChecking(true);
    try {
      setDoctor(await api.doctor(false));
    } finally {
      setChecking(false);
    }
  };

  if (!settings) return <SubNav title={t("nav.settings")} />;
  const patch = (p: Partial<Settings>) => {
    setSaved(false);
    setSettings({ ...settings, ...p });
  };
  const locError = (k: NumKey): string => {
    const v = settings.location[k];
    if (!Number.isFinite(v)) return t("settings.error.number");
    if (k === "lat" && Math.abs(v) > 90) return t("ntn.error.lat");
    if (k === "lon" && Math.abs(v) > 180) return t("ntn.error.lon");
    return "";
  };
  const invalid = (["lat", "lon", "alt_m"] as NumKey[]).some((k) => locError(k));
  const save = async () => {
    setSettings(await api.saveSettings(settings));
    setLang(settings.lang);
    setSaved(true);
  };
  const numInput = (value: number | undefined, onChange: (v: number) => void, p: object) => (
    <input className="input t-body" inputMode="decimal" value={value === undefined || Number.isNaN(value) ? "" : String(value)} onChange={(e) => onChange(e.target.value === "" ? NaN : Number(e.target.value))} {...p} />
  );

  return (
    <>
      <SubNav
        title={t("nav.settings")}
        action={
          <Button onClick={() => void save()} disabled={invalid} data-testid="settings-save">
            {t("settings.save")}
          </Button>
        }
      >
        {saved && <Badge level="ok">{t("settings.saved")}</Badge>}
      </SubNav>

      <Tile tone="light">
        <TileHead title={t("settings.location.title")} lead={t("settings.location.lead")} />
        <div className="form-row">
          {(["lat", "lon", "alt_m"] as NumKey[]).map((k) => (
            <Field key={k} label={t(`settings.location.${k}`)} error={locError(k)}>
              {(p) => numInput(settings.location[k], (v) => patch({ location: { ...settings.location, [k]: v } }), p)}
            </Field>
          ))}
        </div>
      </Tile>

      <Tile tone="parchment">
        <TileHead title={t("settings.device.title")} lead={t("settings.device.lead")} />
        <div className="form-row">
          <Field label={t("settings.device.center")}>
            {(p) => numInput(settings.device.center_freq_hz === undefined ? undefined : settings.device.center_freq_hz / 1e6, (v) => patch({ device: { ...settings.device, center_freq_hz: v * 1e6 } }), p)}
          </Field>
          <Field label={t("settings.device.rate")}>
            {(p) => numInput(settings.device.sample_rate_hz === undefined ? undefined : settings.device.sample_rate_hz / 1e6, (v) => patch({ device: { ...settings.device, sample_rate_hz: v * 1e6 } }), p)}
          </Field>
          <Field label={t("settings.device.gain")}>{(p) => numInput(settings.device.gain_db, (v) => patch({ device: { ...settings.device, gain_db: v } }), p)}</Field>
          <Field label={t("settings.device.antenna")}>
            {(p) => <input className="input t-body" value={settings.device.antenna ?? ""} onChange={(e) => patch({ device: { ...settings.device, antenna: e.target.value } })} {...p} />}
          </Field>
        </div>
        <label className="check t-caption">
          <input type="checkbox" checked={settings.device.external_clock ?? false} onChange={(e) => patch({ device: { ...settings.device, external_clock: e.target.checked } })} />
          {t("settings.device.clock")}
        </label>
        <h3 className="group-title t-body-strong">{t("settings.device.found")}</h3>
        {devices.length === 0 ? (
          <Empty>{t("start.device.none")}</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data t-caption" data-testid="devices-table">
              <thead>
                <tr>
                  <th scope="col">{t("settings.device.name")}</th>
                  <th scope="col" className="right">
                    {t("settings.device.max_rate")}
                  </th>
                  <th scope="col" className="right">
                    {t("settings.device.bits")}
                  </th>
                  <th scope="col">{t("settings.device.note")}</th>
                </tr>
              </thead>
              <tbody>
                {devices.map((d) => (
                  <tr key={d.id}>
                    <td className="t-caption-strong">{d.label}</td>
                    <td className="right num">{d.max_sample_rate_hz ? `${d.max_sample_rate_hz / 1e6} MHz` : "–"}</td>
                    <td className="right num">{d.bits ?? "–"}</td>
                    <td>{d.note ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Tile>

      <Tile tone="light">
        <TileHead title={t("settings.thresholds.title")} lead={t("settings.thresholds.lead")} />
        <div className="form-row">
          <Field label={t("settings.cfo")}>{(p) => numInput(settings.cfo_search_hz / 1e3, (v) => patch({ cfo_search_hz: v * 1e3 }), p)}</Field>
          <Field label={t("settings.cfo_ntn")}>{(p) => numInput(settings.cfo_search_ntn_hz / 1e3, (v) => patch({ cfo_search_ntn_hz: v * 1e3 }), p)}</Field>
          {Object.entries(settings.thresholds).map(([k, v]) => (
            <Field key={k} label={t(`settings.thresholds.${k}`)}>
              {(p) => numInput(v, (nv) => patch({ thresholds: { ...settings.thresholds, [k]: nv } }), p)}
            </Field>
          ))}
        </div>
        <h3 className="group-title t-body-strong">{t("settings.lang")}</h3>
        <div className="chips" role="group" aria-label={t("settings.lang")}>
          {(["ko", "en"] as const).map((l) => (
            <Chip key={l} selected={settings.lang === l} onSelect={() => patch({ lang: l })}>
              {t(`settings.lang.${l}`)}
            </Chip>
          ))}
        </div>
      </Tile>

      <Tile tone="dark">
        <TileHead title={t("settings.doctor.title")} lead={t("settings.doctor.lead")}>
          <Button variant="secondary" onClick={() => void recheck()} disabled={checking} data-testid="doctor-recheck">
            {checking ? t("status.running") : t("settings.doctor.recheck")}
          </Button>
        </TileHead>
        <div className="table-wrap">
          <table className="data t-caption" data-testid="doctor-table">
            <thead>
              <tr>
                <th scope="col">{t("settings.doctor.item")}</th>
                <th scope="col">{t("settings.doctor.state")}</th>
                <th scope="col">{t("settings.doctor.detail")}</th>
                <th scope="col">{t("settings.doctor.fix")}</th>
              </tr>
            </thead>
            <tbody>
              {(doctor?.checks ?? []).map((c) => (
                <tr key={c.id}>
                  <td className="t-caption-strong">{c.label}</td>
                  <td>
                    <Badge level={DOCTOR_LEVEL[c.status]}>{t(`doctor.${c.status}`)}</Badge>
                  </td>
                  <td>{c.detail}</td>
                  <td>{c.fix}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Tile>
      <div className="page-end" />
    </>
  );
}
