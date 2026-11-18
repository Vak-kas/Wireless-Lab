import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { MonitorChannel, MonitorState } from "../api";
import { fakeApi, renderWithStore } from "../test-utils";
import { SpectrumScreen } from "./SpectrumScreen";

const cell = (n: number, reachable = true) => ({ name: `ch${n}`, center_hz: (5000 + 5 * n) * 1e6, width_hz: 20e6, reachable });
const row = (name: string, median: number, extra: Partial<MonitorChannel> = {}): MonitorChannel => ({
  name,
  center_hz: 5.18e9,
  width_hz: 20e6,
  measured: true,
  mean_dbfs: median + 1,
  median_dbfs: median,
  peak_dbfs: -20,
  clipped: false,
  ...extra,
});
const state = (channels: MonitorChannel[], extra: Partial<MonitorState> = {}): MonitorState => ({
  id: "m1",
  device: "driver=uhd",
  plan: "wifi-5g",
  stat: "median_dbfs",
  auto: true,
  sweeps: 1,
  sweep_s: 0.4,
  channels,
  baseline_note: "",
  has_baseline: false,
  forced: [],
  raised: [],
  smooth: 5,
  rise_threshold_db: 6,
  ...extra,
});

function api(sweeps: MonitorState[] = [state([])]) {
  const a = fakeApi();
  a.devices = async () => [{ id: "driver=uhd", label: "USRP B210", driver: "uhd", serial: "ABC123" }];
  a.surveyDevice = async () => ({
    device: { id: "driver=uhd", label: "USRP B210", driver: "uhd", serial: "ABC123", freq_min_hz: 70e6, freq_max_hz: 6e9, max_sample_rate_hz: 56e6, bits: 12 },
    plans: [
      { id: "capture", available: false, channels: 0 },
      { id: "wifi-5g", available: true, channels: 5, widths: [20, 40, 80], map: [cell(36), cell(40), cell(44), cell(48), cell(52, false)], groups: { "40": [["ch36", "ch40"], ["ch44", "ch48"]], "80": [["ch36", "ch40", "ch44", "ch48"]] } },
    ],
    reported: { antennas: ["RX2", "TX/RX"], gain_range_db: [0, 76] },
  });
  let i = 0;
  a.monitorStart = vi.fn(async () => state([], { sweeps: 0, sweep_s: null }));
  a.monitorSweep = vi.fn(async () => sweeps[Math.min(i++, sweeps.length - 1)]!);
  a.monitorPatch = vi.fn(async (_id, body) => state([row("ch36", -70, { baseline_dbfs: -70, rise_db: 0 })], { baseline_note: body.baseline === "save" ? "manual" : "", has_baseline: body.baseline === "save" }));
  a.monitorStop = vi.fn(async () => undefined);
  return a;
}

test("장비를 고르면 장비 정보가 나오고, 쓸 수 없는 대역은 막혀 있다", async () => {
  renderWithStore(<SpectrumScreen />, api());
  const card = await screen.findByTestId("survey-device");
  expect(within(card).getByText("ABC123")).toBeInTheDocument();
  expect(within(card).getByText("70 ~ 6000 MHz")).toBeInTheDocument();
  expect(within(card).getByText("RX2, TX/RX")).toBeInTheDocument();
  expect(within(card).getByText("0 ~ 76 dB")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "파일에 담긴 대역" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Wi-Fi 5 GHz" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("monitor-start")).toBeDisabled(); // 채널을 아직 고르지 않았다
});

test("채널 맵: 누르는 단위에 따라 묶음째 고르고, 닿지 않는 채널은 누를 수 없다", async () => {
  const a = api();
  renderWithStore(<SpectrumScreen />, a);
  await userEvent.click(await screen.findByTestId("cell-ch36"));
  expect(screen.getByTestId("cell-ch36")).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("cell-ch40")).toHaveAttribute("aria-pressed", "false");
  await userEvent.click(screen.getByRole("button", { name: "80 MHz" }));
  await userEvent.click(screen.getByTestId("cell-ch44"));
  for (const n of [36, 40, 44, 48]) expect(screen.getByTestId(`cell-ch${n}`)).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(screen.getByTestId("cell-ch40")); // 다 골라진 묶음을 다시 누르면 풀린다
  expect(screen.getByTestId("cell-ch36")).toHaveAttribute("aria-pressed", "false");
  expect(screen.getByTestId("cell-ch52")).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "40 MHz" }));
  await userEvent.click(screen.getByTestId("cell-ch48"));
  await userEvent.click(screen.getByTestId("monitor-start"));
  expect(a.monitorStart).toHaveBeenCalledWith(expect.objectContaining({ device: "driver=uhd", plan: "wifi-5g", channels: ["ch44", "ch48"] }));
});

