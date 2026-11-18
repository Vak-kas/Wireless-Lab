import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { DeviceInfo, DeviceSearch } from "../api";
import { Badge, Button } from "../components/ui";
import { t } from "../i18n";
import { useStore } from "../state/store";
import { useDevices } from "../state/useDevices";

/** "device": 장비를 쓴다. "none": 장비 없이 시작했다(실제 장비가 필요한 기능은 감춘다). null: 아직 고르지 않았다. */
export type DeviceMode = "device" | "none" | null;
const KEY = "nrtrail.deviceMode";
export const isSim = (d: DeviceInfo) => d.driver === "simulated";

interface Hub {
  /** 화면이 쓸 수 있는 장비. 장비 없이 시작했으면 모의 장비만 */
  devices: DeviceInfo[] | null;
  mode: DeviceMode;
  /** 장비 연결 창을 다시 연다 */
  connect(): void;
  /** 장비 찾기의 지금 상태 (없으면 아직 모름) */
  search: DeviceSearch | null;
  /** 지금 다시 찾는다 */
  rescan(): void;
}
const Ctx = createContext<Hub | null>(null);

/** 장비 목록. 허브가 없으면(화면 하나만 따로 띄운 테스트) 직접 읽는다. */
export function useUsableDevices(): Hub {
  const hub = useContext(Ctx);
  const { api } = useStore();
  const own = useDevices(api, hub === null);
  return hub ?? { devices: own, mode: "device", connect: () => undefined, search: null, rescan: () => undefined };
}

const mhz = (hz?: number) => (hz === undefined ? "" : (hz / 1e6).toFixed(0));

/** 장비 한 대를 나타내는 그림(특정 제품이 아닌 일반적인 SDR 모양). */
function DevicePicture() {
  return (
    <svg className="device-picture" viewBox="0 0 96 64" aria-hidden="true">
      <rect x="10" y="18" width="76" height="34" rx="5" />
      <path d="M22 18V8M22 8l-5-4M22 8l5-4" />
      <path d="M74 18V8M74 8l-5-4M74 8l5-4" />
      <circle cx="22" cy="35" r="4" />
      <circle cx="74" cy="35" r="4" />
      <rect x="40" y="28" width="16" height="14" rx="2" />
      <path d="M44 52v6h8v-6" />
      <path d="M36 32h4M36 38h4M56 32h4M56 38h4" />
    </svg>
  );
}

/**
 * 실제 장비가 하나도 없을 때 보여 주는 한 줄: 찾는 중인지, 다른 프로그램이 쓰는 중인지, 왜 못 찾았는지. 그리고 "다시 찾기".
 */
export function SearchNote({ search, onRescan }: { search: DeviceSearch | null; onRescan: () => void }) {
  const b = search?.backends ?? [];
  const searching = b.some((x) => x.searching);
  const busy = b.flatMap((x) => x.busy_devices ?? []);
  const error = b.map((x) => x.error).find(Boolean);
  const ago = b.map((x) => x.checked_s_ago).find((x) => x !== null && x !== undefined);
  const forS = b.map((x) => x.searching_for_s).find((x) => x !== null && x !== undefined);
  return (
    <div className="search-note" data-testid="search-note">
      {searching ? (
        <p className="searching t-caption" data-testid="connect-searching">
          <span className="spinner" aria-hidden="true" /> {t("hub.search.searching", { s: Math.round(forS ?? 0) })}
        </p>
      ) : busy.length > 0 ? (
        <p className="t-caption" data-testid="search-busy">
          ! {t("hub.search.busy", { list: busy.join(", ") })}
        </p>
      ) : error ? (
        <p className="t-caption" data-testid="search-error">
          ! {t("hub.search.error", { message: error })}
        </p>
      ) : (
        <p className="t-caption muted" data-testid="search-none">
          {b.length === 0 ? t("hub.search.unsupported") : t("hub.search.none", { s: Math.round(ago ?? 0) })}
        </p>
      )}
      {b.length > 0 && (
        <Button variant="link" onClick={onRescan} disabled={searching} data-testid="search-rescan">
          {t("hub.search.rescan")}
        </Button>
      )}
    </div>
  );
}

/** 장비 카드: 그림, 이름, 일련번호, 받을 수 있는 범위. */
export function DeviceCard({ device, action }: { device: DeviceInfo; action?: ReactNode }) {
  return (
    <div className="device-card" data-testid={`device-card-${device.id}`}>
      <DevicePicture />
      <div className="device-card-body">
        <div className="t-body-strong">{device.label.replace(/\s*\(.*\)$/, "")}</div>
        <dl className="t-caption">
          {device.serial && (
            <div>
              <dt className="muted">{t("hub.serial")}</dt>
              <dd>{device.serial}</dd>
            </div>
          )}
          {device.freq_min_hz !== undefined && device.freq_max_hz !== undefined && (
            <div>
              <dt className="muted">{t("hub.range")}</dt>
              <dd>
                {mhz(device.freq_min_hz)} ~ {mhz(device.freq_max_hz)} MHz
              </dd>
            </div>
          )}
          {device.max_sample_rate_hz !== undefined && (
            <div>
              <dt className="muted">{t("hub.rate")}</dt>
              <dd>{mhz(device.max_sample_rate_hz)} Msps</dd>
            </div>
          )}
        </dl>
        {action}
      </div>
    </div>
  );
}

function readMode(): DeviceMode {
  try {
    const v = sessionStorage.getItem(KEY);
    return v === "device" || v === "none" ? v : null;
  } catch {
    return null;
  }
}

