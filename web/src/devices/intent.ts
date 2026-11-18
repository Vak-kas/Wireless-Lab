/** 첫 화면에서 "이 장비로 Wi-Fi 보기" 같은 할 일을 누르면, 주파수 상태 화면이 열릴 때 그대로 골라 주기 위한 쪽지. */
export interface SpectrumIntent {
  device: string;
  /** 미리 고를 대역 (예: wifi-5g) */
  plan?: string;
  /** "view" 면 특정 주파수 들여다보기 쪽으로 내려간다 */
  focus?: "view";
}

const KEY = "nrtrail.spectrumIntent";

export function saveIntent(intent: SpectrumIntent): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(intent));
  } catch {
    /* 저장소를 못 쓰면 그냥 화면만 연다 */
  }
}

/** 한 번 읽으면 지운다. */
export function takeIntent(): SpectrumIntent | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
    return raw ? (JSON.parse(raw) as SpectrumIntent) : null;
  } catch {
    return null;
  }
}

const NEARBY_KEY = "nrtrail.nearbyAdapter";

/** 첫 화면에서 누른 어댑터(컴퓨터의 Wi-Fi·블루투스). */
export function saveNearby(id: string): void {
  try {
    sessionStorage.setItem(NEARBY_KEY, id);
  } catch {
    /* 못 쓰면 주변 보기 화면에서 다시 고른다 */
  }
}

export function takeNearby(): string {
  try {
    const v = sessionStorage.getItem(NEARBY_KEY) ?? "";
    sessionStorage.removeItem(NEARBY_KEY);
    return v;
  } catch {
    return "";
  }
}

const TX_KEY = "nrtrail.txDevice";

/** 첫 화면의 "송신"을 누른 장비. */
export function saveTxDevice(id: string): void {
  try {
    sessionStorage.setItem(TX_KEY, id);
  } catch {
    /* 못 쓰면 송신 화면에서 다시 고른다 */
  }
}

export function takeTxDevice(): string {
  try {
    const v = sessionStorage.getItem(TX_KEY) ?? "";
    sessionStorage.removeItem(TX_KEY);
    return v;
  } catch {
    return "";
  }
}
