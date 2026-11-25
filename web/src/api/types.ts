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
  /** 알아봤지만 이 설치로는 쓸 수 없는 장비: 쓰려면 무엇이 필요한가 */
  needs?: "pro";
  /** 장비가 스스로 알려 준 능력 (범위는 value, 되는지 여부는 state) */
  abilities?: { id: string; state?: "yes" | "no" | "admin" | "unknown"; value?: string }[];
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

/** 컴퓨터의 무선 어댑터(Wi-Fi, 블루투스). SDR 과 달리 칩이 풀어 준 결과만 준다. */
export interface Adapter {
  id: string;
  kind: "wifi" | "bluetooth";
  /** 내장 / 외장(USB 등) / 운영체제가 알려 주지 않음 */
  attach: "builtin" | "external" | "unknown";
  label: string;
  detail: Record<string, string | number | boolean>;
  /**
   * 이 어댑터가 할 수 있는 일. value 가 있으면 값(대역, 폭, 규격), state 가 있으면 되는지 여부.
   * state: yes / no / admin(관리자 권한이 있어야 됨) / unknown(운영체제가 알려 주지 않음)
   */
  abilities?: { id: string; state?: "yes" | "no" | "admin" | "unknown"; value?: string }[];
  /** 지금 모드 (Linux 에서만 안다): managed = 일반(연결용), monitor = 모니터 */
  mode?: string | null;
  /**
   * 모드를 바꿀 수 있는가. how: direct(바로 됨) / pkexec(운영체제가 암호를 물음) / manual(명령을 직접 실행) / no(reason 참고)
   * to_monitor / to_managed: 그때 실행되는 명령
   */
  mode_switch?: { how: "direct" | "pkexec" | "manual" | "no"; reason?: string; to_monitor?: string[]; to_managed?: string[] };
}

export interface NearbyNetwork {
  /** 운영체제가 가리면 null (위치 권한이 없을 때) */
  ssid: string | null;
  bssid: string | null;
  rssi_dbm: number | null;
  channel: number | null;
  band: "2.4" | "5" | "6" | "";
  width_mhz: number | null;
  freq_mhz: number | null;
}

export interface WifiNearby {
  device: string;
  networks: NearbyNetwork[];
  /** 지금 이어져 있는 망의 채널과 세기 (알 수 있을 때만) */
  current: { channel: number; band: string; width_mhz: number | null; rssi_dbm: number; noise_dbm: number } | null;
  took_s: number;
  names_hidden: boolean;
  /** 이름이 가려졌을 때만: 위치 권한의 상태 (undetermined 면 물어볼 수 있다) */
  location?: "undetermined" | "authorized" | "denied" | "restricted" | "off" | "unknown" | null;
}

export interface NearbyBleDevice {
  address: string;
  name: string;
  rssi_dbm: number;
  company: string;
  company_ids: number[];
  services: number;
  count: number;
  tx_power_dbm?: number;
}

export interface BleNearby {
  device: string;
  seconds: number;
  devices: NearbyBleDevice[];
}

/** 기준 신호를 어디서 받나: 장비 안 / 기준 포트로 넣어 준 것 / 달려 있는 GPS 모듈 */
export type RefSource = "internal" | "external" | "gpsdo";

export interface DeviceReference {
  clock: RefSource;
  pps: RefSource;
}

/** 장비 찾기의 지금 상태 (찾는 중인지, 왜 못 찾았는지) */
export interface DeviceSearch {
  backends: {
    backend: string;
    searching: boolean;
    found: number;
    error: string;
    /** 꽂혀 있지만 다른 프로그램이 쓰는 중인 장비 */
    busy_devices?: string[];
    searching_for_s?: number | null;
    checked_s_ago?: number | null;
  }[];
}

