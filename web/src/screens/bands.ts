/**
 * "들여다보기"에서 단추 하나로 고르는 대역. 가운데 주파수와 폭(MHz)만 가진다.
 *
 * - BUILTIN: 자주 보는 대역. 이름은 i18n(`view.band.<id>`)에 둔다.
 * - 사용자가 등록한 대역: 이 브라우저의 localStorage 에 둔다(서버에 보내지 않는다).
 */
export interface Band {
  id: string;
  center_mhz: number;
  width_mhz: number;
  /** 사용자가 등록한 대역의 이름. BUILTIN 은 i18n 에서 찾는다 */
  name?: string;
}

export const BUILTIN: Band[] = [
  { id: "fm", center_mhz: 98, width_mhz: 20 }, // FM 방송 88 ~ 108 MHz
  { id: "remote433", center_mhz: 433.92, width_mhz: 2 }, // 433.05 ~ 434.79 MHz 소출력 무선(리모컨, 차 키)
  { id: "iot920", center_mhz: 920, width_mhz: 8 }, // 917 ~ 923.5 MHz 소출력 무선(LoRa, RFID 등, 한국)
  { id: "adsb", center_mhz: 1090, width_mhz: 4 }, // 항공기 위치 방송 1090 MHz
  { id: "gps-l1", center_mhz: 1575.42, width_mhz: 4 }, // GPS L1 C/A
  { id: "nr-n78", center_mhz: 3550, width_mhz: 100 }, // 5G 3.5 GHz 대역 가운데(한국 3.42 ~ 3.70 GHz)
];

const KEY = "nrtrail.viewBands";

export function loadBands(): Band[] {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "[]") as unknown;
    if (!Array.isArray(raw)) return [];
    return (raw as Band[]).filter((b) => typeof b?.name === "string" && b.center_mhz > 0 && b.width_mhz > 0);
  } catch {
    return [];
  }
}

export function saveBands(bands: Band[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(bands));
  } catch {
    /* 저장소를 못 쓰면 이번 화면에서만 남는다 */
  }
}

/** 장비가 닿는 대역만 남기고, 폭은 장비가 한 번에 받을 수 있는 만큼으로 줄인다. */
export function fit(bands: Band[], minHz?: number, maxHz?: number, maxRateHz?: number): Band[] {
  return bands
    .filter((b) => (minHz === undefined || b.center_mhz * 1e6 >= minHz) && (maxHz === undefined || b.center_mhz * 1e6 <= maxHz))
    .map((b) => (maxRateHz !== undefined && b.width_mhz * 1e6 > maxRateHz ? { ...b, width_mhz: maxRateHz / 1e6 } : b));
}
