/**
 * 사용자가 추가한 "볼 곳": 이름, 가운데 주파수, 폭(MHz). 수신 화면의 "어디를 볼까요"에 단추로 나온다.
 * 서버(sessions/view-bands.json)에 두고, 이 브라우저의 localStorage 에도 한 벌 둔다(서버에 못 닿을 때 쓴다).
 * 브라우저에만 두면 앱이 다른 포트로 떴을 때 사라진 것처럼 보인다(저장소가 주소마다 따로라서).
 */
export interface Band {
  id: string;
  name: string;
  center_mhz: number;
  width_mhz: number;
}

/** 대역폭을 비우고 추가했을 때의 폭 */
export const DEFAULT_WIDTH_MHZ = 2;

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
