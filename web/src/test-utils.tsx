import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import type { Api, JobEvent, PipelineDef, Session, StageResult } from "./api";
import { StoreProvider } from "./state/store";

/** 컴포넌트 테스트용 작은 파이프라인과 가짜 API. 서버 fixture와 무관하게 돈다. */
export const PIPELINE: PipelineDef = {
  stages: [
    { id: "scan", requires: [], label: "스캔", title: "대역 스캔", question: "주변에 어떤 기지국이 있나", intro: "훑어봅니다.", button: "스캔 시작", progress: { a: "받는 중" } },
    { id: "ssb", requires: ["scan"], label: "SSB", title: "SSB 동기", intro: "박자를 맞춥니다.", button: "SSB에 맞추기", locked_reason: "먼저 스캔을 해야 합니다.", progress: { a: "찾는 중" } },
  ],
};

export function result(stage: string, over: Partial<StageResult> = {}): StageResult {
  return {
    stage,
    status: "ok",
    summary_easy: `${stage} 성공`,
    summary_expert: `${stage} expert`,
    values: [],
    derivations: [],
    plots: [],
    diagnostics: [],
    next_inputs: {},
    spec_refs: ["TS 38.213 4.1"],
    ...over,
  };
}

export interface FakeApi extends Api {
  emit(e: Partial<JobEvent> & Pick<JobEvent, "type" | "stage">): void;
  runs: { stage: string; params: Record<string, unknown> }[];
  setStages(states: Session["stages"]): void;
}

export function fakeApi(results: Record<string, StageResult> = {}): FakeApi {
  let listener: ((e: JobEvent) => void) | null = null;
  let session: Session = {
    id: "s1",
    name: "연습",
    created_at: "2026-11-17T00:00:00Z",
    source: { kind: "synthetic", scenario: "x" },
    engine: "mock",
    stages: [
      { stage: "scan", state: "next" },
      { stage: "ssb", state: "locked", locked_reason: "먼저 스캔을 해야 합니다." },
    ],
  };
  const runs: FakeApi["runs"] = [];
  const no = () => Promise.reject(new Error("not used"));
  return {
    runs,
    emit: (e) => listener?.({ job_id: "j", session_id: "s1", ts: 0, ...e } as JobEvent),
    setStages: (stages) => {
      session = { ...session, stages };
    },
    pipeline: async () => PIPELINE,
    glossary: async () => ({ ssb: { name: "SSB", short: "기지국이 주기적으로 쏘는 신호등" } }),
    scenarios: async () => [{ id: "x", title: "위성 연습", description: "설명", recommended: true }],
    doctor: async () => ({ checks: [{ id: "python", label: "Python", status: "ok", detail: "3.12", fix: "" }], engines: { mock: true } }),
    devices: async () => [],
    settings: async () => ({ location: { lat: 36, lon: 127, alt_m: 50 }, cfo_search_hz: 10000, cfo_search_ntn_hz: 50000, thresholds: {}, device: {}, lang: "ko" }),
    saveSettings: async (s) => s,
    listSessions: async () => [session],
    createSession: async () => session,
    getSession: async () => session,
    deleteSession: async () => undefined,
    result: async (_id, stage) => results[stage] ?? null,
    runStage: async (_id, stage, params = {}) => {
      runs.push({ stage, params });
      return { job_id: "j" };
    },
    selectCell: async (_id, cell) => (session = { ...session, selected_cell: cell }),
    subscribe: (_id, fn) => {
      listener = fn;
      return () => (listener = null);
    },
    oaiStatus: async () => ({ available: false, ready: false, running: false, reason: "" }),
    oaiRecord: no,
    oaiProgress: async () => ({ phase: "idle" }),
    ntn: no,
    trackStart: no,
    trackStop: no,
    trackData: async () => ({ running: false, interval_s: 5, series: [], points: [] }),
    trackChanges: async () => [],
    trackCsvUrl: () => "#",
    record: async () => session,
    reportUrl: () => "#",
    phoneCells: no,
  };
}

export function renderWithStore(ui: ReactElement, api: Api = fakeApi()) {
  return render(<StoreProvider api={api}>{ui}</StoreProvider>);
}
