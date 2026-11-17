import { useRef, useState } from "react";
import type { Diagnostic, Scalar, StageDef } from "../api";
import { t } from "../i18n";
import { go } from "../router";
import { useStore } from "../state/store";
import { Figure } from "./Figure";
import { Tile, TileHead } from "./layout";
import { Derivations, Diagnostics, ExpertInfo, Values } from "./result";
import { StageConcept } from "./StageConcept";
import { Badge, Button, Empty, LockIcon } from "./ui";

const STATUS_LEVEL = { ok: "ok", partial: "warn", fail: "error" } as const;

/**
 * 단계 하나의 구역: 쉬운 설명 한 줄 → 큰 그림 하나 → 핵심 값 카드 → "계산 과정 보기"·"전문가 정보" 펼침.
 */
export function StageSection({
  def,
  tone,
  selected,
  onSelectRow,
  extraAction,
  runParams,
  stateOverride,
  lockedText,
}: {
  def: StageDef;
  tone: "light" | "parchment" | "dark";
  selected?: Scalar;
  onSelectRow?: (row: Record<string, Scalar>) => void;
  extraAction?: React.ReactNode;
  /** 실행 버튼을 누를 때 함께 보낼 값 (예: 스캔할 대역) */
  runParams?: Record<string, unknown>;
  /** 사슬 밖의 단계(예: RA 관측)는 서버가 상태를 주지 않으므로 화면이 정한다 */
  stateOverride?: "next" | "locked";
  lockedText?: string;
}) {
  const { session, results, job, run, stageState } = useStore();
  const [highlight, setHighlight] = useState<string | null>(null);
  const derivFold = useRef<HTMLDetailsElement>(null);
  const state = stateOverride ?? stageState(def.id)?.state ?? "locked";
  const result = results[def.id];
  const running = job?.stage === def.id;
  const busy = job !== null;

  const onAction = (d: Diagnostic) => {
    const a = d.action;
    if (!a || !session) return;
    if (a.kind === "rerun") void run(a.target ?? def.id, a.params ?? {});
    else if (a.target === "scan") go("scan", session.id);
    else if (a.target) document.getElementById(`stage-${a.target}`)?.scrollIntoView();
  };

  const showDerivation = (id: string) => {
    setHighlight(id);
    if (derivFold.current) derivFold.current.open = true;
    setTimeout(() => document.getElementById(`deriv-${id}`)?.scrollIntoView({ block: "center" }), 30);
  };

  if (state === "locked" && !result) {
    return (
      <Tile tone={tone} id={`stage-${def.id}`} className="tile-locked">
        <TileHead eyebrow={def.question} title={def.title} lead={def.intro}>
          <span className="badge t-caption" data-level="info">
            <LockIcon />
            {t("chain.state.locked")} · {lockedText ?? stageState(def.id)?.locked_reason ?? def.locked_reason ?? ""}
          </span>
        </TileHead>
        <StageConcept stage={def.id} />
      </Tile>
    );
  }

  const figures = result?.plots.filter((p) => p.type !== "table") ?? [];
  const tables = result?.plots.filter((p) => p.type === "table") ?? [];

  return (
    <Tile tone={tone} id={`stage-${def.id}`}>
      <TileHead eyebrow={def.question} title={def.title} lead={running ? job.message || def.intro : result ? result.summary_easy : def.intro}>
        {result && !running && (
          <Badge level={STATUS_LEVEL[result.status]}>
            <span data-testid={`status-${def.id}`}>{t(`stage.status.${result.status}`)}</span>
          </Badge>
        )}
        {running && <span className="spinner" aria-label={t("status.running")} />}
        {!result && !running && (
          <Button onClick={() => void run(def.id, runParams)} disabled={busy} data-testid={`run-${def.id}`}>
            {def.button ?? def.title}
          </Button>
        )}
        {result && !running && result.status !== "fail" && extraAction}
        {result && !running && (
          <Button variant="link" onClick={() => void run(def.id, runParams)} disabled={busy} data-testid={`rerun-${def.id}`}>
            {t("stage.rerun")}
          </Button>
        )}
      </TileHead>

      {!result && <StageConcept stage={def.id} />}
      {!result && !running && def.analogy && <p className="center muted t-body">{def.analogy}</p>}
      {!result && running && <Empty>{t("stage.figure_pending")}</Empty>}

      {result && (
        <>
          <Diagnostics list={result.diagnostics} onAction={onAction} disabled={busy} />
          {figures.length > 0 && <Figure plots={figures} />}
          {tables.map((p) => (
            <Figure key={p.id} plots={[p]} selected={selected} onSelect={onSelectRow} />
          ))}
          {result.values.length > 0 && <Values values={result.values} groups={def.groups} onShowDerivation={showDerivation} />}
          {result.derivations.length > 0 && (
            <details className="fold" ref={derivFold} data-testid={`fold-derivations-${def.id}`}>
              <summary className="t-body">{t("stage.show_derivations", { n: result.derivations.length })}</summary>
              <div className="fold-body">
                <Derivations list={result.derivations} highlight={highlight} />
              </div>
            </details>
          )}
          <details className="fold" data-testid={`fold-expert-${def.id}`}>
            <summary className="t-body">{t("stage.expert")}</summary>
            <div className="fold-body">
              <ExpertInfo result={result} />
            </div>
          </details>
        </>
      )}
    </Tile>
  );
}
