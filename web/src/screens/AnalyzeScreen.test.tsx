import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { AnalyzeCompare, AnalyzeDetail, AnalyzeFile, AnalyzeOverview } from "../api";
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
  // 비트로 풀기: 고른 신호를 0·1 과 HEX 로. 되풀이된 패킷은 그렇다고 알려 준다
  a.analyzeDemod = vi.fn(async () => ({ kind: "fsk" as const, guessed: "fsk", symbol_s: 0.00025, symbol_rate_hz: 4000, fit: 0.97, packets_total: 1,
    packets: [{ start_s: 0.5, seconds: 0.2, bits: "0101010111110000", hex: "55F0", repeats: 2, manchester: { bits: "00001100", hex: "0C" } }] }));
  await userEvent.click(screen.getByTestId("analyze-bits-go"));
  expect(a.analyzeDemod).toHaveBeenCalledWith({ path: "/d/key.sigmf-meta", start_s: 0.47, seconds: 0.26, offset_hz: -100e3, bandwidth_hz: 160e3, kind: "auto", symbol_rate_hz: undefined });
  const packet = await screen.findByTestId("analyze-packet-0");
  expect(packet).toHaveTextContent("01010101 11110000");
  expect(packet).toHaveTextContent("HEX 55 F0");
  expect(packet).toHaveTextContent("같은 내용이 2번");
  expect(packet).toHaveTextContent("맨체스터 부호로 보입니다");
  expect(screen.getByTestId("analyze-bits")).toHaveTextContent("심볼 속도 4000 /s");
  expect(screen.getByTestId("analyze-bits")).toHaveTextContent("박자 맞음 97%");
  // 다른 버스트로 옮기고, 확대하고, 그 구간만 파일로 남긴다
  await userEvent.click(screen.getByTestId("analyze-burst-0"));
  await waitFor(() => expect(screen.queryByTestId("analyze-bits")).toBeNull()); // 구간이 바뀌면 전에 푼 비트는 치운다
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

test("수신 화면에서 녹화하고 넘어오면 그 파일을 바로 연다", async () => {
  sessionStorage.setItem("nrtrail.analyze.next", "/d/k.sigmf-meta");
  const a = fakeApi();
  a.analyzeOpen = vi.fn(async () => ({ ...OVER, bursts: [] }));
  a.analyzeDetail = vi.fn(async () => detail());
  renderWithStore(<AnalyzeScreen />, a);
  await waitFor(() => expect(a.analyzeOpen).toHaveBeenCalledWith({ path: "/d/k.sigmf-meta" }));
  expect(sessionStorage.getItem("nrtrail.analyze.next")).toBeNull();
});

