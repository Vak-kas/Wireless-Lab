import { useState } from "react";
import type { DeviceInfo } from "../api";
import { Button, Chip } from "../components/ui";
import { t } from "../i18n";

export const isSim = (d: DeviceInfo) => d.driver === "simulated";

/**
 * 장비 고르기. 평소에는 실제 장비만 보여 준다. 모의 장비(저장 파일을 장비처럼 흘려보내는 연습용)는
 * "모의 실험하기"를 눌러야 나온다: 실제 장비와 섞여 있으면 헷갈린다.
 */
export function DevicePicker({
  devices,
  device,
  onPick,
  disabled,
  center,
}: {
  devices: DeviceInfo[];
  device: string;
  /** 사용자가 고른 장비. 모의 실험을 켜고 끌 때는 그쪽 첫 장비(없으면 "")가 넘어온다 */
  onPick: (id: string) => void;
  disabled?: boolean;
  center?: boolean;
}) {
  const [sim, setSim] = useState(() => devices.some((d) => d.id === device && isSim(d)));
  const shown = devices.filter((d) => isSim(d) === sim);
  const hasSim = devices.some(isSim);
  const toggle = () => {
    const next = !sim;
    setSim(next);
    onPick(devices.find((d) => isSim(d) === next)?.id ?? "");
  };
  return (
    <div data-testid="device-picker" className={center ? "picker center" : "picker"}>
      {sim && (
<p className="t-caption muted">{t("sim.badge")}</p>
      )}
      {shown.length > 0 ? (
        <div className={`chips ${center ? "center-row" : ""}`} role="group" aria-label={t("start.device.pick")}>
          {shown.map((d) => (
            <Chip key={d.id} selected={d.id === device} onSelect={() => onPick(d.id)} disabled={disabled}>
              {sim ? d.id.replace(/^simulated:/, "") : d.label}
            </Chip>
          ))}
        </div>
      ) : (
        <p className="t-caption muted" data-testid="device-none">
          {t("sim.no_real")}
        </p>
      )}
      {(hasSim || sim) && (
        <p>
          <Button variant="link" onClick={toggle} disabled={disabled} data-testid="sim-toggle">
            {sim ? `← ${t("sim.leave")}` : t("sim.enter")}
          </Button>
        </p>
      )}
      {hasSim && !sim && <p className="t-caption muted">{t("sim.hint")}</p>}
    </div>
  );
}
