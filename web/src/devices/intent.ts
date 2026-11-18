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
