import type { JobEvent, Session, Source, StageResult } from "./contracts.gen";

export type * from "./contracts.gen";

/** GET /api/pipeline 의 단계 하나. 문구는 서버(pipeline/stages.json)가 정한다. */
export interface StageDef {
  id: string;
  requires: string[];
  label: string;
  title: string;
  question?: string;
  intro?: string;
  analogy?: string;
  button?: string;
  locked_reason?: string;
  spec_refs?: string[];
  progress?: Record<string, string>;
  /** 값 묶음 키 → 소제목 */
  groups?: Record<string, string>;
}

export interface PipelineDef {
  stages: StageDef[];
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
}

export interface TrackData {
  running: boolean;
  interval_s: number;
  series: { key: string; label: string; unit: string }[];
  points: TrackPoint[];
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

export interface Api {
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
