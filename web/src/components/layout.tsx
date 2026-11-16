import type { ReactNode } from "react";
import { t } from "../i18n";
import { go, href, type Route } from "../router";
import { useStore } from "../state/store";
import { Button, LockIcon } from "./ui";

const NAV: Route["screen"][] = ["start", "scan", "follow", "ntn", "track", "sessions", "settings"];

/** global-nav: 앱 이름, 화면 이동, 현재 세션과 입력 소스. */
export function GlobalNav({ route }: { route: Route }) {
  const { session, job } = useStore();
  return (
    <header className="global-nav t-nav-link">
      <a className="brand" href="#/">
        {t("app.name")}
      </a>
      <nav aria-label={t("nav.label")}>
        {NAV.map((screen) => {
          const needsSession = ["scan", "follow", "ntn", "track"].includes(screen);
          if (needsSession && !session) return null;
          return (
            <a key={screen} href={href(screen, session?.id)} aria-current={route.screen === screen ? "page" : undefined}>
              {t(`nav.${screen}`)}
            </a>
          );
        })}
      </nav>
      <div className="status" data-testid="nav-status">
        {session ? (
          <>
            <span>{session.name}</span>
            <span>· {t(`source.${session.source.kind}`)}</span>
            {session.recording && <span>· ● {t("nav.recording")}</span>}
            {job && <span className="spinner" aria-label={t("status.running")} />}
          </>
        ) : (
          <span>{t("nav.no_session")}</span>
        )}
      </div>
    </header>
  );
}

const STATE_ICON = { done: "✓", running: "◌", next: "●", locked: "" } as const;

/** 단계 사슬: 완료 / 진행 중 / 다음 차례 / 잠김(이유는 툴팁). */
export function Chain({ current }: { current?: string }) {
  const { pipeline, session, stageState } = useStore();
  if (!session) return null;
  const jump = (id: string) => {
    if (id === "scan") return go("scan", session.id);
    go("follow", session.id);
    setTimeout(() => document.getElementById(`stage-${id}`)?.scrollIntoView(), 50);
  };
  return (
    <ol className="chain t-caption" aria-label={t("chain.label")} data-testid="chain">
      {pipeline.stages.map((def) => {
        const st = stageState(def.id);
        const state = st?.state ?? "locked";
        const failed = st?.last_status === "fail";
        const word = failed ? t("chain.state.failed") : t(`chain.state.${state}`);
        return (
          <li key={def.id}>
            <button
              type="button"
              className="chain-step"
              data-state={state}
              data-failed={failed || undefined}
              data-testid={`chain-${def.id}`}
              aria-current={current === def.id ? "step" : undefined}
              aria-disabled={state === "locked" || undefined}
              title={state === "locked" ? (st?.locked_reason ?? def.locked_reason ?? word) : word}
              aria-label={`${def.label} — ${word}${state === "locked" && (st?.locked_reason ?? def.locked_reason) ? `. ${st?.locked_reason ?? def.locked_reason}` : ""}`}
              onClick={() => state !== "locked" && jump(def.id)}
            >
              <span className="icon" aria-hidden="true">
                {state === "running" ? <span className="spinner" /> : failed ? "✕" : state === "locked" ? <LockIcon /> : STATE_ICON[state]}
              </span>
              {def.label}
            </button>
          </li>
        );
      })}
    </ol>
  );
}

/** sub-nav-frosted: 화면 이름 + (가운데 내용) + 오른쪽 주 버튼. */
export function SubNav({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="sub-nav">
      <h1 className="title t-tagline">{title}</h1>
      <div className="grow">{children}</div>
      {action}
    </div>
  );
}

/** 사슬 오른쪽의 주 버튼: 다음 차례인 단계를 실행한다. */
export function NextStageButton() {
  const { session, job, nextStage, run, results } = useStore();
  if (!session) return null;
  const next = nextStage();
  if (job) {
    return (
      <Button disabled data-testid="next-stage">
        <span className="spinner" aria-hidden="true" /> {t("status.running")}
      </Button>
    );
  }
  if (!next) {
    return results.sib19?.status === "ok" ? (
      <Button data-testid="next-stage" onClick={() => go("ntn", session.id)}>
        {t("follow.open_ntn")}
      </Button>
    ) : null;
  }
  const onClick = () => {
    if (next.id === "scan") go("scan", session.id);
    else {
      go("follow", session.id);
      setTimeout(() => document.getElementById(`stage-${next.id}`)?.scrollIntoView(), 50);
    }
    void run(next.id);
  };
  return (
    <Button data-testid="next-stage" onClick={onClick}>
      {t("follow.next", { name: next.button ?? next.title })}
    </Button>
  );
}

/** floating-sticky-bar: 실행 중인 일과 진행 정도. 실행 중이거나 오류가 있을 때만 보인다. */
export function StickyBar() {
  const { job, error, clearError, stageDef } = useStore();
  if (!job && !error) return null;
  return (
    <div className="sticky-bar t-body" role="status" data-testid="sticky-bar">
      {job && <span className="progress" style={{ width: `${Math.round(job.progress * 100)}%` }} />}
      {job ? (
        <>
          <span className="spinner" aria-hidden="true" />
          <span className="message">
            <strong>{stageDef(job.stage)?.title}</strong> · {job.message || t("status.running")}
          </span>
          <span className="num t-caption">{Math.round(job.progress * 100)}%</span>
        </>
      ) : (
        <>
          <span className="message">
            <span aria-hidden="true">✕ </span>
            {t("status.error", { message: error ?? "" })}
          </span>
          <Button variant="utility" onClick={clearError}>
            {t("common.close")}
          </Button>
        </>
      )}
    </div>
  );
}

export function Tile({
  tone = "light",
  wide,
  children,
  id,
  className = "",
}: {
  tone?: "light" | "parchment" | "dark";
  wide?: boolean;
  children: ReactNode;
  id?: string;
  className?: string;
}) {
  return (
    <section className={`tile ${className}`} data-tone={tone} id={id}>
      <div className={`tile-inner ${wide ? "wide" : ""}`}>{children}</div>
    </section>
  );
}

export function TileHead({ eyebrow, title, lead, children }: { eyebrow?: ReactNode; title: ReactNode; lead?: ReactNode; children?: ReactNode }) {
  return (
    <div className="tile-head">
      {eyebrow && <p className="eyebrow t-caption-strong">{eyebrow}</p>}
      <h2 className="t-display-lg">{title}</h2>
      {lead && <p className="lead t-lead">{lead}</p>}
      {children && <div className="actions">{children}</div>}
    </div>
  );
}
