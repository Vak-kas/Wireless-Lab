/* 자동 생성 파일. 고치지 말고 tools/gen_types.py 를 다시 돌릴 것. */

/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Scalar".
 */
export type Scalar = number | string | boolean | null;

/**
 * 서버와 화면이 주고받는 데이터 계약의 유일한 원본. Python(pydantic)과 TypeScript 타입은 tools/gen_types.py로 여기서 생성한다.
 */
export interface Contracts {
  stage_result?: StageResult;
  job_event?: JobEvent;
  session?: Session;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "StageResult".
 */
export interface StageResult {
  stage: string;
  status: "ok" | "partial" | "fail";
  summary_easy: string;
  summary_expert: string;
  values: Value[];
  derivations: Derivation[];
  plots: Plot[];
  diagnostics: Diagnostic[];
  next_inputs: {
    [k: string]: unknown;
  };
  spec_refs: string[];
  trees?: Tree[];
  meta?: ResultMeta;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Value".
 */
export interface Value {
  key: string;
  label: string;
  value: Scalar | Scalar[];
  unit: string;
  /**
   * decoded = 비트에서 바로 읽은 값(source 필수), measured = 신호에서 잰 값, derived = 다른 값으로 계산한 값(derivation_id 필수)
   */
  kind: "decoded" | "measured" | "derived";
  derivation_id?: string;
  source?: string;
  raw?: Scalar;
  group?: string;
  term?: string;
  primary?: boolean;
  note?: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Derivation".
 */
export interface Derivation {
  id: string;
  title: string;
  formula_tex: string;
  inputs: DerivationInput[];
  steps: string[];
  result: {
    value: Scalar;
    unit: string;
  };
  spec_ref: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "DerivationInput".
 */
export interface DerivationInput {
  symbol: string;
  value: Scalar;
  unit?: string;
  source: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Plot".
 */
export interface Plot {
  id: string;
  type:
    | "spectrum"
    | "waterfall"
    | "correlation"
    | "resource_grid"
    | "constellation"
    | "timeseries"
    | "table"
    | "sky_geometry";
  title: string;
  caption?: string;
  x?: PlotAxis;
  y?: PlotAxis;
  series?: PlotSeries[];
  grid?: PlotGrid;
  table?: PlotTable;
  sky?: PlotSky;
  annotations: PlotAnnotation[];
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "PlotAxis".
 */
export interface PlotAxis {
  label: string;
  unit?: string;
  min?: number;
  max?: number;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "PlotSeries".
 */
export interface PlotSeries {
  name: string;
  x?: number[];
  y?: number[];
  /**
   * 큰 배열은 여기 적힌 바이너리 엔드포인트(float32 LE, x와 y가 번갈아 나옴)에서 받는다.
   */
  data_ref?: string;
  role?: "primary" | "accent" | "muted";
  mode?: "line" | "points" | "bars" | "step";
}
/**
 * 행 = 주파수(부반송파 또는 RB), 열 = 시간(OFDM 심볼). values는 0~1로 정규화한 세기, categories는 칸마다 category_names의 번호(-1 = 없음).
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "PlotGrid".
 */
export interface PlotGrid {
  rows: number;
  cols: number;
  values: number[][];
  categories?: number[][];
  category_names?: string[];
  category_terms?: string[];
  row_label?: string;
  col_label?: string;
  row_start?: number;
  col_start?: number;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "PlotTable".
 */
export interface PlotTable {
  columns: {
    key: string;
    label: string;
    unit?: string;
    term?: string;
    align?: "left" | "right";
  }[];
  rows: {
    [k: string]: Scalar;
  }[];
  /**
   * 행을 고를 수 있는 표이면, 선택값으로 쓸 열의 key
   */
  select_key?: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "PlotSky".
 */
export interface PlotSky {
  tracks: {
    name: string;
    az_deg: number[];
    el_deg: number[];
    t_s?: number[];
  }[];
  markers: {
    name: string;
    az_deg: number;
    el_deg: number;
  }[];
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "PlotAnnotation".
 */
export interface PlotAnnotation {
  kind: "vline" | "hline" | "point" | "region" | "box";
  label: string;
  description?: string;
  term?: string;
  category?: number;
  x?: number;
  y?: number;
  x0?: number;
  x1?: number;
  y0?: number;
  y1?: number;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Diagnostic".
 */
export interface Diagnostic {
  level: "info" | "warn" | "error";
  code: string;
  message_easy: string;
  fix: string;
  action?: DiagnosticAction;
  detail?: string;
}
/**
 * 실패 화면의 버튼 하나. kind=rerun이면 params를 덮어써서 같은 단계를 다시 실행하고, kind=goto이면 target 단계/화면으로 이동한다.
 *
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "DiagnosticAction".
 */
export interface DiagnosticAction {
  label: string;
  kind: "rerun" | "goto";
  target?: string;
  params?: {
    [k: string]: unknown;
  };
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Tree".
 */
export interface Tree {
  id: string;
  title: string;
  data: unknown;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "ResultMeta".
 */
export interface ResultMeta {
  engine?: string;
  run_index?: number;
  created_at?: string;
  duration_ms?: number;
  capture?: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "JobEvent".
 */
export interface JobEvent {
  type: "job.started" | "job.progress" | "job.plot_partial" | "job.finished" | "job.failed";
  job_id: string;
  session_id: string;
  stage: string;
  ts: number;
  progress?: number;
  message?: string;
  plot?: Plot;
  result?: StageResult;
  error?: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Session".
 */
export interface Session {
  id: string;
  name: string;
  created_at: string;
  source: Source;
  engine: string;
  stages: StageState[];
  practice?: boolean;
  recording?: boolean;
  tracking?: boolean;
  selected_cell?: {
    [k: string]: unknown;
  };
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "Source".
 */
export interface Source {
  kind: "synthetic" | "file" | "device";
  /**
   * synthetic: 연습용 시나리오 id
   */
  scenario?: string;
  /**
   * file: .sigmf-meta 경로
   */
  path?: string;
  /**
   * file: 사용자가 테스트베드 녹화라고 표시했는지 (RA 관측 허용 조건)
   */
  testbed?: boolean;
  /**
   * device: 장비 식별자 (driver=...,serial=...)
   */
  device?: string;
  device_label?: string;
  center_freq_hz?: number;
  sample_rate_hz?: number;
  gain_db?: number;
  antenna?: string;
  external_clock?: boolean;
  band?: string;
}
/**
 * This interface was referenced by `Contracts`'s JSON-Schema
 * via the `definition` "StageState".
 */
export interface StageState {
  stage: string;
  state: "done" | "running" | "next" | "locked";
  last_status?: "ok" | "partial" | "fail";
  runs?: number;
  locked_reason?: string;
  job_id?: string;
}
