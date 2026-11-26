import type {
  Api,
  DoctorReport,
  Glossary,
  JobEvent,
  PipelineDef,
  Scenario,
  Session,
  Settings,
  Source,
  StageResult,
  StageState,
  TrackData,
} from "./types";

/**
 * 서버 없이 화면만 돌리는 구현 (VITE_API=mock, 컴포넌트 테스트).
 * 데이터는 tools/gen_mock.py 가 내보낸 fixtures/ 의 JSON을 그대로 쓴다.
 */

const files = import.meta.glob("../mock/fixtures/**/*.json", { eager: true, import: "default" }) as Record<string, unknown>;

function fixture<T>(path: string): T | undefined {
  return files[`../mock/fixtures/${path}`] as T | undefined;
}

const STEP_MS = Number(import.meta.env.VITE_MOCK_STEP_MS ?? 350);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

interface MockSession {
  session: Session;
  results: Record<string, StageResult>;
  listeners: Set<(e: JobEvent) => void>;
  attempts: Record<string, number>;
  track: TrackData;
  timer?: ReturnType<typeof setInterval>;
}

const sessions = new Map<string, MockSession>();
let counter = 0;

let settings: Settings = {
  location: { lat: 36.35, lon: 127.38, alt_m: 60 },
  cfo_search_hz: 10000,
  cfo_search_ntn_hz: 50000,
  thresholds: { doppler_residual_hz: 1000, ta_mismatch_us: 50, altitude_min_km: 200, altitude_max_km: 40000 },
  device: {},
  lang: "ko",
};

function pipelineDef(): PipelineDef {
  return fixture<PipelineDef>("pipeline.json") ?? { stages: [] };
}

function stageStates(m: MockSession, running?: string): StageState[] {
  const defs = pipelineDef().stages;
  return defs.map((d) => {
    const r = m.results[d.id];
    const ready = d.requires.every((req) => m.results[req]?.status === "ok" || m.results[req]?.status === "partial");
    const state: StageState["state"] =
      running === d.id ? "running" : r && r.status !== "fail" ? "done" : ready ? "next" : "locked";
    return {
      stage: d.id,
      state,
      last_status: r?.status,
      runs: m.attempts[d.id] ?? 0,
      locked_reason: state === "locked" ? (d.locked_reason ?? undefined) : undefined,
    };
  });
}

function need(id: string): MockSession {
  const m = sessions.get(id);
  if (!m) throw new Error(`session ${id} not found`);
  return m;
}

function emit(m: MockSession, e: Omit<JobEvent, "ts" | "session_id">): void {
  const event = { ...e, ts: Date.now() / 1000, session_id: m.session.id } as JobEvent;
  m.listeners.forEach((fn) => fn(event));
}

function loadResult(m: MockSession, stage: string, params: Record<string, unknown>): StageResult | undefined {
  const scenario = m.session.source.scenario ?? "ntn-leo-n256";
  const first = fixture<StageResult>(`${scenario}/${stage}.json`);
  // 실패 예시 시나리오는 "다시 시도" 버튼(params가 붙음)을 누르면 정상 시나리오 결과로 넘어간다.
  if (first?.status === "fail" && Object.keys(params).length > 0) {
    const retry = fixture<StageResult>(`${scenario}/${stage}.retry.json`);
    if (retry) return retry;
  }
  return first;
}

