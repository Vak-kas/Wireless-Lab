import type { Api, JobEvent, StageResult } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res
      .json()
      .then((j: { detail?: unknown }) => (typeof j.detail === "string" ? j.detail : ""))
      .catch(() => "");
    throw new ApiError(res.status, detail || res.statusText);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

/** 로컬 서버(FastAPI)와 통신하는 구현. */
export const httpApi: Api = {
  pipeline: () => call("/pipeline"),
  glossary: () => call("/glossary"),
  scenarios: () => call("/scenarios"),
  doctor: (quick = true) => call(`/doctor${quick ? "?quick=1" : ""}`),
  devices: () => call("/devices"),
  settings: () => call("/settings"),
  saveSettings: (s) => call("/settings", "PUT", s),
  listSessions: () => call("/sessions"),
  createSession: (source, opts = {}) => call("/sessions", "POST", { source, ...opts }),
  getSession: (id) => call(`/sessions/${id}`),
  deleteSession: (id) => call(`/sessions/${id}`, "DELETE"),
  result: (id, stage) =>
    call<StageResult>(`/sessions/${id}/results/${stage}`).catch((e: unknown) => {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    }),
  runStage: (id, stage, params = {}) => call(`/sessions/${id}/stages/${stage}/run`, "POST", { params }),
  selectCell: (id, cell) => call(`/sessions/${id}/select-cell`, "POST", cell),
  subscribe(id, onEvent) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    let closed = false;
    let ws: WebSocket | null = null;
    const open = () => {
      ws = new WebSocket(`${proto}://${location.host}/api/ws/sessions/${id}`);
      ws.onmessage = (m) => onEvent(JSON.parse(String(m.data)) as JobEvent);
      ws.onclose = () => {
        if (!closed) setTimeout(open, 1000);
      };
    };
    open();
    return () => {
      closed = true;
      ws?.close();
    };
  },
  ntn: (id, loc) => call(`/sessions/${id}/ntn`, "POST", loc),
  trackStart: (id, interval_s) => call(`/sessions/${id}/track/start`, "POST", { interval_s }),
  trackStop: (id) => call(`/sessions/${id}/track/stop`, "POST", {}),
  trackData: (id) => call(`/sessions/${id}/track/timeseries`),
  trackChanges: (id) => call(`/sessions/${id}/track/changes`),
  trackCsvUrl: (id) => `/api/sessions/${id}/track/timeseries.csv`,
  record: (id, on) => call(`/sessions/${id}/record`, "POST", { on }),
  reportUrl: (id) => `/api/sessions/${id}/report.html`,
  phoneCells: () => call("/phone/cells"),
  oaiStatus: () => call("/testbed/oai"),
  oaiRecord: (seconds) => call("/testbed/oai/record", "POST", { seconds }),
};
