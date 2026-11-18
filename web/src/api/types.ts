import type { JobEvent, Session, Source, StageResult } from "./contracts.gen";

export type * from "./contracts.gen";

/** GET /api/pipeline 의 단계 하나. 문구는 서버(pipeline/stages.json)가 정한다. */
export interface StageDef {
  id: string;
  requires: string[];
  label: string;
  title: string;
  question?: string | null;
  intro?: string | null;
  analogy?: string | null;
  button?: string | null;
  locked_reason?: string | null;
  /** 이 입력 소스로는 쓸 수 없을 때 보여줄 문구 (테스트베드 전용 기능) */
  not_allowed?: string | null;
  spec_refs?: string[];
  progress?: Record<string, string>;
  /** 값 묶음 키 → 소제목 */
  groups?: Record<string, string>;
}

export interface PipelineDef {
  stages: StageDef[];
  /** 사슬 밖의 화면(예: ntn)에 쓰는 문구와 값 묶음 이름 */
  views?: StageDef[];
}

export type Glossary = Record<string, { name: string; short: string }>;

export interface Scenario {
  id: string;
  title: string;
  description: string;
  band?: string;
  ntn?: boolean;
  recommended?: boolean;
}

export interface DoctorCheck {
  id: string;
  label: string;
  status: "ok" | "warn" | "missing";
  detail: string;
  fix: string;
}

export interface DoctorReport {
  checks: DoctorCheck[];
  engines: Record<string, boolean>;
}

export interface DeviceInfo {
  id: string;
  label: string;
  driver: string;
  serial?: string;
  max_sample_rate_hz?: number;
  freq_min_hz?: number;
  freq_max_hz?: number;
  bits?: number;
  stages?: Record<string, "ok" | "limited" | "no">;
  note?: string;
  clock_ppm?: number;
  capability?: string;
}

export interface SurveyChannel {
  name: string;
  center_hz: number;
  width_hz: number;
  /** 채널 폭 가운데 받은 대역 안에 들어온 비율 */
  coverage: number;
  measured: boolean;
  mean_dbfs?: number;
  median_dbfs?: number;
  peak_dbfs?: number;
  clipped?: boolean;
}

export interface SurveyResult {
  device: string;
  plan: string;
  unit: string;
  dwell_s: number;
  channels: SurveyChannel[];
  fixed_tuning: boolean;
}

export interface SurveyPlan {
  id: string;
  available: boolean;
  channels: number;
  /** 누르는 단위로 고를 수 있는 폭 (MHz) */
  widths?: number[];
  /** 채널 맵의 칸. reachable=false 면 장비가 닿지 않는 주파수 */
  map?: { name: string; center_hz: number; width_hz: number; reachable: boolean }[];
  /** 폭(MHz) → 함께 쓰이는 채널 묶음들 */
  groups?: Record<string, string[][]>;
}

export interface TxStatus {
  /** 송신 기능이 이 설치에 있는가 */
  available: boolean;
  warning_version?: string;
  max_seconds?: number;
  max_gain_db?: number;
  default_gain_db?: number;
  sending?: boolean;
}

export interface TxRequest {
  device: string;
  center_hz: number;
  sample_rate_hz: number;
  gain_db: number;
  seconds: number;
  waveform: { kind: "tone"; offset_hz: number; amplitude: number } | { kind: "file"; path: string };
  /** 경고창에서 확인한 내용. 없으면 서버가 거부한다 */
  confirm?: { accepted: boolean; closed_setup: boolean; version: string; shown: { device: string; center_hz: number; gain_db: number; seconds: number } };
}

export interface BleDevice {
  address: string;
  address_type: "public" | "random";
  name: string;
  company: string;
  company_id: number | null;
  services: string[];
  pdu_types: string[];
  count: number;
  power_db: number;
  /** 잡힌 광고 채널 (37, 38, 39) */
  channel: number;
}

export interface BleScan {
  channel: number;
  packets: number;
  crc_failed: number;
  clipped: boolean;
  devices: BleDevice[];
  /** 특정 기기를 향한 패킷: 종류별 개수만 (내용은 풀지 않는다) */
  directed: Record<string, number>;
}

export interface WifiAp {
  ssid: string;
  bssid: string;
  /** 잡힌 채널 */
  seen_on: string;
  /** P20 채널 이름 (예: ch36) */
  primary: string;
  width_mhz: number | null;
  eht: boolean;
  count: number;
  power_db: number;
}

