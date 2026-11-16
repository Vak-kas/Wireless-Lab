import katex from "katex";
import { useMemo, type ReactNode } from "react";
import type { Derivation, Diagnostic, StageResult, Value } from "../api";
import { t } from "../i18n";
import { fmtValue } from "./plots/scale";
import { Button, Fold, Term } from "./ui";

/** 핵심 값 카드 하나. 계산한 값이면 "어떻게 구했나" 링크로 계산 과정 카드에 연결된다. */
export function ValueCard({ value, onShowDerivation }: { value: Value; onShowDerivation?: (id: string) => void }) {
  const kind = t(`value.kind.${value.kind}`);
  return (
    <div className="card value-card" data-testid={`value-${value.key}`}>
      <div className="label t-caption">
        <Term k={value.term}>{value.label}</Term>
      </div>
      <div className="value t-tagline num">
        {fmtValue(value.value)}
        {value.unit && <span className="unit t-caption">{value.unit}</span>}
      </div>
      <div className="meta t-fine-print">
        {kind}
        {value.raw !== undefined && value.raw !== null ? ` · ${t("value.raw")} ${fmtValue(value.raw)}` : ""}
        {value.source ? ` · ${value.source}` : ""}
      </div>
      {value.note && <div className="meta t-fine-print">{value.note}</div>}
      {value.derivation_id && onShowDerivation && (
        <Button variant="link" className="how t-caption" onClick={() => onShowDerivation(value.derivation_id!)}>
          {t("value.how")}
        </Button>
      )}
    </div>
  );
}

/** 값 카드 묶음. primary 값이 있으면 그것만 먼저 보여주고 나머지는 "전체 값"으로 접는다. */
export function Values({
  values,
  groups,
  onShowDerivation,
}: {
  values: Value[];
  groups?: Record<string, string>;
  onShowDerivation?: (id: string) => void;
}) {
  const primary = values.filter((v) => v.primary);
  const head = primary.length ? primary : values.slice(0, 8);
  const rest = values.filter((v) => !head.includes(v));
  const byGroup = new Map<string, Value[]>();
  for (const v of rest) byGroup.set(v.group ?? "", [...(byGroup.get(v.group ?? "") ?? []), v]);
  return (
    <>
      <div className="cards">
        {head.map((v) => (
          <ValueCard key={v.key} value={v} onShowDerivation={onShowDerivation} />
        ))}
      </div>
      {rest.length > 0 && (
        <Fold title={t("stage.all_values", { n: values.length })} testId="fold-values">
          {[...byGroup.entries()].map(([group, list]) => (
            <div key={group}>
              {group && <h4 className="group-title t-body-strong">{groups?.[group] ?? group}</h4>}
              <div className="cards">
                {list.map((v) => (
                  <ValueCard key={v.key} value={v} onShowDerivation={onShowDerivation} />
                ))}
              </div>
            </div>
          ))}
        </Fold>
      )}
    </>
  );
}

function Formula({ tex }: { tex: string }) {
  const html = useMemo(() => {
    try {
      return katex.renderToString(tex, { displayMode: true, throwOnError: false, output: "htmlAndMathml" });
    } catch {
      return "";
    }
  }, [tex]);
  return html ? <div className="formula" dangerouslySetInnerHTML={{ __html: html }} /> : <pre className="formula mono">{tex}</pre>;
}