export const mockApi: Api = {
  pipeline: async () => pipelineDef(),
  glossary: async () => fixture<Glossary>("glossary.json") ?? {},
  scenarios: async () => fixture<Scenario[]>("scenarios.json") ?? [],
  doctor: async () =>
    fixture<DoctorReport>("doctor.json") ?? {
      checks: [{ id: "mock", label: "mock", status: "ok", detail: "화면 전용 모드", fix: "" }],
      engines: { mock: true, matlab: false },
    },
  devices: async () => fixture("devices.json") ?? [],
  settings: async () => settings,
  saveSettings: async (s) => (settings = s),
  listSessions: async () => [...sessions.values()].map((m) => m.session).reverse(),
  async createSession(source: Source, opts = {}) {
    const id = `mock-${++counter}`;
    const m: MockSession = {
      session: {
        id,
        name: opts.name ?? `${source.scenario ?? source.kind} #${counter}`,
        created_at: new Date().toISOString(),
        source,
        engine: "mock",
        stages: [],
        practice: opts.practice ?? source.kind === "synthetic",
      },
      results: {},
      listeners: new Set(),
      attempts: {},
      track: { running: false, interval_s: 5, series: [], points: [], replay: true },
    };
    m.session.stages = stageStates(m);
    sessions.set(id, m);
    return m.session;
  },
  getSession: async (id) => need(id).session,
  deleteSession: async (id) => void sessions.delete(id),
  result: async (id, stage) => need(id).results[stage] ?? null,
  async runStage(id, stage, params = {}) {
    const m = need(id);
    const job_id = `job-${Date.now()}`;
    const def = pipelineDef().stages.find((s) => s.id === stage);
    m.attempts[stage] = (m.attempts[stage] ?? 0) + 1;
    // 이 단계를 다시 돌리면 뒤 단계 결과는 더 이상 맞지 않는다.
    const order = pipelineDef().stages.map((s) => s.id);
    if (order.includes(stage)) for (const later of order.slice(order.indexOf(stage))) delete m.results[later];
    m.session = { ...m.session, stages: stageStates(m, stage) };
    void (async () => {
      emit(m, { type: "job.started", job_id, stage });
      const steps = Object.values(def?.progress ?? { run: "…" });
      for (let i = 0; i < steps.length; i++) {
        emit(m, { type: "job.progress", job_id, stage, progress: i / steps.length, message: steps[i] });
        await sleep(STEP_MS);
      }
      const result = loadResult(m, stage, params);
      if (!result) {
        m.session = { ...m.session, stages: stageStates(m) };
        emit(m, { type: "job.failed", job_id, stage, error: `fixture 없음: ${stage}` });
        return;
      }
      m.results[stage] = result;
      m.session = { ...m.session, stages: stageStates(m) };
      emit(m, { type: "job.finished", job_id, stage, progress: 1, result });
    })();
    return { job_id };
  },
  async selectCell(id, cell) {
    const m = need(id);
    m.session = { ...m.session, selected_cell: cell };
    return m.session;
  },
  subscribe(id, onEvent) {
    const m = need(id);
    m.listeners.add(onEvent);
    return () => m.listeners.delete(onEvent);
  },
  async ntn(id) {
    const m = need(id);
    const r = fixture<StageResult>(`${m.session.source.scenario ?? "ntn-leo-n256"}/ntn.json`);
    if (!r) throw new Error("ntn fixture 없음");
    return r;
  },
  async trackStart(id, interval_s) {
    const m = need(id);
    const data = fixture<TrackData>(`${m.session.source.scenario ?? "ntn-leo-n256"}/track.json`);
    const all = data?.points ?? [];
    m.track = { running: true, interval_s, series: data?.series ?? [], points: all.slice(0, Math.min(3, all.length)), replay: true };
    m.session = { ...m.session, tracking: true };
    m.timer = setInterval(() => {
      if (m.track.points.length < all.length) m.track.points = all.slice(0, m.track.points.length + 1);
    }, STEP_MS);
  },
  async trackStop(id) {
    const m = need(id);
    clearInterval(m.timer);
    m.track = { ...m.track, running: false };
    m.session = { ...m.session, tracking: false };
  },
  trackData: async (id) => need(id).track,
  trackChanges: async (id) => fixture(`${need(id).session.source.scenario ?? "ntn-leo-n256"}/track-changes.json`) ?? [],
  oaiStatus: async () => ({ available: false, ready: false, running: false, reason: "" }),
  oaiRecord: async () => {
    throw new Error("mock");
  },
  oaiProgress: async () => ({ phase: "idle" }),
  surveyDevice: async (id) => ({
    device: { id, label: id, driver: "simulated" },
    plans: [{ id: "capture", available: true, channels: 0 }],
    capture: { center_freq_hz: 2e9, sample_rate_hz: 15.36e6, duration_s: 0.1 },
  }),
  monitorStart: async () => {
    throw new Error("mock");
  },
  monitorSweep: async () => {
    throw new Error("mock");
  },
  monitorPatch: async () => {
    throw new Error("mock");
  },
  monitorStop: async () => undefined,
  adapters: async () => [],
  adapterWifiScan: async () => {
    throw new Error("mock");
  },
  deviceReference: async () => ({ clock: "internal", pps: "internal" }),
  deviceSetReference: async (_d, clock, pps) => ({ clock, pps }),
  deviceCheckReference: async () => ({ clock: "internal", pps: "internal", ref_locked: null, gps_locked: null }),
  adapterAskLocation: async () => ({ state: "unknown" }),
  adapterOpenSettings: async (pane) => ({ opened: pane }),
  adapterSetMode: async () => {
    throw new Error("mock");
  },
  adapterBleScan: async () => {
    throw new Error("mock");
  },
  deviceSearch: async () => ({ backends: [] }),
  deviceRescan: async () => ({ backends: [] }),
  deviceReset: async () => ({ backends: [] }),
  txStatus: async () => ({ available: false }),
  txPlugins: async () => ({ folder: "", files: [], templates: [], can_reveal: false }),
  txPluginNew: async () => {
    throw new Error("mock");
  },
  txPluginReveal: async () => ({ ok: true }),
  txStart: async () => {
    throw new Error("mock");
  },
  txStartGroup: async () => {
    throw new Error("mock");
  },
  txStop: async () => ({ stopping: false }),
  bleScan: async () => {
    throw new Error("mock");
  },
  wifiStatus: async () => ({ available: false }),
  wifiAps: async () => {
    throw new Error("mock");
  },
  wifiLive: async () => {
    throw new Error("mock");
  },
  wifiUsig: async () => {
    throw new Error("mock");
  },
  streamTaps: async () => {
    throw new Error("mock");
  },
  streamStart: async () => {
    throw new Error("mock");
  },
  streamState: async () => {
    throw new Error("mock");
  },
  streamRows: async () => {
    throw new Error("mock");
  },
  streamTap: async () => {
    throw new Error("mock");
  },
  streamStop: async () => {
    throw new Error("mock");
  },
  analyzeFiles: async () => ({ folder: "", files: [], can_choose: false }),
  analyzeChoose: async () => ({ path: null }),
  analyzeOpen: async () => {
    throw new Error("mock");
  },
  analyzeDetail: async () => {
    throw new Error("mock");
  },
  analyzeDemod: async () => {
    throw new Error("mock");
  },
  analyzeCompare: async () => {
    throw new Error("mock");
  },
  analyzeCut: async () => {
    throw new Error("mock");
  },
  bandsLoad: async () => ({ bands: [] }),
  bandsSave: async (bands) => ({ bands }),
  savedState: async () => {
    throw new Error("mock");
  },
  savedFolder: async () => {
    throw new Error("mock");
  },
  savedChoose: async () => {
    throw new Error("mock");
  },
  savedReveal: async () => {
    throw new Error("mock");
  },
  savedExport: async () => {
    throw new Error("mock");
  },
  surveySave: async () => {
    throw new Error("mock");
  },
  surveySpectrum: async (req) => {
    const n = 256;
    const mean = Array.from({ length: n }, (_, i) => -80 + (i > 90 && i < 170 ? 28 : 0) + Math.random() * 2);
    return {
      device: req.device,
      fixed_tuning: true,
      center_hz: 2e9,
      sample_rate_hz: 15.36e6,
      bin_hz: 60e3,
      dwell_s: 0.02,
      freq_hz: Array.from({ length: n }, (_, i) => 2e9 - 7.68e6 + (i + 0.5) * 60e3),
      mean_db: mean,
      max_db: mean.map((v) => v + 6),
      total_dbfs: -30,
      peak_dbfs: -12,
      clipped: false,
      waterfall: { rows: 64, cols: 20, values: Array.from({ length: 64 }, (_, r) => Array.from({ length: 20 }, () => (r > 22 && r < 42 ? 0.9 : 0.1))), col_ms: 1, floor_db: -90, ceil_db: -40 },
    };
  },
  surveyRun: async (req) => ({
    device: req.device,
    plan: req.plan,
    unit: "dBFS",
    dwell_s: 0.02,
    fixed_tuning: true,
    channels: Array.from({ length: 16 }, (_, i) => {
      const center = 2e9 - 7.2e6 + i * 0.96e6;
      const p = -70 + (i > 4 && i < 11 ? 30 : 0) + Math.random();
      return { name: (center / 1e6).toFixed(2), center_hz: center, width_hz: 0.96e6, coverage: 1, measured: true, mean_dbfs: p, median_dbfs: p - 0.2, peak_dbfs: -18, clipped: false };
    }),
  }),
  trackCsvUrl: () => "#",
  async record(id, on) {
    const m = need(id);
    m.session = { ...m.session, recording: on };
    return m.session;
  },
  reportUrl: () => "#",
  phoneCells: async () =>
    fixture("phone.json") ?? { status: "no_device", cells: [], limits: [] },
};