export interface WifiPpdu {
  /** 프레임 종류 (Non-HT, HT-MF, VHT, HE-SU, EHT-MU …). 송신 폭 등은 Wi-Fi 7(EHT) 프레임에만 있다 */
  format?: string;
  bandwidth_mhz?: number | null;
  uplink?: boolean;
  bss_color?: number | null;
  non_ofdma?: boolean;
  punctured?: number | null;
  power_db: number;
}

export interface MonitorChannel {
  name: string;
  center_hz: number;
  width_hz: number;
  measured: boolean;
  mean_dbfs?: number;
  median_dbfs?: number;
  peak_dbfs?: number | null;
  clipped?: boolean;
  baseline_dbfs?: number;
  rise_db?: number;
  /** 기준보다 rise_threshold_db 이상 올랐는가 */
  raised?: boolean;
  forced?: boolean;
  /** 자동 기준값까지 남은 시간 (초) */
  settle_s?: number;
  /** 이번 바퀴에 이 채널을 받지 못한 이유 */
  error?: string;
}

export interface MonitorState {
  id: string;
  device: string;
  plan: string;
  stat: "median_dbfs" | "mean_dbfs";
  auto: boolean;
  sweeps: number;
  sweep_s: number | null;
  channels: MonitorChannel[];
  baseline_note: "" | "manual" | "auto";
  has_baseline: boolean;
  forced: string[];
  raised: string[];
  smooth: number;
  rise_threshold_db: number;
}

export interface MonitorRequest {
  device: string;
  plan: string;
  channels?: string[];
  gain_db?: number;
  center_hz?: number;
  span_hz?: number;
  step_hz?: number;
}

export interface SurveyDevice {
  device: DeviceInfo;
  plans: SurveyPlan[];
  /** 장비가 직접 알려 준 값 (실제 장비일 때만) */
  reported?: {
    antennas?: string[];
    gain_range_db?: number[];
    sample_rate_range_hz?: number[];
    freq_range_hz?: number[];
    clock_sources?: string[];
    error?: string;
  };
  capture?: { center_freq_hz: number; sample_rate_hz: number; duration_s: number } | null;
}

export interface SpectrumView {
  device: string;
  fixed_tuning: boolean;
  /** 장비가 실제로 맞춘 값 (요청한 값과 조금 다를 수 있다) */
  center_hz: number;
  sample_rate_hz: number;
  bin_hz: number;
  dwell_s: number;
  freq_hz: number[];
  mean_db: number[];
  max_db: number[];
  total_dbfs: number;
  peak_dbfs: number;
  clipped: boolean;
  /** values[주파수 칸][시간 칸] = 0~1 */
  waterfall: { rows: number; cols: number; values: number[][]; col_ms: number; floor_db: number; ceil_db: number };
}

export interface SurveyRequest {
  device: string;
  plan: string;
  gain_db?: number;
  center_hz?: number;
  span_hz?: number;
  step_hz?: number;
}

export interface Settings {
  location: { lat: number; lon: number; alt_m: number };
  cfo_search_hz: number;
  cfo_search_ntn_hz: number;
  thresholds: Record<string, number>;
  device: { center_freq_hz?: number; sample_rate_hz?: number; gain_db?: number; antenna?: string; external_clock?: boolean };
  lang: "ko" | "en";
}

export interface NtnLocation {
  lat: number;
  lon: number;
  alt_m: number;
  t_offset_s?: number;
}

export interface TrackPoint {
  t_s: number;
  [key: string]: number | null;
}

export interface TrackChange {
  t_s: number;
  field: string;
  label: string;
  before: string;
  after: string;
  /** 궤도 전파로 설명되지 않는 변화 */
  anomaly?: boolean;
}

export interface TrackData {
  running: boolean;
  interval_s: number;
  series: { key: string; label: string; unit: string }[];
  points: TrackPoint[];
  /** 저장 파일·합성 신호를 되풀이해 읽는 중(측정값은 같고 궤도 계산값만 변함) */
  replay?: boolean;
}

export interface PhoneCell {
  registered: boolean;
  rat: string;
  arfcn?: number;
  band?: string;
  pci?: number;
  tac?: string;
  mcc?: string;
  mnc?: string;
  cell_id?: string;
  rsrp_dbm?: number;
  rsrq_db?: number;
  sinr_db?: number;
  timing_advance?: number;
  freq_mhz?: number;
}