test("버스트 전체 비교: 신호(반송파·편이·심볼 속도)와 데이터(줄 맞춘 비트, 고정 칸·바뀌는 칸, 다른 자리 수)를 따로 보여 준다", async () => {
  const burst = (index: number, payload: string, carrier: number) => ({
    index, start_s: 0.1 + index, seconds: 0.27, peak_db: -14, power_db: -16.4, carrier_offset_hz: carrier, deviation_hz: 37119, symbol_rate_hz: 4004.85, fit: 1,
    bits: "1010" + payload, hex: "A", preamble: { start: 0, length: 642 }, payload, payload_hex: "9", repeat_period: null,
    manchester: { bits: payload.slice(0, 4), errors: 1, shift: 0, broken_at: [3] },
  });
  const cols = { length: 8, mask: "====xxxx", same: 4, varies: 4, groups: [[0], [1]], distance: [[0, 3], [3, 0]],
    fields: [{ start: 0, length: 4, kind: "same" as const, bits: "1001", hex: "9" }, { start: 4, length: 4, kind: "varies" as const, distinct: 2, step: 1 }] };
  const result: AnalyzeCompare = {
    kind: "fsk", offset_hz: -99705, bandwidth_hz: 339843, center_hz: 434.016e6, total_bursts: 2, decoded: [0, 1],
    bursts: [burst(0, "10010101", -99397), burst(1, "10010110", -99415)],
    symbols: cols, manchester: { ...cols, length: 4, mask: "===x", same: 3, varies: 1, rows: [0, 1], fields: [{ start: 0, length: 3, kind: "same", bits: "100", hex: "8" }, { start: 3, length: 1, kind: "varies", distinct: 2 }] },
    signal: { carrier_offset_hz: { mean: -99406, min: -99415, max: -99397, std: 9 }, deviation_hz: { mean: 37119, min: 37113, max: 37126, std: 4 }, symbol_rate_hz: { mean: 4004.85, min: 4003.35, max: 4006.84, std: 0.8 },
      power_db: { mean: -16.4, min: -17.5, max: -15, std: 0.6 }, seconds: { mean: 0.27, min: 0.267, max: 0.274, std: 0.002 } },
    traces: { per_symbol: 8, before: 24, after: 104, lines: [[0, 1, -1], [0, 1, 1]] },
    frames: null, repeats_within: null, second: null,
    advice: { carrier_hz: 433.9166e6, occupied_hz: 78243, center_hz: 434.167e6, bandwidth_hz: 1e6, samples_per_symbol: 249.7, mb_per_s: 4, now_bandwidth_hz: 29e6, now_mb_per_s: 116, peak_db: -13.2, gain: "ok" },
  };
  const a = fakeApi();
  a.analyzeFiles = vi.fn(async () => ({ folder: "/d", files: [FILE], can_choose: true }));
  a.analyzeOpen = vi.fn(async () => OVER);
  a.analyzeDetail = vi.fn(async () => detail());
  a.analyzeCompare = vi.fn(async () => result);
  renderWithStore(<AnalyzeScreen />, a);
  await userEvent.click(await screen.findByTestId("analyze-open-key.sigmf-data"));
  await userEvent.click(await screen.findByTestId("compare-go"));
  // 고른 주파수가 없으면 서버가 가장 센 버스트에서 잰 값을 쓴다(폭 0 으로 묻는다)
  expect(a.analyzeCompare).toHaveBeenCalledWith({ path: "/d/key.sigmf-meta", offset_hz: 0, bandwidth_hz: 0, kind: "auto", symbol_rate_hz: undefined });
  expect(await screen.findByTestId("compare-summary")).toHaveTextContent("버스트 2개 가운데 2개를 풀었습니다 (주파수 바꾸기 (FSK)). 서로 다른 내용은 2가지입니다. 누를 때마다 내용이 전부 다릅니다.");
  // 신호: 반송파의 절대 주파수와 흩어진 정도, 버스트마다 평균과의 차
  expect(screen.getByTestId("compare-spread")).toHaveTextContent("433.916594 MHz · 가장 낮은 것과 높은 것의 차 18 Hz");
  expect(screen.getByTestId("compare-table")).toHaveTextContent("+9 Hz");
  expect(screen.getByTestId("compare-table")).toHaveTextContent("±37.119 kHz");
  // 데이터: 모두 풀리면 맨체스터를 푼 것부터 보여 주고, 심볼로 바꿔 볼 수 있다
  expect(screen.getByTestId("compare-layer-manchester")).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("compare-fields")).toHaveTextContent("100 (HEX 8)");
  expect(screen.getByTestId("compare-broken")).toHaveTextContent("규칙이 깨진 자리(첫 버스트): 3");
  await userEvent.click(screen.getByTestId("compare-layer-symbols"));
  const grid = screen.getByTestId("compare-grid");
  expect(grid.querySelectorAll(".an-vary")).toHaveLength(2); // 줄마다 바뀌는 칸 하나
  expect(grid).toHaveTextContent("10010101");
  expect(screen.getByTestId("compare-fields")).toHaveTextContent("서로 다른 값 2가지 (버스트 2개) · 누를 때마다 1씩 달라짐 · 매번 다름");
  expect(screen.getByTestId("compare-distance")).toHaveTextContent("3");
  expect(screen.queryByTestId("compare-frames")).toBeNull();
  // 다음 녹화 권장: 가운데와 폭, 그리고 그 값을 볼 곳으로 저장
  const advice = screen.getByTestId("compare-advice");
  expect(advice).toHaveTextContent("가운데 주파수 434.167 MHz, 대역폭 1 MHz 로 두세요.");
  expect(advice).toHaveTextContent("1초에 약 4 MB 입니다(지금 녹화는 폭 29 MHz, 1초에 약 116 MB)");
  expect(advice).toHaveTextContent("세기는 알맞습니다(가장 셀 때 -13.2 dBFS)");
  a.bandsSave = vi.fn(async (bands) => ({ bands }));
  await userEvent.click(screen.getByTestId("compare-advice-keep"));
  await waitFor(() => expect(a.bandsSave).toHaveBeenCalledWith([expect.objectContaining({ name: "433.917 분석용", center_mhz: 434.167, width_mhz: 1 })]));
  // 섹션 접기: 제목을 누르면 그 섹션이 접히고, 다시 누르면 펴진다
  expect(screen.getByTestId("part-c-distance")).not.toHaveAttribute("data-folded");
  await userEvent.click(screen.getByTestId("fold-c-distance"));
  expect(screen.getByTestId("part-c-distance")).toHaveAttribute("data-folded", "true");
  expect(screen.getByTestId("fold-c-distance")).toHaveAttribute("aria-expanded", "false");
  await userEvent.click(screen.getByTestId("fold-c-distance"));
  expect(screen.getByTestId("part-c-distance")).not.toHaveAttribute("data-folded");
  // 표시로 프레임이 나뉘는 신호: 프레임마다 따로 견주고, 한 번 누를 때 같은 패킷을 되풀이하는지 알려 준다
  const same = { length: 4, mask: "====", same: 4, varies: 0, groups: [[0, 1]], distance: [[0, 0], [0, 0]], fields: [{ start: 0, length: 4, kind: "same" as const, bits: "0110", hex: "6" }] };
  a.analyzeCompare = vi.fn(async () => ({
    ...result,
    frames: [
      { index: 0, marker_before: [], lengths: [8, 12], rows: { symbols: ["10010101", "10010110"], manchester: null, second: null }, symbols: cols, manchester: null, second: null },
      { index: 1, marker_before: ["111110000001"], lengths: [4, 4], rows: { symbols: ["0110", "0110"], manchester: ["01", "01"], second: ["1", "1"] }, symbols: same, manchester: { ...same, length: 2 }, second: { ...same, length: 1, flipped: false, lengths: [1, 1] } },
    ],
    repeats_within: { same: 2, of: 2, length: 70, frames: 2 },
  }));
  await userEvent.click(screen.getByTestId("compare-go"));
  const frames = await screen.findByTestId("compare-frames");
  expect(frames).toHaveTextContent("2개의 프레임으로 나뉩니다");
  expect(frames).toHaveTextContent("같은 패킷을 되풀이해 보냅니다");
  expect(frames).toHaveTextContent("길이가 버스트마다 다릅니다(8 ~ 12심볼)");
  await userEvent.click(screen.getByTestId("compare-frame-1"));
  expect(frames).toHaveTextContent("앞의 표시: 111110000001 · 길이는 모두 4심볼");
  expect(screen.getByTestId("compare-grid").querySelectorAll(".an-vary")).toHaveLength(0); // 둘째 프레임은 두 줄이 같다
  // 둘째 층이 있는 프레임에서는 그것까지 푼 것을 고를 수 있다
  expect(screen.getByTestId("compare-layer-second")).not.toBeDisabled();
  await userEvent.click(screen.getByTestId("compare-layer-second"));
  expect(screen.getByTestId("compare-layer-second")).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText(/1 뒤에는 늘 0 이 붙는 부호/)).toBeInTheDocument();
});
