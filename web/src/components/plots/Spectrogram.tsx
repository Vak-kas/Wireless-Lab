import { useEffect, useRef } from "react";

/** 0 ~ 1 값의 격자: values[주파수 칸][시간 칸] */
export interface SpectrogramGrid {
  rows: number;
  cols: number;
  values: number[][];
}

/**
 * 스펙트로그램을 캔버스에 그린다: 가로가 시간(오른쪽이 지금), 세로가 주파수(아래가 낮은 주파수), 진할수록 세다.
 * 칸 하나를 점 하나로 찍고 화면 크기로 늘린다. 실시간으로 자주 다시 그려야 해서 SVG 사각형 대신 이렇게 한다
 * (칸이 수만 개면 SVG 는 한 번 그리는 데 눈에 띄게 걸린다).
 * 색은 이 요소의 글자색(토큰)을 쓰고, 세기는 그 색의 불투명도로 나타낸다.
 */
export function Spectrogram({ grid, label }: { grid: SpectrogramGrid; label: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || navigator.userAgent.includes("jsdom")) return; // 테스트 환경에는 캔버스 그리기가 없다
    const ctx = canvas.getContext("2d");
    if (!ctx || grid.rows === 0 || grid.cols === 0) return;
    const ink = (getComputedStyle(canvas).color.match(/\d+(\.\d+)?/g) ?? ["0", "0", "0"]).slice(0, 3).map(Number);
    const image = ctx.createImageData(grid.cols, grid.rows);
    for (let r = 0; r < grid.rows; r++) {
      const row = grid.values[r] ?? [];
      const y = grid.rows - 1 - r; // 낮은 주파수가 아래
      for (let c = 0; c < grid.cols; c++) {
        const i = (y * grid.cols + c) * 4;
        image.data[i] = ink[0] ?? 0;
        image.data[i + 1] = ink[1] ?? 0;
        image.data[i + 2] = ink[2] ?? 0;
        image.data[i + 3] = Math.round(255 * Math.max(0, Math.min(1, row[c] ?? 0)));
      }
    }
    ctx.putImageData(image, 0, 0);
  }, [grid]);
  return <canvas ref={ref} width={Math.max(1, grid.cols)} height={Math.max(1, grid.rows)} role="img" aria-label={label} className="spectrogram" />;
}
