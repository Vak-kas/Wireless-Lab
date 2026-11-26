import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { AnalyzeDetail, AnalyzeFile, AnalyzeOverview } from "../api";
import { fakeApi, renderWithStore } from "../test-utils";
import { AnalyzeScreen } from "./AnalyzeScreen";

const FILE: AnalyzeFile = { path: "/d/key.sigmf-meta", name: "key.sigmf-data", datatype: "ci16_le", sample_rate_hz: 2e6, center_hz: 433.92e6, samples: 2e6, seconds: 1, bytes: 8e6 };
const GRID = { cols: 2, rows: 2, db: [[-80, -40], [-80, -80]] };
const OVER: AnalyzeOverview = {
  file: FILE,
  scan_s: 0.1,
  block_s: 1e-3,
  floor_db: -70,
  envelope: { peak_db: [-70, -20, -70], mean_db: [-75, -30, -75] },
  bursts: [
    { start_s: 0.1, seconds: 0.02, peak_db: -30, above_floor_db: 40 },
    { start_s: 0.5, seconds: 0.2, peak_db: -20, above_floor_db: 50 },
  ],
  spectrogram: GRID,
};
const detail = (over: Partial<AnalyzeDetail> = {}): AnalyzeDetail => ({
  start_s: 0.47, seconds: 0.26, samples: 520000, coarse: false, offset_hz: 0, bandwidth_hz: 0, fft: 1024, bin_hz: 1953.1, power_db: -25, peak_db: -20,
  spectrogram: GRID, spectrum: { mean_db: [-80, -40], max_db: [-70, -30], lo_hz: -1e6, hi_hz: 1e6 },
  occupied: { center_offset_hz: -100e3, lo_hz: -140e3, hi_hz: -60e3, bandwidth_hz: 80e3 },
  wave: { max: [0, 0.3], min: [0, 0.2], i: [0, 0.1], q: [0, 0.2], rate_hz: 2e6 },
  inst_freq_hz: [null, 36000], constellation: { i: [1], q: [0] },
  modulation: { kind: "unknown" },
  ...over,
});

test("파일을 열면 전체를 훑어 버스트를 보여 주고, 가장 센 것부터 자세히 본다. 신호를 고르면 그 주파수만 남겨 잰다", async () => {
  const a = fakeApi();
  a.analyzeFiles = vi.fn(async () => ({ folder: "/d", files: [FILE], can_choose: true }));
  a.analyzeOpen = vi.fn(async () => OVER);
  a.analyzeDetail = vi.fn(async (req: { bandwidth_hz: number }) =>
    req.bandwidth_hz > 0 ? detail({ bandwidth_hz: req.bandwidth_hz, modulation: { kind: "fsk", shortest_on_s: 0.00024, symbol_rate_hz: 4181, deviation_hz: 36227 } }) : detail(),
  );
  a.analyzeCut = vi.fn(async () => ({ meta_path: "/d/key-cut.sigmf-meta", data_path: "/d/key-cut.sigmf-data", bytes: 100, seconds: 0.26 }));
  renderWithStore(<AnalyzeScreen />, a);
  await userEvent.click(await screen.findByTestId("analyze-open-key.sigmf-data"));
  expect(a.analyzeOpen).toHaveBeenCalledWith({ path: "/d/key.sigmf-meta" });
  expect(await screen.findByTestId("analyze-overview")).toHaveTextContent("길이 1 s · 가운데 433.92 MHz · 2 MS/s");
  expect(screen.getByTestId("analyze-bursts")).toHaveTextContent("200 ms");
  // 가장 센 버스트(둘째)를 앞뒤 여유를 두고 본다
  await waitFor(() => expect(a.analyzeDetail).toHaveBeenCalledWith({ path: "/d/key.sigmf-meta", start_s: 0.47, seconds: 0.26, offset_hz: 0, bandwidth_hz: 0 }));
  const facts = await screen.findByTestId("analyze-facts");
  expect(facts).toHaveTextContent("433.82 MHz (-100 kHz)"); // 신호의 가운데: 녹화한 가운데에서 -100 kHz
  expect(facts).toHaveTextContent("80 kHz");
  // 이 신호 고르기: 잰 가운데와 폭(의 두 배)으로 걸러서 다시 본다
  await userEvent.click(screen.getByTestId("analyze-pick"));
  await waitFor(() => expect(a.analyzeDetail).toHaveBeenLastCalledWith({ path: "/d/key.sigmf-meta", start_s: 0.47, seconds: 0.26, offset_hz: -100e3, bandwidth_hz: 160e3 }));
  await waitFor(() => expect(screen.getByTestId("analyze-facts")).toHaveTextContent("주파수 바꾸기 (FSK)"));
  expect(screen.getByTestId("analyze-facts")).toHaveTextContent("±36.2 kHz");
  expect(screen.getByTestId("analyze-offset")).toHaveValue("-100");
  // 다른 버스트로 옮기고, 확대하고, 그 구간만 파일로 남긴다
  await userEvent.click(screen.getByTestId("analyze-burst-0"));
  await waitFor(() => expect(a.analyzeDetail).toHaveBeenLastCalledWith(expect.objectContaining({ start_s: expect.closeTo(0.097, 6), seconds: expect.closeTo(0.026, 6) })));
  await userEvent.click(screen.getByTestId("analyze-in"));
  await waitFor(() => expect(a.analyzeDetail).toHaveBeenLastCalledWith(expect.objectContaining({ start_s: expect.closeTo(0.1035, 6), seconds: expect.closeTo(0.013, 6) })));
  await userEvent.click(screen.getByTestId("analyze-cut"));
  expect(a.analyzeCut).toHaveBeenCalledWith({ path: "/d/key.sigmf-meta", start_s: expect.closeTo(0.1035, 6), seconds: expect.closeTo(0.013, 6) });
  expect(await screen.findByTestId("analyze-made")).toHaveTextContent("/d/key-cut.sigmf-data");
});

test("날것 파일은 샘플 속도를 함께 적어 열고, 녹화가 없으면 그렇다고 알려 준다", async () => {
  const a = fakeApi();
  a.analyzeFiles = vi.fn(async () => ({ folder: "/d", files: [], can_choose: false }));
  a.analyzeOpen = vi.fn(async () => ({ ...OVER, bursts: [] }));
  a.analyzeDetail = vi.fn(async () => detail({ coarse: true, modulation: undefined, inst_freq_hz: undefined, constellation: undefined }));
  renderWithStore(<AnalyzeScreen />, a);
  expect(await screen.findByText(/저장 폴더\(\/d\)에 녹화가 없습니다/)).toBeInTheDocument();
  expect(screen.queryByTestId("analyze-choose")).toBeNull(); // 파일 고르는 창을 띄울 수 없는 곳
  await userEvent.type(screen.getByTestId("analyze-path"), "/x/a.cfile");
  await userEvent.type(screen.getByTestId("analyze-rate"), "2");
  await userEvent.click(screen.getByTestId("analyze-open-path"));
  expect(a.analyzeOpen).toHaveBeenCalledWith({ path: "/x/a.cfile", sample_rate_hz: 2e6, center_hz: undefined });
  expect(await screen.findByText(/켜졌다 꺼지는 신호를 찾지 못했습니다/)).toBeInTheDocument();
  expect(await screen.findByText(/구간이 길어 세기만 보여 줍니다/)).toBeInTheDocument();
});
