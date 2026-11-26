import type { Adapter, Api, JobEvent, StageResult } from "./types";

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
  surveyDevice: (id) => call(`/survey/device?id=${encodeURIComponent(id)}`),
  surveyRun: (req) => call("/survey/run", "POST", req),
  monitorStart: (req) => call("/monitor", "POST", req),
  monitorSweep: (id) => call(`/monitor/${id}/sweep`, "POST", {}),
  monitorPatch: (id, body) => call(`/monitor/${id}`, "PATCH", body),
  monitorStop: (id) => call(`/monitor/${id}`, "DELETE"),
  adapters: () => call<{ adapters: Adapter[] }>("/adapters").then((r) => r.adapters),
  adapterWifiScan: (device) => call("/adapters/wifi/scan", "POST", { device }),
  deviceReference: (device) => call(`/devices/reference?id=${encodeURIComponent(device)}`),
  deviceSetReference: (device, clock, pps) => call("/devices/reference", "PUT", { device, clock, pps }),
  deviceCheckReference: (device) => call("/devices/reference/check", "POST", { device }),
  adapterAskLocation: () => call("/adapters/permission/location", "POST", {}),
  adapterOpenSettings: (pane) => call("/adapters/settings", "POST", { pane }),
  adapterSetMode: (device, mode, confirmed) => call("/adapters/wifi/mode", "POST", { device, mode, confirmed }),
  adapterBleScan: (device, seconds = 4) => call("/adapters/bluetooth/scan", "POST", { device, seconds }),
  deviceSearch: () => call("/devices/status"),
  deviceRescan: () => call("/devices/rescan", "POST", {}),
  deviceReset: () => call("/devices/reset", "POST", {}),
  txStatus: () => call("/tx"),
  txPlugins: () => call("/tx/plugins"),
  txPluginNew: (template, name) => call("/tx/plugins/new", "POST", { template, name }),
  txPluginReveal: (name) => call("/tx/plugins/reveal", "POST", { name: name ?? null }),
  txStart: (req) => call("/tx/start", "POST", req),
  txStartGroup: (items) => call("/tx/start-group", "POST", { items }),
  txStop: () => call("/tx/stop", "POST", {}),
  bleScan: (req) => call("/ble/scan", "POST", req),
  wifiStatus: () => call("/wifi"),
  wifiAps: (req) => call("/wifi/aps", "POST", req),
  wifiUsig: (req) => call("/wifi/usig", "POST", req),
  wifiLive: (req) => call("/wifi/live", "POST", req),
  surveySpectrum: (req) => call("/survey/spectrum", "POST", req),
  analyzeFiles: () => call("/analyze/files", "GET"),
  analyzeChoose: () => call("/analyze/choose", "POST", {}),
  analyzeOpen: (src) => call("/analyze/open", "POST", src),
  analyzeDetail: (req) => call("/analyze/detail", "POST", req),
  analyzeDemod: (req) => call("/analyze/demod", "POST", req),
  analyzeCompare: (req) => call("/analyze/compare", "POST", req),
  analyzeCut: (req) => call("/analyze/cut", "POST", req),
  bandsLoad: () => call("/bands", "GET"),
  bandsSave: (bands) => call("/bands", "POST", { bands }),
  savedState: () => call("/saved", "GET"),
  relayState: () => call("/relay", "GET"),
  relayTarget: (body) => call("/relay/target", "PUT", body),
  relayForget: () => call("/relay/target", "DELETE"),
  relayCheck: () => call("/relay/check", "POST", {}),
  relayFile: (meta_path, loop) => call("/relay/file", "POST", { meta_path, loop }),
  relayFileStop: () => call("/relay/file", "DELETE"),
  relayRecvTarget: (body) => call("/relay/recv/target", "PUT", body),
  relayRecvForget: () => call("/relay/recv/target", "DELETE"),
  relayRecvStart: (record) => call("/relay/recv", "POST", { record }),
  relayRecvStop: () => call("/relay/recv", "DELETE"),
  savedFolder: (path) => call("/saved/folder", "POST", { path }),
  savedChoose: () => call("/saved/choose", "POST", {}),
  savedReveal: (path) => call("/saved/reveal", "POST", { path }),
  savedExport: (meta_path, format) => call("/saved/export", "POST", { meta_path, format }),
  surveySave: (req) => call("/survey/save", "POST", req),
  streamTaps: (req) => call("/streams/taps", "POST", req),
  streamStart: (req) => call("/streams", "POST", req),
  streamState: (id) => call(`/streams/${id}`, "GET"),
  streamStop: (id) => call(`/streams/${id}`, "DELETE"),
  streamRows: (id, after) => call(`/streams/${id}/rows?after=${after}`, "GET"),
  streamTap: (id, name, on) => call(`/streams/${id}/taps`, "POST", { name, on }),
  oaiStatus: () => call("/testbed/oai"),
  oaiRecord: (seconds) => call("/testbed/oai/record", "POST", { seconds }),
  oaiProgress: () => call("/testbed/oai/progress"),
};
