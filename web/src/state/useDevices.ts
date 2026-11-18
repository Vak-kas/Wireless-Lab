import { useEffect, useState } from "react";
import type { Api, DeviceInfo } from "../api";

export const DEVICE_POLL_MS = 5000;

/**
 * 장비 목록을 읽고 몇 초마다 다시 읽는다. USRP 는 찾는 데 몇 초 걸려 처음에는 빠져 있을 수 있고, 나중에 꽂을 수도 있다.
 * 아직 한 번도 못 읽었으면 null. active=false 면 다시 읽지 않는다(장비를 쓰는 중).
 */
export function useDevices(api: Api, active = true): DeviceInfo[] | null {
  const [devices, setDevices] = useState<DeviceInfo[] | null>(null);
  useEffect(() => {
    if (!active) return;
    let alive = true;
    const load = () =>
      void api.devices().then(
        (list) => alive && setDevices((old) => (old && old.map((d) => d.id).join() === list.map((d) => d.id).join() ? old : list)),
        () => alive && setDevices((old) => old ?? []),
      );
    load();
    const timer = setInterval(load, DEVICE_POLL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [api, active]);
  return devices;
}
