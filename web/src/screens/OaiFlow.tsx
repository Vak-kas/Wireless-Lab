import type { ReactNode } from "react";
import type { OaiPhase } from "../api";
import { t } from "../i18n";

/** 그림에서 지금 불이 들어올 칸. 기록 요청이 끝난 뒤 파일을 여는 동안은 "opening". */
export type FlowPhase = OaiPhase | "opening";

type NodeId = "gnb" | "recorder" | "file" | "follow";
const ORDER: NodeId[] = ["gnb", "recorder", "file", "follow"];
const ACTIVE: Record<FlowPhase, NodeId | null> = {
  idle: null,
  starting: "gnb",
  waiting: "gnb",
  recording: "recorder",
  stopping: "file",
  opening: "follow",
};

const ICONS: Record<NodeId, ReactNode> = {
  // 위성: 몸통과 양쪽 날개, 아래로 퍼지는 신호
  gnb: (
    <>
      <rect x="9" y="5" width="6" height="6" rx="1" />
      <path d="M9 8H3M15 8h6M3 6v4M21 6v4M6 6v4M18 6v4" />
      <path d="M8.5 15a5 5 0 0 1 7 0M6 18a8.5 8.5 0 0 1 12 0" />
    </>
  ),
  // 기록: 바깥 원과 가운데 점
  recorder: (
    <>
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  // 파일: 접힌 귀퉁이와 파형
  file: (
    <>
      <path d="M7 3h7l4 4v14H7z" />
      <path d="M14 3v4h4" />
      <path d="M9 15l1.5-3 2 5 1.5-3 1 1" />
    </>
  ),
  // 따라가기: 이어진 다섯 점
  follow: (
    <>
      <path d="M3 12h18" />
      <circle cx="4" cy="12" r="1.6" />
      <circle cx="8" cy="12" r="1.6" />
      <circle cx="12" cy="12" r="1.6" />
      <circle cx="16" cy="12" r="1.6" />
      <circle cx="20" cy="12" r="1.6" />
    </>
  ),
};

/** OAI 시뮬레이터 → 기록기 → 파일 → 따라가기. 기록 중에는 지금 하는 칸이 강조된다. */
export function OaiFlow({ phase, band, seconds }: { phase: FlowPhase; band: string; seconds: number }) {
  const active = ACTIVE[phase];
  const activeIdx = active ? ORDER.indexOf(active) : -1;
  return (
    <ol className="flow" aria-label={t("oai.diagram.label")} data-testid="oai-flow">
      {ORDER.map((id, i) => {
        const state = i === activeIdx ? "active" : i < activeIdx ? "done" : "idle";
        return (
          <li key={id} className="flow-node" data-state={state} data-link={id === "gnb" ? "soft" : undefined} data-testid={`oai-node-${id}`}>
            <span className="flow-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24">{ICONS[id]}</svg>
            </span>
            <div>
              <div className="flow-name t-caption">
                {t(`oai.node.${id}`)}
                {state !== "idle" && <span className="sr-only"> · {t(`oai.state.${state}`)}</span>}
              </div>
              <div className="t-caption">{t(`oai.node.${id}.desc`, { band, s: seconds })}</div>
              {id === "gnb" && <div className="flow-link t-caption">↓ {t("oai.node.link")}</div>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
