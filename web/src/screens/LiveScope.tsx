import { useEffect, useRef, useState } from "react";
import type { SeenSignal, StreamTapState } from "../api";
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
 * - 아래: 스펙트로그램. 가로는 위 그림과 같은 주파수, 세로는 시간이다. 새 줄이 맨 위에 붙고 나머지는 아래로 밀린다. 진할수록 세다.
 * - 진하기의 기준(바닥과 꼭대기)은 들어오는 값에 맞춰 천천히 따라간다. 이득을 바꿔도 그림이 하얗거나 까맣게 뭉치지 않게.
 *
 * 그림은 캔버스에 직접 그린다(초당 10 번 다시 그리므로 React 로 요소를 만들지 않는다). 색은 글자색 토큰을 쓴다.
 */
export function LiveScope({
  id,
  running,
  centerHz,
  rateHz,
  rowMs,
  taps,
}: {
  id: string;
  running: boolean;
  centerHz: number;
  rateHz: number;
  rowMs: number;
  /** 풀이들의 결과: 추정한 신호가 실제로 풀렸는지("확인")를 보여 주는 데 쓴다 */
  taps?: Record<string, StreamTapState>;
}) {
  const { api } = useStore();
  const lineRef = useRef<HTMLCanvasElement>(null);
  const fallRef = useRef<HTMLCanvasElement>(null);
  const after = useRef(-1);
  const range = useRef<{ lo: number; hi: number } | null>(null);
  const [shown, setShown] = useState<{ rows: number; lo: number; hi: number } | null>(null);
  const [signals, setSignals] = useState<SeenSignal[]>([]);

  useEffect(() => {
    if (!running) return;
    let alive = true;
    let asking = false;
    let total = 0;

    const draw = (mean: number[][], max: number[][], found: SeenSignal[]) => {
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
      const inkCss = getComputedStyle(fall).color; // 글자색 토큰(계산된 값)
      const ink = (inkCss.match(/\d+(\.\d+)?/g) ?? ["0", "0", "0"]).slice(0, 3).map(Number);

      // 스펙트로그램: 가로는 위 그림과 같은 주파수, 세로는 시간. 있던 그림을 아래로 밀고 새 줄들을 맨 위에 붙인다(맨 위가 지금)
      const f = fall.getContext("2d");
      if (f) {
        if (fall.width !== bins) fall.width = bins;
        const n = Math.min(mean.length, HISTORY);
        f.globalCompositeOperation = "copy"; // 밀 때 겹쳐 칠하지 않고 그대로 옮긴다
        f.drawImage(fall, 0, n);
        f.globalCompositeOperation = "source-over";
        const image = f.createImageData(bins, n);
        for (let j = 0; j < n; j++) {
          const row = max[max.length - 1 - j]!; // 가장 새 줄이 맨 위
          for (let b = 0; b < bins; b++) {
            const i = (j * bins + b) * 4;
            image.data[i] = ink[0] ?? 0;
            image.data[i + 1] = ink[1] ?? 0;
            image.data[i + 2] = ink[2] ?? 0;
            image.data[i + 3] = Math.round(255 * Math.max(0, Math.min(1, (row[b]! - lo) / (hi - lo))));
          }
        }
        f.putImageData(image, 0, 0);
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
        // 찾은 신호의 자리를 옅은 띠로 깔고 번호를 적는다(아래 표의 번호와 같다). 지금 보이는 것은 조금 더 진하게
        const left = centerHz - rateHz / 2;
        l.fillStyle = inkCss;
        l.font = "600 20px sans-serif";
        found.forEach((sig, k) => {
          if (sig.kind === "dc") return;
          const x0 = ((sig.lo_hz - left) / rateHz) * w;
          const x1 = ((sig.hi_hz - left) / rateHz) * w;
          l.globalAlpha = sig.now ? 0.14 : 0.06;
          l.fillRect(x0, 0, Math.max(2, x1 - x0), h);
          l.globalAlpha = 0.9;
          l.fillText(String(k + 1), Math.min(w - 14, x0 + 4), 22);
        });
        l.strokeStyle = inkCss;
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
          setSignals(got.signals ?? []);
          draw(got.mean, got.max, got.signals ?? []);
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
  }, [api, id, running, centerHz, rateHz]);

  return (
    <div className="card scope" data-testid="live-scope">
      <canvas ref={lineRef} width={768} height={LINE_H} className="scope-line" role="img" aria-label={t("view.plot.spectrum")} />
      <div className="scope-axis t-caption muted">
        <span>{mhz(centerHz - rateHz / 2)} MHz</span>
        <span>{mhz(centerHz)} MHz</span>
        <span>{mhz(centerHz + rateHz / 2)} MHz</span>
      </div>
      <div className="scope-fall-wrap">
        <canvas ref={fallRef} width={256} height={HISTORY} className="scope-fall" role="img" aria-label={t("view.plot.waterfall")} />
        <span className="scope-when scope-now t-caption">{t("live.scope.now")}</span>
        <span className="scope-when scope-then t-caption">{t("live.scope.ago", { s: ((HISTORY * rowMs) / 1e3).toFixed(0) })}</span>
      </div>
      <p className="t-caption muted center" data-testid="live-scope-note">
        {shown ? t("live.scope.caption", { s: ((HISTORY * rowMs) / 1e3).toFixed(0), lo: shown.lo.toFixed(0), hi: shown.hi.toFixed(0), n: Math.round(1e3 / Math.max(rowMs, 1)) }) : t("live.scope.waiting")}
      </p>
      <SignalTable signals={signals} taps={taps ?? {}} />
    </div>
  );
}

/** 모양으로 추정한 이름. 채널을 알면 함께 적는다. */
function nameOf(sig: SeenSignal): string {
  const channel = sig.channel === null || sig.channel === undefined ? "" : String(sig.channel);
  return t(`signal.kind.${sig.kind}`) + (channel ? ` · ${sig.kind === "bt" ? t("signal.ble_channel", { channel }) : channel}` : "");
}

/** 풀이가 실제로 이 종류의 신호를 풀었으면 그 내용("확인"). 못 풀었거나 풀이가 없으면 빈 문자열. */
function confirmed(sig: SeenSignal, taps: Record<string, StreamTapState>): string {
  if ((sig.kind === "wifi" || sig.kind === "wide") && (taps.wifi?.frames_decoded ?? 0) > 0) {
    const kinds = Object.entries(taps.wifi?.formats ?? {})
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([f]) => f)
      .join(", ");
    return t("signal.confirm.wifi", { kinds, aps: taps.wifi?.aps?.length ?? 0 });
  }
  if (sig.kind === "bt" && (taps.ble?.devices?.length ?? 0) > 0) return t("signal.confirm.ble", { n: taps.ble?.devices?.length ?? 0 });
  return "";
}

/** 지금 보이는 신호들의 표. 번호는 위 그림의 띠에 적힌 번호와 같다. */
function SignalTable({ signals, taps }: { signals: SeenSignal[]; taps: Record<string, StreamTapState> }) {
  const rows = signals.filter((s) => s.kind !== "dc");
  const dc = signals.some((s) => s.kind === "dc");
  return (
    <div className="signals" data-testid="live-signals">
      <h4 className="t-caption-strong">{t("signal.title")}</h4>
      {rows.length === 0 ? (
        <p className="t-caption muted">{t("signal.none")}</p>
      ) : (
        <div className="table-wrap">
          <table className="data t-caption">
            <caption className="sr-only">{t("signal.title")}</caption>
            <thead>
              <tr>
                {["no", "kind", "center", "width", "level", "seen", "confirm"].map((c) => (
                  <th key={c} scope="col" className={`t-caption-strong ${c === "kind" || c === "confirm" ? "" : "right"}`}>
                    {t(`signal.col.${c}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((sig, k) => {
                const ok = confirmed(sig, taps);
                return (
                  <tr key={`${sig.kind}-${sig.center_hz}`} data-now={sig.now}>
                    <td className="right">{signals.indexOf(sig) + 1}</td>
                    <td>
                      {nameOf(sig)} <span className="muted">{ok ? "" : t("signal.guess")}</span>
                    </td>
                    <td className="right">{mhz(sig.center_hz)}</td>
                    <td className="right">{sig.width_hz >= 1e6 ? `${(sig.width_hz / 1e6).toFixed(1)} MHz` : `${Math.round(sig.width_hz / 1e3)} kHz`}</td>
                    <td className="right">+{sig.above_floor_db.toFixed(0)} dB</td>
                    <td className="right">{Math.round(sig.seen * 100)}%</td>
                    <td data-testid={`signal-confirm-${k}`}>{ok || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="t-caption muted">
        {t("signal.note")}
        {dc ? ` ${t("signal.dc")}` : ""}
      </p>
    </div>
  );
}
