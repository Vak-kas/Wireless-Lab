import { useState } from "react";
import type { DeviceInfo, PhoneCell, PhoneReport } from "../api";
import { Tile, TileHead } from "../components/layout";
import { Badge, Button, Empty, Fold } from "../components/ui";
import { t } from "../i18n";
import { go } from "../router";
import { useStore } from "../state/store";

const fmt = (v: number | string | undefined, unit = "") => (v === undefined || v === null ? "–" : `${v}${unit}`);

/** 휴대폰이 보는 기지국 (선택 기능). adb로 읽은 셀 정보를 SDR 스캔의 출발점으로 쓰고, SDR 결과와 대조한다. */
export function PhoneTile({ devices }: { devices: DeviceInfo[] }) {
  const { api, start, session, results } = useStore();
  const [report, setReport] = useState<PhoneReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const read = async () => {
    setBusy(true);
    setError("");
    try {
      setReport(await api.phoneCells());
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  const follow = async (cell: PhoneCell) => {
    const device = devices[0];
    if (!device || cell.freq_mhz === undefined) return;
    const s = await start({ kind: "device", device: device.id, device_label: device.label, center_freq_hz: cell.freq_mhz * 1e6, band: cell.band });
    go("scan", s.id);
  };

  // SDR로 찾은 기지국(열려 있는 세션의 스캔 결과)과 대조한다.
  const sdrCells = (results.scan?.next_inputs.cells as { pci: number; ss_ref_hz: number; gscn: number }[] | undefined) ?? [];
  const sdr = sdrCells.find((c) => c.gscn === (session?.selected_cell?.gscn ?? results.scan?.next_inputs.selected_gscn)) ?? sdrCells[0];
  const compare = (cell: PhoneCell) => {
    if (!sdr || cell.pci === undefined) return null;
    const delta = cell.freq_mhz === undefined ? null : Math.abs(cell.freq_mhz - sdr.ss_ref_hz / 1e6);
    return { match: cell.pci === sdr.pci, delta };
  };

  return (
    <Tile tone="light" id="phone">
      <TileHead title={t("phone.title")} lead={t("phone.lead")}>
        <Button variant="secondary" onClick={() => void read()} disabled={busy} data-testid="phone-read">
          {busy ? t("status.running") : t("phone.read")}
        </Button>
      </TileHead>
      {error && <Empty>{t("status.error", { message: error })}</Empty>}
      {report && report.status !== "ok" && (
        <Empty>
          <span data-testid="phone-status">{t(`phone.status.${report.status}`)}</span>
        </Empty>
      )}
      {report?.status === "ok" && (
        <div className="cards" data-testid="phone-cells">
          {report.cells.map((cell, i) => {
            const cmp = compare(cell);
            return (
              <div className="card stack" key={i}>
                <div className="row">
                  <span className="t-tagline">
                    {cell.rat} · PCI {fmt(cell.pci)}
                  </span>
                  {cell.registered && <Badge level="ok">{t("phone.registered")}</Badge>}
                </div>
                <div className="t-caption num">
                  {t("phone.freq")}: {fmt(cell.freq_mhz, " MHz")} · ARFCN {fmt(cell.arfcn)} {cell.band ? `· ${cell.band}` : ""}
                  <br />
                  PLMN {fmt(cell.mcc)}-{fmt(cell.mnc)} · TAC {fmt(cell.tac)} · {t("phone.cell_id")} {fmt(cell.cell_id)}
                  <br />
                  RSRP {fmt(cell.rsrp_dbm, " dBm")} · RSRQ {fmt(cell.rsrq_db, " dB")} · SINR {fmt(cell.sinr_db, " dB")}
                  {cell.timing_advance !== undefined ? ` · TA ${cell.timing_advance}` : ""}
                </div>
                {cmp && (
                  <div data-testid="phone-compare">
                    <Badge level={cmp.match ? "ok" : "warn"}>
                      {cmp.match ? t("phone.match") : t("phone.mismatch")}
                      {cmp.delta !== null ? ` · ${t("phone.delta", { mhz: cmp.delta.toFixed(2) })}` : ""}
                    </Badge>
                  </div>
                )}
                {cell.rat === "NR" && cell.freq_mhz !== undefined && (
                  <div>
                    <Button variant="link" disabled={devices.length === 0} onClick={() => void follow(cell)} title={devices.length === 0 ? t("phone.need_device") : undefined}>
                      {t("phone.follow")}
                    </Button>
                    {devices.length === 0 && <span className="t-fine-print muted"> {t("phone.need_device")}</span>}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      {report && (
        <>
          {report.raw && (report.status === "unparsed" || report.cells.length === 0) && (
            <Fold title={t("phone.raw")} defaultOpen={report.status === "unparsed"}>
              <pre className="mono t-fine-print" style={{ whiteSpace: "pre-wrap", lineHeight: 1.4 }}>
                {report.raw}
              </pre>
            </Fold>
          )}
          <ul className="t-caption muted" data-testid="phone-limits">
            {report.limits.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </>
      )}
    </Tile>
  );
}
