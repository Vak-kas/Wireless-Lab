import { useEffect, useRef, useState } from "react";
import { t } from "../i18n";
import { useStore } from "../state/store";

const POLL_MS = 100; // 화면이 새 줄을 가져오는 간격(초당 10 번. 한 번에 두 줄쯤 온다)
const HISTORY = 400; // 스펙트로그램에 남기는 줄 수(줄 하나가 50 ms 면 20 초)
const LINE_H = 180;
const MIN_SPAN_DB = 20;

const mhz = (hz: number) => Number((hz / 1e6).toFixed(3)).toString();

/**
 * 실시간 그림: 받는 쪽(C++)이 계산해 보내는 "주파수별 세기 한 줄"을 0.1 초마다 가져와 바로 그린다.
 *
 * - 위: 지금의 주파수별 세기. 진한 선이 그 줄 동안의 평균, 옅은 선이 가장 셌던 순간.
 * - 아래: 스펙트로그램. 새 줄이 오른쪽에 붙고 나머지는 왼쪽으로 밀린다. 아래가 낮은 주파수, 진할수록 세다.
 * - 진하기의 기준(바닥과 꼭대기)은 들어오는 값에 맞춰 천천히 따라간다. 이득을 바꿔도 그림이 하얗거나 까맣게 뭉치지 않게.
 *
 * 그림은 캔버스에 직접 그린다(초당 10 번 다시 그리므로 React 로 요소를 만들지 않는다). 색은 글자색 토큰을 쓴다.
 */
export function LiveScope({ id, running, centerHz, rateHz, rowMs }: { id: string; running: boolean; centerHz: number; rateHz: number; rowMs: number }) {
  const { api } = useStore();
  const lineRef = useRef<HTMLCanvasElement>(null);
  const fallRef = useRef<HTMLCanvasElement>(null);
  const after = useRef(-1);
  const range = useRef<{ lo: number; hi: number } | null>(null);
  const [shown, setShown] = useState<{ rows: number; lo: number; hi: number } | null>(null);

  useEffect(() => {
    if (!running) return;
    let alive = true;
    let asking = false;
    let total = 0;

    const draw = (mean: number[][], max: number[][]) => {
      const line = lineRef.current;
      const fall = fallRef.current;
      const bins = mean[0]?.length ?? 0;
      if (!line || !fall || bins === 0) return;
      // 진하기의 기준을 새 줄들에 맞춰 조금씩 옮긴다: 바닥은 평균의 중앙값, 꼭대기는 최대값
      for (let j = 0; j < mean.length; j++) {
        const floor = [...mean[j]!].sort((a, b) => a - b)[bins >> 1]!;
        const peak = Math.max(...max[j]!);
        const r = range.current;
        range.current = r ? { lo: r.lo * 0.95 + floor * 0.05, hi: peak > r.hi ? peak : r.hi * 0.99 + peak * 0.01 } : { lo: floor, hi: peak };
      }
      const lo = range.current!.lo;
      const hi = Math.max(range.current!.hi, lo + MIN_SPAN_DB);
      total += mean.length;
      setShown({ rows: total, lo, hi });
      if (navigator.userAgent.includes("jsdom")) return; // 테스트 환경에는 캔버스 그리기가 없다
      const ink = (getComputedStyle(fall).color.match(/\d+(\.\d+)?/g) ?? ["0", "0", "0"]).slice(0, 3).map(Number);

      // 스펙트로그램: 있던 그림을 왼쪽으로 밀고 새 줄들을 오른쪽에 붙인다
      const f = fall.getContext("2d");
      if (f) {
        if (fall.height !== bins) fall.height = bins;
        const n = Math.min(mean.length, HISTORY);
        f.globalCompositeOperation = "copy"; // 밀 때 겹쳐 칠하지 않고 그대로 옮긴다
        f.drawImage(fall, -n, 0);
        f.globalCompositeOperation = "source-over";
        const image = f.createImageData(n, bins);
        for (let j = 0; j < n; j++) {
          const row = max[max.length - n + j]!;
          for (let b = 0; b < bins; b++) {
            const i = ((bins - 1 - b) * n + j) * 4; // 낮은 주파수가 아래
            image.data[i] = ink[0] ?? 0;
            image.data[i + 1] = ink[1] ?? 0;
            image.data[i + 2] = ink[2] ?? 0;
            image.data[i + 3] = Math.round(255 * Math.max(0, Math.min(1, (row[b]! - lo) / (hi - lo))));
          }
        }
        f.putImageData(image, HISTORY - n, 0);
      }

      // 지금의 주파수별 세기: 마지막 줄
      const l = line.getContext("2d");
      if (l) {
        const w = line.width;
        const h = line.height;
        const bottom = lo - 5;
        const span = hi + 5 - bottom;
        const path = (row: number[]) => {
          l.beginPath();
          row.forEach((v, b) => {
            const x = ((b + 0.5) / bins) * w;
            const y = h - ((v - bottom) / span) * h;
            if (b === 0) l.moveTo(x, y);
            else l.lineTo(x, y);
          });
          l.stroke();
        };
        l.clearRect(0, 0, w, h);
        l.strokeStyle = `rgb(${ink[0]}, ${ink[1]}, ${ink[2]})`;
        l.lineWidth = 2;
        l.globalAlpha = 0.3;
        path(max[max.length - 1]!);
        l.globalAlpha = 1;
        path(mean[mean.length - 1]!);
      }
    };

    const tick = async () => {
      if (asking) return;
      asking = true;
      try {
        const got = await api.streamRows(id, after.current);
        if (alive && got.mean.length > 0) {
          after.current = got.next;
          draw(got.mean, got.max);
        }
      } catch {
        /* 한 번 못 가져와도 다음에 이어서 가져온다 */
      } finally {
        asking = false;
      }
    };
    const timer = setInterval(() => void tick(), POLL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [api, id, running]);

  return (
    <div className="card scope" data-testid="live-scope">
      <canvas ref={lineRef} width={768} height={LINE_H} className="scope-line" role="img" aria-label={t("view.plot.spectrum")} />
      <canvas ref={fallRef} width={HISTORY} height={256} className="scope-fall" role="img" aria-label={t("view.plot.waterfall")} />
      <div className="scope-axis t-caption muted">
        <span>{mhz(centerHz - rateHz / 2)} MHz</span>
        <span>{mhz(centerHz)} MHz</span>
        <span>{mhz(centerHz + rateHz / 2)} MHz</span>
      </div>
      <p className="t-caption muted center" data-testid="live-scope-note">
        {shown ? t("live.scope.caption", { s: ((HISTORY * rowMs) / 1e3).toFixed(0), lo: shown.lo.toFixed(0), hi: shown.hi.toFixed(0), n: Math.round(1e3 / Math.max(rowMs, 1)) }) : t("live.scope.waiting")}
      </p>
    </div>
  );
}
