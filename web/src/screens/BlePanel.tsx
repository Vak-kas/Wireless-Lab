import type { BleDevice } from "../api";
import { t } from "../i18n";

/** 주변 블루투스 기기 표. 주소가 "임의"인 기기는 사생활 보호를 위해 주소를 주기적으로 바꾸므로 같은 기기가 여러 줄로 보일 수 있다. */
export function BleTable({ devices, directed, broken }: { devices: (BleDevice & { at?: number })[]; directed: Record<string, number>; broken: number }) {
  const others = Object.entries(directed);
  return (
    <div data-testid="ble-panel">
      {devices.length === 0 ? (
        <p className="t-caption muted">{t("ble.none")}</p>
      ) : (
        <div className="table-wrap">
          <table className="data t-caption" data-testid="ble-table">
            <caption className="sr-only">{t("ble.title")}</caption>
            <thead>
              <tr>
                {["address", "kind", "name", "company", "types", "count", "power", "channel"].map((c) => (
                  <th key={c} scope="col" className="t-caption-strong">
                    {t(`ble.col.${c}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {devices.map((d) => (
                <tr key={d.address}>
                  <td>{d.address}</td>
                  <td>{t(`ble.addr.${d.address_type}`)}</td>
                  <td>{d.name || "—"}</td>
                  <td>{d.company || (d.company_id !== null && d.company_id !== undefined ? `0x${d.company_id.toString(16).toUpperCase().padStart(4, "0")}` : "—")}</td>
                  <td>{d.pdu_types.join(", ")}</td>
                  <td>{d.count}</td>
                  <td>{d.power_db.toFixed(1)}</td>
                  <td>{d.channel}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="t-caption muted">
        {t("ble.note")}
        {others.length > 0 ? ` ${t("ble.directed", { list: others.map(([k, v]) => `${k} ${v}`).join(", ") })}` : ""}
        {broken > 0 ? ` ${t("ble.broken", { n: broken })}` : ""}
      </p>
    </div>
  );
}
