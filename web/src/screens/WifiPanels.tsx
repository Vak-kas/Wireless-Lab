import type { WifiAp, WifiPpdu } from "../api";
import { Badge, Button, Chip } from "../components/ui";
import { t } from "../i18n";

/** 찾은 AP 표. "이 대역 고르기"를 누르면 그 AP 가 쓰는 채널들이 채널 맵에서 골라진다. */
export function ApTable({ aps, onPick }: { aps: WifiAp[]; onPick: (ap: WifiAp) => void }) {
  if (aps.length === 0) return <p className="t-caption muted">{t("wifi.aps.none")}</p>;
  return (
    <div className="table-wrap">
      <table className="data t-caption" data-testid="ap-table">
        <caption className="sr-only">{t("wifi.aps.title")}</caption>
        <thead>
          <tr>
            {["ssid", "bssid", "primary", "width", "eht", "power", "pick"].map((c) => (
              <th key={c} scope="col" className="t-caption-strong">
                {c === "pick" ? <span className="sr-only">{t("wifi.pick")}</span> : t(`wifi.col.${c}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {aps.map((ap) => (
            <tr key={ap.bssid}>
              <td>{ap.ssid || t("wifi.hidden")}</td>
              <td>{ap.bssid}</td>
              <td>{ap.primary}</td>
              <td>{ap.width_mhz ? `${ap.width_mhz} MHz` : "—"}</td>
              <td>{ap.eht ? t("wifi.yes") : "—"}</td>
              <td>{ap.power_db.toFixed(1)}</td>
              <td>
                <Button variant="link" onClick={() => onPick(ap)} data-testid={`ap-pick-${ap.bssid}`}>
                  {t("wifi.pick")}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export interface UsigSample {
  /** 받은 시각 (ms) */
  at: number;
  ppdus: WifiPpdu[];
}

const RECENT_MS = 10_000;

/** 최근 구간의 다운링크 PPDU 를 대역폭별로 센다. */
export function countByWidth(samples: UsigSample[], now: number, windowMs = RECENT_MS): { width: number; count: number }[] {
  const counts = new Map<number, number>();
  for (const s of samples) {
    if (now - s.at > windowMs) continue;
    for (const p of s.ppdus) if (!p.uplink && p.bandwidth_mhz) counts.set(p.bandwidth_mhz, (counts.get(p.bandwidth_mhz) ?? 0) + 1);
  }
  return [...counts].map(([width, count]) => ({ width, count })).sort((a, b) => b.width - a.width);
}

/** 가장 많이 쓰인 폭. 같으면 넓은 쪽. */
export const dominant = (rows: { width: number; count: number }[]): number | null =>
  rows.reduce<{ width: number; count: number } | null>((a, r) => (!a || r.count > a.count ? r : a), null)?.width ?? null;

/**
 * 실제 송신 대역폭 지켜보기. 처음 자리 잡은 폭(reference)보다 좁게 보내는 쪽이 주가 되면 경고한다.
 */
export function BandwidthWatch({
  channels,
  channel,
  onChannel,
  samples,
  reference,
  now,
}: {
  channels: string[];
  channel: string;
  onChannel: (name: string) => void;
  samples: UsigSample[];
  reference: number | null;
  now: number;
}) {
  const rows = countByWidth(samples, now);
  const total = rows.reduce((a, r) => a + r.count, 0);
  const main = dominant(rows);
  return (
    <div className="card stack-gap" data-testid="usig-watch">
      <h3 className="t-tagline">{t("wifi.usig.title")}</h3>
      <p className="t-caption muted">{t("wifi.usig.desc")}</p>
      <div className="chips" role="group" aria-label={t("wifi.usig.channel")}>
        <Chip selected={channel === ""} onSelect={() => onChannel("")}>
          {t("wifi.usig.off")}
        </Chip>
        {channels.map((c) => (
          <Chip key={c} selected={c === channel} onSelect={() => onChannel(c)}>
            {c}
          </Chip>
        ))}
      </div>
      {channel !== "" && (
        <>
          <div className="row">
            {reference !== null && <Badge level="info">{t("wifi.usig.reference", { w: reference })}</Badge>}
            {reference !== null && main !== null && main < reference && (
              <Badge level="warn">
                <span data-testid="usig-narrowed">{t("wifi.usig.narrowed", { from: reference, to: main })}</span>
              </Badge>
            )}
          </div>
          {total === 0 ? (
            <p className="t-caption muted">{t("wifi.usig.none")}</p>
          ) : (
            <table className="data t-caption" data-testid="usig-table">
              <caption className="sr-only">{t("wifi.usig.title")}</caption>
              <thead>
                <tr>
                  {["width", "count", "share"].map((c) => (
                    <th key={c} scope="col" className="t-caption-strong">
                      {t(`wifi.usig.col.${c}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.width}>
                    <td>{r.width} MHz</td>
                    <td>{r.count}</td>
                    <td>{Math.round((100 * r.count) / total)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}
