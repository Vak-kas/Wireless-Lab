/**
 * 스펙트로그램의 세기 색. 디자인 토큰 --color-viz-heat-0 ~ 4 (약한 것 → 센 것)를 읽어, 0 ~ 1 의 세기를 그 사이의 색으로 바꾼다.
 * 색 값은 여기 적지 않는다: 토큰(DESIGN-extensions.md → tokens.css)에서 계산된 값을 읽어 쓴다.
 */
const STOPS = 5;
export type Rgb = [number, number, number];

/** 토큰에서 계산된 색 문자열(16진수 표기나 숫자 셋 표기)을 숫자 셋으로 */
function parse(css: string): Rgb {
  const text = css.trim();
  if (text.startsWith("#") && text.length >= 7) return [1, 3, 5].map((k) => parseInt(text.slice(k, k + 2), 16)) as Rgb;
  const m = text.match(/\d+(\.\d+)?/g) ?? ["0", "0", "0"];
  return [Number(m[0]), Number(m[1]), Number(m[2])];
}

/** 색 256 단계(낮은 세기 → 높은 세기). 토큰을 읽지 못하면(테스트 환경 등) 회색 단계가 된다 */
export function heatTable(): Rgb[] {
  const style = getComputedStyle(document.documentElement);
  const stops = Array.from({ length: STOPS }, (_, k) => style.getPropertyValue(`--color-viz-heat-${k}`)).map((v, k) => (v.trim() ? parse(v) : ([k * 60, k * 60, k * 60] as Rgb)));
  return Array.from({ length: 256 }, (_, i) => {
    const at = (i / 255) * (STOPS - 1);
    const a = stops[Math.min(Math.floor(at), STOPS - 2)]!;
    const b = stops[Math.min(Math.floor(at), STOPS - 2) + 1]!;
    const part = at - Math.min(Math.floor(at), STOPS - 2);
    return [0, 1, 2].map((c) => Math.round(a[c]! + (b[c]! - a[c]!) * part)) as Rgb;
  });
}