export interface TxStatus {
  /** 송신 기능이 이 설치에 있는가 */
  available: boolean;
  warning_version?: string;
  max_seconds?: number;
  max_gain_db?: number;
  default_gain_db?: number;
  sending?: boolean;
  /** 만들 수 있는 표준 시험 신호와 그 샘플레이트 */
  standards?: {
    id: string;
    sample_rate_hz: number;
    /** builtin: 이 도구가 만든다 · plugin: 사용자가 넣은 생성기 · planned: 아직 생성기가 없는 칸 */
    source?: "builtin" | "plugin" | "planned";
    label?: string;
    description?: string;
    error?: string | null;
    /** 사용자 생성기가 프레임 바이트만 돌려주고, 전파 모양은 이 도구가 만드는 종류인가 */
    frames?: boolean;
  }[];
  /** 보내면서 받기의 한도 */
  receive?: { max_seconds: number; max_samples: number; skip_seconds: number; default_gain_db: number };
}

/** 보내면서 받은 신호를 보낸 것과 견준 결과 */
export interface TxReceived {
  device: string;
  gain_db: number;
  num_samples: number;
  seconds?: number;
  power_dbfs: number | null;
  peak: number;
  clipped: boolean;
  overflows: number;
  spectrum: { offset_hz: number[]; db: number[] };
  check: {
    kind: string;
    found: boolean;
    reason?: string;
    expected_offset_hz?: number;
    found_offset_hz?: number;
    above_floor_db?: number;
    match?: number;
    at_seconds?: number;
  };
  decoded?: { decoder: string; packets: number; crc_failed: number; found: boolean };
  /** 받은 구간이 남은 파일 (.sigmf-meta) */
  meta_path: string;
}

export interface TxResult {
  seconds: number;
  stopped: boolean;
  underruns: number;
  received?: TxReceived;
}

/** 함께 시작한 송신의 결과. aligned: "pps" 면 같은 시각 신호에 맞춰, "host" 면 컴퓨터가 맞춰(수 ms 까지 어긋날 수 있다) */
export interface TxGroupResult {
  id: string;
  aligned: "pps" | "host" | null;
  streams: { id: string; device: string; seconds: number; stopped: boolean; underruns: number }[];
}

