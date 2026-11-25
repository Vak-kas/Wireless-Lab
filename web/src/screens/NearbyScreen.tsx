import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Adapter, BleNearby, NearbyNetwork, WifiNearby } from "../api";
import { ApiError } from "../api/http";
import { SubNav, Tile, TileHead } from "../components/layout";
import { Button, Chip, Empty } from "../components/ui";
import { t } from "../i18n";
import { href } from "../router";
import { useStore } from "../state/store";
import { AdapterCard, useUsableDevices } from "../devices/DeviceHub";
import { takeNearby } from "../devices/intent";

const REPEAT_MS = 8000;
const BLE_SECONDS = 4;
const RSSI_MIN = -100;
const RSSI_MAX = -30;
const BANDS = ["2.4", "5", "6"] as const;

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** 대역 하나의 채널별 막대: 가로는 채널 번호 순서, 세로는 받은 세기. 같은 채널의 망은 겹쳐서 가장 센 것이 보인다. */
function BandChart({ band, networks }: { band: string; networks: NearbyNetwork[] }) {
  const channels = [...new Set(networks.map((n) => n.channel).filter((c): c is number => c !== null))].sort((a, b) => a - b);
  const W = 640;
  const H = 160;
  const left = 44;
  const bottom = 24;
  const step = (W - left - 8) / Math.max(channels.length, 1);
  const y = (rssi: number) => 8 + ((RSSI_MAX - Math.max(RSSI_MIN, Math.min(RSSI_MAX, rssi))) / (RSSI_MAX - RSSI_MIN)) * (H - bottom - 8);
  return (
    <figure className="nearby-chart" data-testid={`nearby-chart-${band}`}>
      <figcaption className="t-caption-strong">{t("nearby.band", { band })}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t("nearby.chart.alt", { band, n: networks.length })}>
        {[-40, -60, -80].map((v) => (
          <g key={v}>
            <line className="grid" x1={left} x2={W - 8} y1={y(v)} y2={y(v)} />
            <text className="axis" x={left - 6} y={y(v) + 4} textAnchor="end">
              {v}
            </text>
          </g>
        ))}
        {channels.map((ch, i) => {
          const here = networks.filter((n) => n.channel === ch && n.rssi_dbm !== null).sort((a, b) => (a.rssi_dbm ?? 0) - (b.rssi_dbm ?? 0));
          const x = left + i * step + step * 0.15;
          return (
            <g key={ch}>
              {here.map((n, k) => (
                <rect key={k} className="bar" x={x} width={step * 0.7} y={y(n.rssi_dbm ?? RSSI_MIN)} height={Math.max(1, H - bottom - y(n.rssi_dbm ?? RSSI_MIN))} />
              ))}
              <text className="axis" x={x + step * 0.35} y={H - 8} textAnchor="middle">
                {ch}
              </text>
              {here.length > 1 && (
                <text className="axis" x={x + step * 0.35} y={y(here[here.length - 1]?.rssi_dbm ?? RSSI_MIN) - 4} textAnchor="middle">
                  ×{here.length}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </figure>
  );
}

/** 망 이름이 가려졌을 때: 권한을 물어볼 수 있으면 묻는 단추, 아니면 설정 창을 여는 단추. */
function HiddenNote({ data, onAllowed }: { data: WifiNearby; onAllowed: () => void }) {
  const { api } = useStore();
  const [state, setState] = useState<string>(data.location ?? "unknown");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  useEffect(() => setState(data.location ?? "unknown"), [data.location]);
  const ask = async () => {
    setBusy(true);
    setNote("");
    try {
      const r = await api.adapterAskLocation();
      setState(r.state);
      if (r.state === "authorized") onAllowed();
    } catch (e) {
      setNote(message(e));
    } finally {
      setBusy(false);
    }
  };
  const open = () =>
    void api.adapterOpenSettings("location").then(
      () => setNote(t("nearby.perm.opened")),
      (e: unknown) => setNote(message(e)),
    );
  return (
    <div className="perm-note" data-testid="nearby-hidden">
      <p className="t-caption notice">! {t("nearby.wifi.hidden")}</p>
      <p className="t-caption muted">{t(`nearby.perm.location.${state}`)}</p>
      <div className="row">
        {state === "undetermined" && (
          <Button onClick={() => void ask()} disabled={busy} data-testid="perm-ask">
            {t(busy ? "nearby.perm.asking" : "nearby.perm.ask")}
          </Button>
        )}
        <Button variant="secondary" onClick={open} data-testid="perm-open">
          {t("nearby.perm.open.location")}
        </Button>
      </div>
      {note && (
        <p className="t-caption muted" role="status" data-testid="perm-note">
          {note}
        </p>
      )}
    </div>
  );
}

function WifiResult({ data, onAllowed }: { data: WifiNearby; onAllowed: () => void }) {
  const byBand = BANDS.map((b) => [b, data.networks.filter((n) => n.band === b)] as const).filter(([, list]) => list.length > 0);
  return (
    <div className="stack" data-testid="nearby-wifi">
      {data.names_hidden && <HiddenNote data={data} onAllowed={onAllowed} />}
      {data.current && (
        <p className="t-caption muted" data-testid="nearby-current">
          {t("nearby.wifi.current", { channel: data.current.channel, band: data.current.band, rssi: data.current.rssi_dbm, noise: data.current.noise_dbm })}
        </p>
      )}
      {data.networks.length === 0 ? (
        <Empty>{t("nearby.wifi.none")}</Empty>
      ) : (
        <>
          {byBand.map(([b, list]) => (
            <BandChart key={b} band={b} networks={list} />
          ))}
          <div className="table-wrap">
            <table className="data t-caption" data-testid="nearby-wifi-table">
              <caption className="sr-only">{t("nearby.wifi.title")}</caption>
              <thead>
                <tr>
                  {["name", "address", "band", "channel", "width", "rssi"].map((c) => (
                    <th key={c} scope="col" className="t-caption-strong">
                      {t(`nearby.col.${c}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.networks.map((n, i) => (
                  <tr key={`${n.bssid ?? ""}-${i}`}>
                    <td>{n.ssid ?? "—"}</td>
                    <td>{n.bssid ?? "—"}</td>
                    <td>{n.band ? `${n.band} GHz` : "—"}</td>
                    <td>{n.channel ?? "—"}</td>
                    <td>{n.width_mhz ? `${n.width_mhz} MHz` : "—"}</td>
                    <td>{n.rssi_dbm ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <p className="t-caption muted">{t("nearby.wifi.note")}</p>
    </div>
  );
}

function BleResult({ data }: { data: BleNearby }) {
  return (
    <div className="stack" data-testid="nearby-ble">
      {data.devices.length === 0 ? (
        <Empty>{t("nearby.ble.none")}</Empty>
      ) : (
        <div className="table-wrap">
          <table className="data t-caption" data-testid="nearby-ble-table">
            <caption className="sr-only">{t("nearby.ble.title")}</caption>
            <thead>
              <tr>
                {["name", "address", "company", "count", "rssi"].map((c) => (
                  <th key={c} scope="col" className="t-caption-strong">
                    {t(`nearby.col.${c}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.devices.map((d) => (
                <tr key={d.address}>
                  <td>{d.name || "—"}</td>
                  <td>{d.address}</td>
                  <td>{d.company || (d.company_ids[0] !== undefined ? `0x${d.company_ids[0].toString(16).toUpperCase().padStart(4, "0")}` : "—")}</td>
                  <td>{d.count}</td>
                  <td>{d.rssi_dbm}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="t-caption muted">{t("nearby.ble.note")}</p>
    </div>
  );
}

/** 컴퓨터의 Wi-Fi·블루투스 어댑터로 주변을 본다(방송 정보만. 연결하지 않는다). */
/** adapter 를 주면 그 어댑터로 고정하고, embedded 면 작업판의 칸 안이라 화면 머리와 어댑터 고르기를 그리지 않는다. */
export function NearbyScreen({ adapter: fixed, embedded }: { adapter?: string; embedded?: boolean } = {}) {
  const { api } = useStore();
  const { adapters } = useUsableDevices();
  const [wanted] = useState(takeNearby);
  const [picked, setPicked] = useState("");
  const adapter: Adapter | undefined = useMemo(
    () => (fixed !== undefined ? adapters.find((a) => a.id === fixed) : (adapters.find((a) => a.id === picked) ?? adapters.find((a) => a.id === wanted) ?? adapters[0])),
    [adapters, picked, wanted, fixed],
  );
  const [wifi, setWifi] = useState<WifiNearby | null>(null);
  const [ble, setBle] = useState<BleNearby | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  /** 운영체제 권한 때문에 실패했는가 (설정 창을 여는 단추를 보여 준다) */
  const [denied, setDenied] = useState(false);
  const [repeat, setRepeat] = useState(true);
  const [rounds, setRounds] = useState(0);
  const running = useRef(false);

  const scan = useCallback(async () => {
    if (!adapter || running.current) return;
    running.current = true;
    setBusy(true);
    try {
      if (adapter.kind === "wifi") setWifi(await api.adapterWifiScan(adapter.id));
      else setBle(await api.adapterBleScan(adapter.id, BLE_SECONDS));
      setError("");
      setDenied(false);
      setRounds((n) => n + 1);
    } catch (e) {
      setError(message(e));
      setDenied(e instanceof ApiError && e.status === 403);
      // 잠깐 바쁜 것(409)은 다음 차례에 다시 하면 된다. 그 밖의 실패(권한 없음, 꺼짐)는 되풀이해도 같은 오류다
      if (!(e instanceof ApiError && e.status === 409)) setRepeat(false);
    } finally {
      running.current = false;
      setBusy(false);
    }
  }, [api, adapter]);

  // 어댑터를 바꾸면 지난 결과를 지우고 다시 본다
  const adapterId = adapter?.id;
  useEffect(() => {
    setWifi(null);
    setBle(null);
    setError("");
    setDenied(false);
    setRounds(0);
    setRepeat(true);
  }, [adapterId]);

  useEffect(() => {
    if (!adapterId || !repeat) return;
    void scan();
    const timer = setInterval(() => void scan(), REPEAT_MS);
    return () => clearInterval(timer);
  }, [adapterId, repeat, scan]);

  return (
    <>
      {!embedded && <SubNav title={t("nearby.title")} />}
      <Tile tone="light">
        {!embedded && <TileHead title={t("nearby.title")} lead={t("nearby.lead")} />}
        {!adapter ? (
          <div className="card home-empty" data-testid="nearby-none">
            <p className="t-body">{t("nearby.no_adapter")}</p>
            <a className="t-body" href={href("start")}>
              {t("nearby.back")}
            </a>
          </div>
        ) : (
          <div className="card home-device">
            {!embedded && adapters.length > 1 && (
              <div className="chips" role="group" aria-label={t("nearby.pick")}>
                {adapters.map((a) => (
                  <Chip key={a.id} selected={a.id === adapter.id} onSelect={() => setPicked(a.id)}>
                    {a.label} · {t(`hub.attach.${a.attach}`)}
                  </Chip>
                ))}
              </div>
            )}
            {!embedded && <AdapterCard adapter={adapter} />}
            <div className="row">
              <Button onClick={() => (repeat ? setRepeat(false) : setRepeat(true))} data-testid="nearby-toggle">
                {repeat ? t("nearby.pause") : t("nearby.resume")}
              </Button>
              <Button variant="secondary" onClick={() => void scan()} disabled={busy} data-testid="nearby-once">
                {t("nearby.once")}
              </Button>
              <span className="t-caption muted" role="status" data-testid="nearby-status">
                {busy ? t(adapter.kind === "wifi" ? "nearby.wifi.busy" : "nearby.ble.busy", { s: BLE_SECONDS }) : rounds > 0 ? t("nearby.rounds", { n: rounds }) : ""}
              </span>
            </div>
            {error && (
              <p className="t-caption notice" role="alert" data-testid="nearby-error">
                ! {error}
              </p>
            )}
            {denied && adapter.kind === "bluetooth" && (
              <div className="row">
                <Button variant="secondary" onClick={() => void api.adapterOpenSettings("bluetooth").catch(() => undefined)} data-testid="perm-open-bt">
                  {t("nearby.perm.open.bluetooth")}
                </Button>
                <span className="t-caption muted">{t("nearby.perm.after")}</span>
              </div>
            )}
            {adapter.kind === "wifi" && wifi && <WifiResult data={wifi} onAllowed={() => void scan()} />}
            {adapter.kind === "bluetooth" && ble && <BleResult data={ble} />}
            <p className="t-caption muted">{t("nearby.limits")}</p>
          </div>
        )}
      </Tile>
    </>
  );
}
