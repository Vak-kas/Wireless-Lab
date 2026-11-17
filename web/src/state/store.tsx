import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api as defaultApi } from "../api";
import { getLang, setLang, type Lang } from "../i18n";
import type { Api, Glossary, JobEvent, PipelineDef, Session, Source, StageDef, StageResult, StageState } from "../api";

export interface Job {
  stage: string;
  progress: number;
  message: string;
}

export interface Store {
  api: Api;
  pipeline: PipelineDef;
  glossary: Glossary;
  ready: boolean;
  /** 화면 언어. 바꾸면 문구 전체가 다시 그려진다. */
  lang: Lang;
  setLanguage(lang: Lang): void;
  session: Session | null;
  results: Record<string, StageResult>;
  job: Job | null;
  error: string | null;
  stageDef(id: string): StageDef | undefined;
  stageState(id: string): StageState | undefined;
  nextStage(): StageDef | undefined;
  start(source: Source, opts?: { name?: string; practice?: boolean }): Promise<Session>;
  open(id: string): Promise<void>;
  close(): void;
  run(stage: string, params?: Record<string, unknown>): Promise<void>;
  selectCell(cell: { gscn: number; pci: number }): Promise<void>;
  setSession(s: Session): void;
  clearError(): void;
  /** 화면 아래 띠에 오류 문구를 띄운다. */
  fail(message: string): void;
}

const Ctx = createContext<Store | null>(null);

export function useStore(): Store {
  const s = useContext(Ctx);
  if (!s) throw new Error("StoreProvider가 없습니다");
  return s;
}

export function StoreProvider({ children, api = defaultApi }: { children: ReactNode; api?: Api }) {
  const [pipeline, setPipeline] = useState<PipelineDef>({ stages: [] });
  const [glossary, setGlossary] = useState<Glossary>({});
  const [ready, setReady] = useState(false);
  const [lang, setLangState] = useState<Lang>(getLang());
  const [session, setSession] = useState<Session | null>(null);
  const [results, setResults] = useState<Record<string, StageResult>>({});
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const unsubscribe = useRef<(() => void) | null>(null);
  const sessionId = useRef<string | null>(null);

  useEffect(() => {
    let alive = true;
    Promise.all([api.pipeline(), api.glossary(), api.settings().catch(() => null)])
      .then(([p, g, st]) => {
        if (!alive) return;
        setPipeline(p);
        setGlossary(g);
        if (st && (st.lang === "ko" || st.lang === "en")) {
          setLang(st.lang);
          setLangState(st.lang);
        }
        setReady(true);
      })
      .catch((e: unknown) => alive && setError(String(e instanceof Error ? e.message : e)));
    return () => {
      alive = false;
    };
  }, [api]);

  const refresh = useCallback(
    async (id: string) => {
      const s = await api.getSession(id);
      if (sessionId.current === id) setSession(s);
    },
    [api],
  );

  const onEvent = useCallback(
    (e: JobEvent) => {
      if (e.session_id !== sessionId.current) return;
      if (e.type === "job.started") setJob({ stage: e.stage, progress: 0, message: "" });
      else if (e.type === "job.progress")
        setJob({ stage: e.stage, progress: e.progress ?? 0, message: e.message ?? "" });
      else if (e.type === "job.finished") {
        const result = e.result;
        setJob(null);
        if (result) {
          // 다시 실행한 단계의 뒤 단계 결과는 서버에서도 지워진다. 화면도 맞춘다.
          setResults((prev) => {
            const order = pipeline.stages.map((s) => s.id);
            const at = order.indexOf(e.stage);
            const kept = Object.fromEntries(
              Object.entries(prev).filter(([k]) => at < 0 || order.indexOf(k) < at || !order.includes(k)),
            );
            return { ...kept, [e.stage]: result };
          });
        }
        void refresh(e.session_id);
      } else if (e.type === "job.failed") {
        setJob(null);
        setError(e.error ?? "job failed");
        void refresh(e.session_id);
      }
    },
    [pipeline, refresh],
  );

  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const attach = useCallback(
    (s: Session, loaded: Record<string, StageResult>) => {
      unsubscribe.current?.();
      sessionId.current = s.id;
      setSession(s);
      setResults(loaded);
      setJob(null);
      unsubscribe.current = api.subscribe(s.id, (e) => onEventRef.current(e));
    },
    [api],
  );

  const store = useMemo<Store>(() => {
    const stageDef = (id: string) => pipeline.stages.find((s) => s.id === id);
    const stageState = (id: string) => session?.stages.find((s) => s.stage === id);
    return {
      api,
      pipeline,
      glossary,
      ready,
      lang,
      setLanguage(next) {
        setLang(next);
        setLangState(next);
      },
      session,
      results,
      job,
      error,
      stageDef,
      stageState,
      nextStage: () => pipeline.stages.find((d) => stageState(d.id)?.state === "next"),
      async start(source, opts) {
        const s = await api.createSession(source, opts);
        attach(s, {});
        return s;
      },
      async open(id) {
        if (sessionId.current === id) return;
        const s = await api.getSession(id);
        const pairs = await Promise.all(
          [...pipeline.stages.map((d) => d.id)].map(async (stage) => [stage, await api.result(id, stage)] as const),
        );
        attach(s, Object.fromEntries(pairs.filter((p): p is readonly [string, StageResult] => p[1] !== null)));
      },
      close() {
        unsubscribe.current?.();
        unsubscribe.current = null;
        sessionId.current = null;
        setSession(null);
        setResults({});
        setJob(null);
      },
      async run(stage, params = {}) {
        if (!session) return;
        setError(null);
        setJob({ stage, progress: 0, message: "" });
        try {
          await api.runStage(session.id, stage, params);
        } catch (e) {
          setJob(null);
          setError(String(e instanceof Error ? e.message : e));
        }
      },
      async selectCell(cell) {
        if (!session) return;
        setSession(await api.selectCell(session.id, cell));
      },
      setSession,
      clearError: () => setError(null),
      fail: (message) => setError(message),
    };
  }, [api, pipeline, glossary, ready, lang, session, results, job, error, attach]);

  return <Ctx.Provider value={store}>{children}</Ctx.Provider>;
}