export interface TxRequest {
  device: string;
  center_hz: number;
  sample_rate_hz: number;
  gain_db: number;
  seconds: number;
  waveform: { kind: "tone"; offset_hz: number; amplitude: number } | { kind: "standard"; standard: string } | { kind: "file"; path: string };
  /** 보내면서 받기: 받는 장비(보내는 장비와 같아도 된다), 수신 이득, 모을 길이 */
  receive?: { device: string; gain_db: number; seconds: number };
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

/** 계속 받기에 꽂을 수 있는 풀이 하나와, 못 꽂는다면 그 이유 */
export interface StreamTapInfo {
  name: string;
  ok: boolean;
  reason: string;
}

/** 풀이 하나의 상태와 결과. 풀이마다 채우는 칸이 다르다 */
export interface StreamTapState {
  /** 푼 조각 수 */
  done: number;
  /** 밀려서 풀지 못하고 건너뛴 조각 수 */
  skipped: number;
  error: string;
  took_s: number;
  /** spectrum */
  view?: Omit<SpectrumView, "device" | "fixed_tuning">;
  /** wifi, ble */
  channel?: string | number;
  aps?: WifiAp[];
  formats?: Record<string, number>;
  devices?: BleDevice[];
  directed?: Record<string, number>;
  crc_failed?: number;
  /** record */
  data_path?: string;
  bytes?: number;
  seconds?: number;
  gaps?: number;
  full?: boolean;
}

/** 계속 받기(끊김 없이 받으면서 푸는 것) 하나의 상태 */
export interface StreamState {
  id: string;
  device: string;
  running: boolean;
  error: string;
  center_hz: number;
  sample_rate_hz: number;
  segment_s: number;
  segments: number;
  seconds: number;
  /** 놓쳐서 0 으로 채운 샘플 수. 0 이면 받은 구간이 끊김 없이 이어진다 */
  lost_samples: number;
  overflows: number;
  /** false: 끊김 없이 받지 못하는 장비라 조각 사이에 틈이 있다 */
  continuous: boolean;
  taps: Record<string, StreamTapState>;
}

export interface StreamRequest {
  device: string;
  center_hz: number;
  bandwidth_hz: number;
  gain_db?: number;
  taps?: string[];
}

/** 파일로 저장한 수신 신호 */
export interface SavedCapture {
  meta_path: string;
  data_path: string;
  bytes: number;
  datatype: string;
  num_samples: number;
  seconds: number;
  center_hz: number;
  sample_rate_hz: number;
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
  /** 컴퓨터의 Wi-Fi·블루투스 어댑터 */
  adapters(): Promise<Adapter[]>;
  /** 어댑터로 주변 Wi-Fi 망을 한 번 찾는다 (연결하지 않는다) */
  adapterWifiScan(device: string): Promise<WifiNearby>;
  /** 어댑터로 주변 BLE 광고를 듣는다 (연결하지 않는다) */
  adapterBleScan(device: string, seconds?: number): Promise<BleNearby>;
  /** 장비가 쓰는 기준 신호(10 MHz 클럭, PPS). 없는 설치에서는 거절된다 */
  deviceReference(device: string): Promise<DeviceReference>;
  deviceSetReference(device: string, clock: RefSource, pps: RefSource): Promise<DeviceReference>;
  /** 장비를 잠깐 열어 고른 기준 신호에 잠겼는지 묻는다 (모르면 null) */
  deviceCheckReference(device: string): Promise<DeviceReference & { ref_locked: boolean | null; gps_locked: boolean | null }>;
  /** 운영체제의 위치 권한 창을 띄워 묻는다 (사용자가 고를 때까지 기다린다) */
  adapterAskLocation(): Promise<{ state: string }>;
  /** 운영체제의 권한 설정 창을 연다 (허용은 사용자가 그 창에서 한다) */
  adapterOpenSettings(pane: "location" | "bluetooth"): Promise<{ opened: string }>;
  /** Wi-Fi 어댑터의 모드를 바꾼다. confirmed 가 없으면 서버가 거부한다 */
  adapterSetMode(device: string, mode: "managed" | "monitor", confirmed: boolean): Promise<{ device: string; mode: string; changed: boolean }>;
  deviceSearch(): Promise<DeviceSearch>;
  deviceRescan(): Promise<DeviceSearch>;
  /** 장비 연결을 처음부터 다시 (MATLAB 을 닫았다가 새로 띄워 찾는다) */
  deviceReset(): Promise<DeviceSearch>;
  txStatus(): Promise<TxStatus>;
  txStart(req: TxRequest): Promise<TxResult>;
  /** 여러 장비의 송신을 같은 시각에 시작시킨다. 요청마다 경고 확인이 들어 있어야 한다 */
  txStartGroup(items: TxRequest[]): Promise<TxGroupResult>;
  txStop(): Promise<{ stopping: boolean }>;
  bleScan(req: { device: string; channel: number; gain_db?: number; seconds?: number }): Promise<BleScan>;
  wifiStatus(): Promise<{ available: boolean }>;
  wifiAps(req: { device: string; plan: string; channels: string[]; gain_db?: number }): Promise<{ aps: WifiAp[] }>;
  /** 모니터링 중: 채널 하나를 짧게 받아 프레임 종류·송신 폭·비콘을 함께 */
  wifiLive(req: { device: string; plan: string; channel: string; gain_db?: number }): Promise<{ channel: string; ppdus: WifiPpdu[]; aps: WifiAp[] }>;
  wifiUsig(req: { device: string; plan: string; channel: string; gain_db?: number }): Promise<{ ppdus: WifiPpdu[]; downlink: number }>;
  surveySpectrum(req: { device: string; center_hz?: number; bandwidth_hz?: number; gain_db?: number }): Promise<SpectrumView>;
  /** 계속 받기: 이 조건에 꽂을 수 있는 풀이들 */
  streamTaps(req: StreamRequest): Promise<{ taps: StreamTapInfo[] }>;
  streamStart(req: StreamRequest): Promise<StreamState>;
  streamState(id: string): Promise<StreamState>;
  streamStop(id: string): Promise<StreamState>;
  /** 그 대역을 받아 SigMF 파일로 남긴다 (서버의 sessions/saved/) */
  surveySave(req: { device: string; center_hz: number; bandwidth_hz: number; gain_db?: number; seconds: number }): Promise<SavedCapture>;
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