/**
 * 장비 허브: 처음 열면 장비 연결 창을 띄우고, 새 장비가 잡히면 알리고, 오른쪽 아래 "내 장비"로 언제든 목록을 본다.
 */
export function DeviceHub({ children }: { children: ReactNode }) {
  const { api } = useStore();
  const all = useDevices(api);
  const [mode, setModeState] = useState<DeviceMode>(readMode);
  const [connecting, setConnecting] = useState(false);
  const [open, setOpen] = useState(false);
  const [arrived, setArrived] = useState<DeviceInfo[]>([]);
  const known = useRef<Set<string> | null>(null);
  const [search, setSearch] = useState<DeviceSearch | null>(null);

  // 찾기 상태를 함께 읽는다(찾는 중인지, 왜 못 찾았는지를 보여 주려고)
  useEffect(() => {
    let alive = true;
    const load = () => void api.deviceSearch().then((x) => alive && setSearch(x), () => undefined);
    load();
    const timer = setInterval(load, 3000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [api]);
  const rescan = useCallback(() => void api.deviceRescan().then(setSearch, () => undefined), [api]);

  const real = useMemo(() => (all ?? []).filter((d) => !isSim(d)), [all]);
  const setMode = useCallback((m: DeviceMode) => {
    setModeState(m);
    try {
      if (m) sessionStorage.setItem(KEY, m);
    } catch {
      /* 저장소를 못 쓰면 이번 화면에서만 기억한다 */
    }
    setConnecting(false);
  }, []);

  // 새로 잡힌 장비를 알린다. 처음 읽은 목록과 연결 창이 떠 있는 동안 잡힌 것은 창에서 이미 보이므로 알리지 않는다.
  const asking = mode === null || connecting;
  useEffect(() => {
    if (all === null) return;
    const ids = new Set(real.map((d) => d.id));
    if (known.current !== null && !asking) {
      const fresh = real.filter((d) => !known.current!.has(d.id));
      if (fresh.length > 0) setArrived((old) => [...old.filter((o) => ids.has(o.id) && !fresh.some((f) => f.id === o.id)), ...fresh]);
    }
    known.current = ids;
    setArrived((old) => (old.every((o) => ids.has(o.id)) ? old : old.filter((o) => ids.has(o.id))));
  }, [all, real, asking]);

  const usable = useMemo(() => (all === null ? null : mode === "none" ? all.filter(isSim) : all), [all, mode]);
  const hub = useMemo<Hub>(() => ({ devices: usable, mode, connect: () => setConnecting(true), search, rescan }), [usable, mode, search, rescan]);

  return (
    <Ctx.Provider value={hub}>
      {children}

      {asking && (
        <div className="overlay" data-testid="connect-overlay">
          <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="connect-title">
            <h2 id="connect-title" className="t-display-md">
              {t("hub.connect.title")}
            </h2>
            <p className="t-body muted">{t("hub.connect.lead")}</p>
            {real.length > 0 ? (
              <div className="device-list">
                {real.map((d) => (
                  <DeviceCard key={d.id} device={d} action={<Badge level="ok">{t("hub.connected")}</Badge>} />
                ))}
              </div>
            ) : (
              <SearchNote search={search} onRescan={rescan} />
            )}
            <div className="dialog-actions">
              <Button onClick={() => setMode("device")} disabled={real.length === 0} data-testid="connect-start" autoFocus>
                {real.length > 1 ? t("hub.connect.start_many", { n: real.length }) : t("hub.connect.start")}
              </Button>
              <Button variant="secondary" onClick={() => setMode("none")} data-testid="connect-skip">
                {t("hub.connect.skip")}
              </Button>
            </div>
            <p className="t-caption muted">{t("hub.connect.skip_note")}</p>
          </div>
        </div>
      )}

      {arrived.length > 0 && !asking && (
        <div className="toast" role="status" data-testid="device-arrived">
          <div className="t-caption-strong">{t("hub.arrived.title")}</div>
          {arrived.map((d) => (
            <DeviceCard key={d.id} device={d} />
          ))}
          <div className="dialog-actions">
            {mode === "none" && (
              <Button
                onClick={() => {
                  setMode("device");
                  setArrived([]);
                }}
                data-testid="arrived-use"
              >
                {t("hub.arrived.use")}
              </Button>
            )}
            <Button variant="secondary" onClick={() => setArrived([])} data-testid="arrived-ok">
              {t("hub.arrived.ok")}
            </Button>
          </div>
        </div>
      )}

      {open && (
        <div className="drawer" role="dialog" aria-label={t("hub.mine.title")} data-testid="my-devices">
          <div className="t-caption-strong">{t("hub.mine.title")}</div>
          {mode === "none" && <p className="t-caption muted">{t("hub.mine.none_mode")}</p>}
          {real.length === 0 ? (
            <SearchNote search={search} onRescan={rescan} />
          ) : (
            real.map((d) => <DeviceCard key={d.id} device={d} />)
          )}
          <div className="dialog-actions">
            <Button
              variant="secondary"
              onClick={() => {
                setOpen(false);
                setConnecting(true);
              }}
              data-testid="my-devices-connect"
            >
              {t("hub.mine.reconnect")}
            </Button>
          </div>
        </div>
      )}
      {!asking && (
        <button type="button" className="fab t-caption-strong" onClick={() => setOpen(!open)} aria-expanded={open} data-testid="my-devices-button">
          <span aria-hidden="true">{open ? "▼" : "▲"}</span> {t("hub.mine.button")}
          <span className="fab-count" data-level={real.length > 0 && mode !== "none" ? "on" : "off"}>
            {real.length}
          </span>
        </button>
      )}
    </Ctx.Provider>
  );
}