/** 계산 과정: 공식 → 넣은 값 → 풀이 → 결과 → 표준 조항. */
export function DerivationCard({ d, highlight }: { d: Derivation; highlight?: boolean }) {
  return (
    <article className="card derivation" id={`deriv-${d.id}`} data-highlight={highlight || undefined} data-testid={`derivation-${d.id}`}>
      <h4 className="t-body-strong">{d.title}</h4>
      <Formula tex={d.formula_tex} />
      {d.inputs.length > 0 && (
        <div className="table-wrap">
          <table className="data t-caption">
            <thead>
              <tr>
                <th scope="col">{t("derivation.symbol")}</th>
                <th scope="col" className="right">
                  {t("derivation.value")}
                </th>
                <th scope="col">{t("derivation.source")}</th>
              </tr>
            </thead>
            <tbody>
              {d.inputs.map((inp) => (
                <tr key={inp.symbol}>
                  <td className="mono">{inp.symbol}</td>
                  <td className="right num">
                    {fmtValue(inp.value)}
                    {inp.unit ? ` ${inp.unit}` : ""}
                  </td>
                  <td>{inp.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {d.steps.length > 0 && (
        <ol className="steps t-caption mono">
          {d.steps.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ol>
      )}
      <p className="result t-body-strong num">
        = {fmtValue(d.result.value)} {d.result.unit}
      </p>
      <p className="spec t-fine-print">{d.spec_ref}</p>
    </article>
  );
}

export function Derivations({ list, highlight }: { list: Derivation[]; highlight?: string | null }) {
  return (
    <div className="derivations">
      {list.map((d) => (
        <DerivationCard key={d.id} d={d} highlight={d.id === highlight} />
      ))}
    </div>
  );
}

const LEVEL_ICON = { error: "✕", warn: "!", info: "i" } as const;

/** 실패·주의 안내. 원인 후보를 가능성 순으로, 후보마다 버튼 하나. */
export function Diagnostics({
  list,
  onAction,
  disabled,
}: {
  list: Diagnostic[];
  onAction: (d: Diagnostic) => void;
  disabled?: boolean;
}) {
  if (!list.length) return null;
  // 참고(info)는 카드로 키우지 않고 한 줄 메모로 둔다. 버튼이 달린 참고는 카드로 보여준다.
  const notes = list.filter((d) => d.level === "info" && !d.action);
  const cards = list.filter((d) => !notes.includes(d));
  const ranked = cards.filter((d) => d.level === "error").length > 1;
  let rank = 0;
  return (
    <div className="diagnostics" role="group" aria-label={t("diagnostics.title")}>
      {notes.map((d, i) => (
        <p key={`n${i}`} className="t-caption muted center" data-testid={`note-${d.code}`}>
          <span aria-hidden="true">ⓘ </span>
          <span className="sr-only">{t("diagnostics.level.info")}: </span>
          {d.message_easy} {d.fix}
        </p>
      ))}
      {cards.map((d, i) => (
        <div key={`${d.code}-${i}`} className="card diagnostic" data-testid={`diagnostic-${d.code}`}>
          {ranked && d.level === "error" ? (
            <span className="rank t-caption-strong" aria-label={t("diagnostics.rank", { n: rank + 1 })}>
              {++rank}
            </span>
          ) : (
            <span className="level t-caption-strong" data-level={d.level}>
              <span aria-hidden="true">{LEVEL_ICON[d.level]}</span>
              <span className="sr-only">{t(`diagnostics.level.${d.level}`)}</span>
            </span>
          )}
          <div>
            <p className="t-body-strong">{d.message_easy}</p>
            <p className="t-caption muted">{d.fix}</p>
          </div>
          {d.action && (
            <Button variant="secondary" disabled={disabled} onClick={() => onAction(d)}>
              {d.action.label}
            </Button>
          )}
        </div>
      ))}
    </div>
  );
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** ASN.1 트리 (SIB1 전체 등). 가지는 펼침, 잎은 "이름: 값". */
export function TreeView({ data, depth = 0 }: { data: unknown; depth?: number }): ReactNode {
  if (Array.isArray(data)) {
    return (
      <ul className="tree t-caption">
        {data.map((item, i) => (
          <TreeNode key={i} name={`[${i}]`} value={item} depth={depth} />
        ))}
      </ul>
    );
  }
  if (isObject(data)) {
    return (
      <ul className="tree t-caption">
        {Object.entries(data).map(([k, v]) => (
          <TreeNode key={k} name={k} value={v} depth={depth} />
        ))}
      </ul>
    );
  }
  return <span className="mono t-caption">{fmtValue(data)}</span>;
}

function TreeNode({ name, value, depth }: { name: string; value: unknown; depth: number }) {
  if (Array.isArray(value) || isObject(value)) {
    return (
      <li>
        <details open={depth < 1 || undefined}>
          <summary className="mono">{name}</summary>
          <TreeView data={value} depth={depth + 1} />
        </details>
      </li>
    );
  }
  return (
    <li className="mono">
      <span className="k">{name}: </span>
      {fmtValue(value)}
    </li>
  );
}

/** 전문가 정보: 한 줄 요약, 표준 조항, 트리. */
export function ExpertInfo({ result }: { result: StageResult }) {
  return (
    <div className="stack">
      <p className="mono t-caption">{result.summary_expert}</p>
      <p className="t-caption muted">
        {t("stage.spec_refs")}: {result.spec_refs.join(" · ")}
      </p>
      {result.meta && (
        <p className="t-fine-print muted">
          {t("stage.engine")}: {result.meta.engine ?? "–"}
          {result.meta.duration_ms !== undefined ? ` · ${Math.round(result.meta.duration_ms)} ms` : ""}
        </p>
      )}
      {(result.trees ?? []).map((tree) => (
        <Fold key={tree.id} title={tree.title} testId={`tree-${tree.id}`}>
          <TreeView data={tree.data} />
        </Fold>
      ))}
    </div>
  );
}