test("모니터링: 세기·증가량·경고를 보여 주고, 설정으로 돌아가면 멈추고 다시 고를 수 있다", async () => {
  const a = api([
    state([
      row("ch36", -70, { baseline_dbfs: -70, rise_db: 0, raised: false }),
      row("ch40", -52, { baseline_dbfs: -70, rise_db: 18, raised: true, clipped: true }),
      { name: "ch44", center_hz: 5.22e9, width_hz: 20e6, measured: false },
    ], { sweeps: 7, baseline_note: "auto", has_baseline: true, raised: ["ch40"] }),
  ]);
  renderWithStore(<SpectrumScreen />, a);
  await userEvent.click(await screen.findByTestId("cell-ch36"));
  await userEvent.click(screen.getByTestId("monitor-start"));
  const status = await screen.findByTestId("monitor-status");
  await waitFor(() => expect(within(status).getByText(/ch40 이\(가\) 기준보다 6 dB 넘게/)).toBeInTheDocument());
  expect(within(status).getByText("기준값: 자동 저장됨")).toBeInTheDocument();
  expect(screen.getByTestId("survey-bar-ch40")).toHaveAttribute("data-state", "clipped");
  expect(screen.getByTestId("survey-bar-ch44")).toHaveAttribute("data-state", "missing");
  expect(screen.getByTestId("rise-bar-ch40")).toHaveAttribute("data-state", "raised");
  const table = screen.getByTestId("survey-table");
  expect(within(table).getByText("+18.0")).toBeInTheDocument();
  expect(within(table).getByText("잴 수 없음")).toBeInTheDocument();

  await userEvent.click(screen.getByTestId("monitor-save"));
  expect(a.monitorPatch).toHaveBeenCalledWith("m1", { baseline: "save" });

  await userEvent.click(screen.getByTestId("monitor-back"));
  await waitFor(() => expect(a.monitorStop).toHaveBeenCalledWith("m1"));
  expect(await screen.findByTestId("cell-ch36")).toHaveAttribute("aria-pressed", "true"); // 고른 채널은 그대로
});

const VIEW = {
  device: "driver=uhd",
  fixed_tuning: false,
  center_hz: 5.18e9,
  sample_rate_hz: 20e6,
  bin_hz: 78125,
  dwell_s: 0.02,
  freq_hz: [5.17e9, 5.18e9, 5.19e9],
  mean_db: [-80, -40, -80],
  max_db: [-70, -30, -70],
  total_dbfs: -39.9,
  peak_dbfs: -12.3,
  clipped: false,
  waterfall: { rows: 2, cols: 2, values: [[0, 1], [1, 0]], col_ms: 10, floor_db: -90, ceil_db: -40 },
};

test("가운데 주파수와 대역폭을 넣고 보면 그 대역의 그림과 실제로 맞춘 값이 나온다", async () => {
  const a = api();
  a.surveySpectrum = vi.fn(async () => VIEW);
  renderWithStore(<SpectrumScreen />, a);
  await userEvent.click(await screen.findByTestId("view-run"));
  expect(await screen.findByText("가운데 주파수와 대역폭을 숫자로 넣어 주세요.")).toBeInTheDocument();
  expect(a.surveySpectrum).not.toHaveBeenCalled();
  await userEvent.type(screen.getByTestId("view-center"), "5180");
  await userEvent.type(screen.getByTestId("view-width"), "20");
  await userEvent.click(screen.getByTestId("view-run"));
  expect(a.surveySpectrum).toHaveBeenCalledWith({ device: "driver=uhd", center_hz: 5180e6, bandwidth_hz: 20e6, gain_db: undefined });
  const facts = await screen.findByTestId("view-facts");
  expect(within(facts).getByText("5180 MHz")).toBeInTheDocument();
  expect(within(facts).getByText("-39.9 dBFS")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "주파수별 세기" })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "시간에 따른 변화" })).toBeInTheDocument();
});

