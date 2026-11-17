import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { SurveyChannel } from "../api";
import { fakeApi, renderWithStore } from "../test-utils";
import { SpectrumScreen } from "./SpectrumScreen";

const ch = (name: string, median: number, extra: Partial<SurveyChannel> = {}): SurveyChannel => ({
  name,
  center_hz: 5.18e9,
  width_hz: 20e6,
  coverage: 1,
  measured: true,
  mean_dbfs: median + 1,
  median_dbfs: median,
  peak_dbfs: -20,
  clipped: false,
  ...extra,
});

function api(rows: SurveyChannel[][]) {
  const a = fakeApi();
  a.devices = async () => [{ id: "driver=uhd", label: "USRP B210", driver: "uhd", serial: "ABC123" }];
  a.surveyDevice = async () => ({
    device: { id: "driver=uhd", label: "USRP B210", driver: "uhd", serial: "ABC123", freq_min_hz: 70e6, freq_max_hz: 6e9, max_sample_rate_hz: 56e6, bits: 12 },
    plans: [
      { id: "capture", available: false, channels: 0 },
      { id: "wifi-5g", available: true, channels: 25 },
    ],
    reported: { antennas: ["RX2", "TX/RX"], gain_range_db: [0, 76] },
  });
  let i = 0;
  a.surveyRun = vi.fn(async (req) => ({ device: req.device, plan: req.plan, unit: "dBFS", dwell_s: 0.02, fixed_tuning: false, channels: rows[Math.min(i++, rows.length - 1)]! }));
  return a;
}

test("장비를 고르면 장비 정보가 나오고, 쓸 수 없는 방식은 막혀 있다", async () => {
  renderWithStore(<SpectrumScreen />, api([[]]));
  const card = await screen.findByTestId("survey-device");
  expect(within(card).getByText("ABC123")).toBeInTheDocument();
  expect(within(card).getByText("70 ~ 6000 MHz")).toBeInTheDocument();
  expect(within(card).getByText("RX2, TX/RX")).toBeInTheDocument();
  expect(within(card).getByText("0 ~ 76 dB")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "파일에 담긴 대역" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Wi-Fi 5 GHz" })).toHaveAttribute("aria-pressed", "true");
});

test("재면 가장 센 채널과 막대·표가 나오고, 잴 수 없는 채널과 포화를 구분해 보여 준다", async () => {
  const a = api([[ch("ch36", -70), ch("ch40", -35, { clipped: true }), { name: "ch44", center_hz: 5.22e9, width_hz: 20e6, coverage: 0, measured: false }]]);
  renderWithStore(<SpectrumScreen />, a);
  await userEvent.click(await screen.findByTestId("survey-run"));
  expect(await screen.findByText(/가장 센 곳: ch40/)).toBeInTheDocument();
  expect(a.surveyRun).toHaveBeenCalledWith(expect.objectContaining({ device: "driver=uhd", plan: "wifi-5g" }));
  expect(screen.getByTestId("survey-bar-ch36")).toHaveAttribute("data-state", "ok");
  expect(screen.getByTestId("survey-bar-ch40")).toHaveAttribute("data-state", "clipped");
  expect(screen.getByTestId("survey-bar-ch44")).toHaveAttribute("data-state", "missing");
  expect(screen.getByText(/입력이 포화된 채널/)).toBeInTheDocument();
  expect(within(screen.getByTestId("survey-table")).getByText("잴 수 없음")).toBeInTheDocument();
});

test("기준을 저장한 뒤 다시 재면 기준 대비 얼마나 올랐는지 보여 준다", async () => {
  renderWithStore(<SpectrumScreen />, api([[ch("ch36", -70)], [ch("ch36", -58.5)]]));
  await userEvent.click(await screen.findByTestId("survey-run"));
  await userEvent.click(await screen.findByTestId("survey-baseline"));
  await userEvent.click(screen.getByTestId("survey-run"));
  await waitFor(() => expect(within(screen.getByTestId("survey-table")).getByText("+11.5")).toBeInTheDocument());
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
  const a = api([[]]);
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

test("채널 표에서 들여다보기를 누르면 그 채널의 주파수와 폭으로 바로 본다", async () => {
  const a = api([[ch("ch36", -70)]]);
  a.surveySpectrum = vi.fn(async () => VIEW);
  renderWithStore(<SpectrumScreen />, a);
  await userEvent.click(await screen.findByTestId("survey-run"));
  await userEvent.click(await screen.findByTestId("survey-look-ch36"));
  await waitFor(() => expect(a.surveySpectrum).toHaveBeenCalledWith(expect.objectContaining({ center_hz: 5180e6, bandwidth_hz: 20e6 })));
  expect(screen.getByTestId("view-center")).toHaveValue("5180");
});