export interface PhoneReport {
  status: "ok" | "no_adb" | "no_device" | "unparsed";
  device?: string;
  cells: PhoneCell[];
  raw?: string;
  limits: string[];
}

export interface OaiStatus {
  /** 테스트베드 파일이 있는가 (없으면 화면에 구역 자체를 보이지 않는다) */
  available: boolean;
  /** 지금 기록할 수 있는가. 아니면 reason 에 이유 */
  ready: boolean;
  running: boolean;
  reason: string;
  band?: string;
  location?: { lat: number; lon: number };
  max_seconds?: number;
}

export type OaiPhase = "idle" | "starting" | "waiting" | "recording" | "stopping";

export interface OaiRecording {
  meta_path: string;
  seconds: number;
  num_samples: number;
  size_mb: number;
  band: string;
  location: { lat: number; lon: number };
}

export interface Api {
  surveyDevice(id: string): Promise<SurveyDevice>;
  surveyRun(req: SurveyRequest): Promise<SurveyResult>;
  monitorStart(req: MonitorRequest): Promise<MonitorState>;
  monitorSweep(id: string): Promise<MonitorState>;
  monitorPatch(id: string, body: { auto?: boolean; stat?: string; baseline?: "save" | "clear" }): Promise<MonitorState>;
  monitorStop(id: string): Promise<void>;
  txStatus(): Promise<TxStatus>;
  txStart(req: TxRequest): Promise<{ seconds: number; stopped: boolean; underruns: number }>;
  txStop(): Promise<{ stopping: boolean }>;
  bleScan(req: { device: string; channel: number; gain_db?: number; seconds?: number }): Promise<BleScan>;
  wifiStatus(): Promise<{ available: boolean }>;
  wifiAps(req: { device: string; plan: string; channels: string[]; gain_db?: number }): Promise<{ aps: WifiAp[] }>;
  /** 모니터링 중: 채널 하나를 짧게 받아 프레임 종류·송신 폭·비콘을 함께 */
  wifiLive(req: { device: string; plan: string; channel: string; gain_db?: number }): Promise<{ channel: string; ppdus: WifiPpdu[]; aps: WifiAp[] }>;
  wifiUsig(req: { device: string; plan: string; channel: string; gain_db?: number }): Promise<{ ppdus: WifiPpdu[]; downlink: number }>;
  surveySpectrum(req: { device: string; center_hz?: number; bandwidth_hz?: number; gain_db?: number }): Promise<SpectrumView>;
  oaiStatus(): Promise<OaiStatus>;
  oaiRecord(seconds: number): Promise<OaiRecording>;
  /** 기록이 지금 어느 단계인지 (그림에 표시) */
  oaiProgress(): Promise<{ phase: OaiPhase }>;
  pipeline(): Promise<PipelineDef>;
  glossary(): Promise<Glossary>;
  scenarios(): Promise<Scenario[]>;
  doctor(quick?: boolean): Promise<DoctorReport>;
  devices(): Promise<DeviceInfo[]>;
  settings(): Promise<Settings>;
  saveSettings(s: Settings): Promise<Settings>;
  listSessions(): Promise<Session[]>;
  createSession(source: Source, opts?: { name?: string; practice?: boolean }): Promise<Session>;
  getSession(id: string): Promise<Session>;
  deleteSession(id: string): Promise<void>;
  result(id: string, stage: string): Promise<StageResult | null>;
  runStage(id: string, stage: string, params?: Record<string, unknown>): Promise<{ job_id: string }>;
  selectCell(id: string, cell: { gscn: number; pci: number }): Promise<Session>;
  subscribe(id: string, onEvent: (e: JobEvent) => void): () => void;
  ntn(id: string, loc: NtnLocation): Promise<StageResult>;
  trackStart(id: string, interval_s: number): Promise<void>;
  trackStop(id: string): Promise<void>;
  trackData(id: string): Promise<TrackData>;
  trackChanges(id: string): Promise<TrackChange[]>;
  trackCsvUrl(id: string): string;
  record(id: string, on: boolean): Promise<Session>;
  reportUrl(id: string): string;
  phoneCells(): Promise<PhoneReport>;
}