test("모니터를 멈춘 뒤 표에서 들여다보기를 누르면 그 채널의 주파수와 폭으로 바로 본다", async () => {
  const a = api([state([row("ch36", -70)])]);
  a.surveySpectrum = vi.fn(async () => VIEW);
  renderWithStore(<SpectrumScreen />, a);
  await userEvent.click(await screen.findByTestId("cell-ch36"));
  await userEvent.click(screen.getByTestId("monitor-start"));
  await userEvent.click(await screen.findByTestId("survey-look-ch36"));
  expect(await screen.findByText(/채널 모니터가 장비를 쓰는 중/)).toBeInTheDocument(); // 장비는 하나라 동시에 못 쓴다
  expect(a.surveySpectrum).not.toHaveBeenCalled();
  await userEvent.click(screen.getByTestId("monitor-toggle"));
  await userEvent.click(screen.getByTestId("survey-look-ch36"));
  await waitFor(() => expect(a.surveySpectrum).toHaveBeenCalledWith(expect.objectContaining({ center_hz: 5180e6, bandwidth_hz: 20e6 })));
  expect(screen.getByTestId("view-center")).toHaveValue("5180");
});

test("주변 AP 찾기: 찾은 AP의 '이 대역 고르기'로 그 AP가 쓰는 채널이 골라진다", async () => {
  const a = api();
  a.wifiStatus = async () => ({ available: true });
  a.wifiAps = vi.fn(async () => ({ aps: [{ ssid: "home", bssid: "AA:BB", seen_on: "ch36", primary: "ch44", width_mhz: 80, eht: true, count: 2, power_db: -31.25 }] }));
  renderWithStore(<SpectrumScreen />, a);
  await userEvent.click(await screen.findByTestId("cell-ch36"));
  await userEvent.click(await screen.findByTestId("ap-find"));
  expect(a.wifiAps).toHaveBeenCalledWith({ device: "driver=uhd", plan: "wifi-5g", channels: ["ch36"], gain_db: undefined });
  const table = await screen.findByTestId("ap-table");
  expect(within(table).getByText("home")).toBeInTheDocument();
  expect(within(table).getByText("80 MHz")).toBeInTheDocument();
  await userEvent.click(screen.getByTestId("ap-pick-AA:BB"));
  for (const n of [36, 40, 44, 48]) expect(screen.getByTestId(`cell-ch${n}`)).toHaveAttribute("aria-pressed", "true");
});

test("실제 송신 대역폭: 처음 자리 잡은 폭보다 좁은 프레임이 주가 되면 경고한다", async () => {
  const { BandwidthWatch, countByWidth, dominant } = await import("./WifiPanels");
  const { render } = await import("@testing-library/react");
  const p = (w: number, uplink = false) => ({ bandwidth_mhz: w, uplink, bss_color: 1, non_ofdma: true, punctured: 0, power_db: -30 });
  const samples = [
    { at: 1000, ppdus: [p(160), p(160)] }, // 오래된 것(10초 밖)
    { at: 20_000, ppdus: [p(80), p(80), p(80), p(160), p(20, true)] },
  ];
  expect(countByWidth(samples, 21_000)).toEqual([{ width: 160, count: 1 }, { width: 80, count: 3 }]); // 올려 보내는 프레임은 세지 않는다
  expect(dominant(countByWidth(samples, 21_000))).toBe(80);
  render(<BandwidthWatch channels={["ch36"]} channel="ch36" onChannel={() => undefined} samples={samples} reference={160} now={21_000} />);
  expect(screen.getByTestId("usig-narrowed")).toHaveTextContent("160 → 80 MHz");
  expect(within(screen.getByTestId("usig-table")).getByText("75%")).toBeInTheDocument();
});
