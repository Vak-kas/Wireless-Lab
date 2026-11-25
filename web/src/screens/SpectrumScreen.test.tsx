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

test("장비를 고르면 장비 정보가 나오고, 쓸 수 없는 대역은 보이지 않는다", async () => {
  renderWithStore(<SpectrumScreen />, api());
  const card = await screen.findByTestId("survey-device");
  expect(within(card).getByText("ABC123")).toBeInTheDocument();
  expect(within(card).getByText("70 ~ 6000 MHz")).toBeInTheDocument();
  expect(within(card).getByText("RX2, TX/RX")).toBeInTheDocument();
  expect(within(card).getByText("0 ~ 76 dB")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "파일에 담긴 대역" })).toBeNull(); // 실제 장비에는 모의용 대역을 보이지 않는다
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

test("모의 장비는 평소에 보이지 않고, '모의 실험하기'를 눌러야 나온다. 실제 장비가 나타나면 자동으로 고른다", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    const a = api();
    const sim = { id: "simulated:x", label: "모의 장비 · x", driver: "simulated" };
    const usrp = { id: "driver=uhd", label: "USRP B210", driver: "uhd" };
    let list = [sim];
    a.devices = async () => list;
    const asked: string[] = [];
    const describe = a.surveyDevice;
    a.surveyDevice = async (id) => (asked.push(id), describe(id));
    renderWithStore(<SpectrumScreen />, a);
    expect(await screen.findByTestId("device-none")).toBeInTheDocument(); // 실제 장비가 없다고 알려 준다
    expect(screen.queryByRole("button", { name: "x" })).toBeNull();
    expect(asked).toEqual([]);

    list = [usrp, sim];
    await vi.advanceTimersByTimeAsync(5100);
    await waitFor(() => expect(screen.getByRole("button", { name: "USRP B210" })).toHaveAttribute("aria-pressed", "true"));
    expect(screen.queryByRole("button", { name: "x" })).toBeNull();

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(screen.getByTestId("sim-toggle"));
    expect(screen.getByRole("button", { name: "x" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: "USRP B210" })).toBeNull();
    expect(screen.getByText(/모의 실험 중/)).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(5100); // 목록을 다시 읽어도 고른 것은 그대로
    expect(screen.getByRole("button", { name: "x" })).toHaveAttribute("aria-pressed", "true");
    expect(asked.at(-1)).toBe("simulated:x");

    await user.click(screen.getByTestId("sim-toggle"));
    expect(screen.getByRole("button", { name: "USRP B210" })).toHaveAttribute("aria-pressed", "true");
  } finally {
    vi.useRealTimers();
  }
});

test("첫 화면에서 'Wi-Fi 보기'로 넘어오면 그 장비와 대역이 골라진 채 열린다", async () => {
  const { saveIntent } = await import("../devices/intent");
  const a = api();
  const other = { id: "driver=other", label: "다른 장비", driver: "x" };
  a.devices = async () => [other, { id: "driver=uhd", label: "USRP B210", driver: "uhd" }];
  const asked: string[] = [];
  const describe = a.surveyDevice;
  a.surveyDevice = async (id) => (asked.push(id), describe(id));
  saveIntent({ device: "driver=uhd", plan: "wifi-5g" });
  renderWithStore(<SpectrumScreen />, a);
  await waitFor(() => expect(screen.getByRole("button", { name: "USRP B210" })).toHaveAttribute("aria-pressed", "true"));
  expect(new Set(asked)).toEqual(new Set(["driver=uhd"])); // 맨 앞 장비가 아니라 넘겨받은 장비만 물었다
  expect(await screen.findByRole("button", { name: "Wi-Fi 5 GHz" })).toHaveAttribute("aria-pressed", "true");
  expect(sessionStorage.getItem("nrtrail.spectrumIntent")).toBeNull(); // 한 번 쓰면 지운다
});

test("모니터링 탭: 주변 AP 와 프레임·송신 폭이 스크롤 없이 탭으로 나오고, 실시간 풀이를 끌 수 있다", async () => {
  const a = api([state([row("ch36", -70)])]);
  a.wifiStatus = async () => ({ available: true });
  a.wifiLive = vi.fn(async ({ channel }: { channel: string }) => ({
    channel,
    aps: [{ ssid: "home", bssid: "AA:BB", seen_on: channel, primary: "ch36", width_mhz: 160, eht: true, count: 1, power_db: -30 }],
    ppdus: [
      { format: "Non-HT", power_db: -30 },
      { format: "HE-SU", power_db: -31 },
      ...Array.from({ length: 12 }, () => ({ format: "EHT-MU", bandwidth_mhz: 160, uplink: false, bss_color: 1, non_ofdma: true, punctured: 0, power_db: -32 })),
    ],
  }));
  renderWithStore(<SpectrumScreen />, a);
  await userEvent.click(await screen.findByTestId("cell-ch36"));
  await userEvent.click(screen.getByTestId("monitor-start"));
  await waitFor(() => expect(a.wifiLive).toHaveBeenCalledWith({ device: "driver=uhd", plan: "wifi-5g", channel: "ch36", gain_db: undefined }));
  expect(await screen.findByTestId("survey-table")).toBeInTheDocument(); // 처음에는 채널 세기 탭
  await waitFor(() => expect(screen.getByTestId("tab-near")).toHaveTextContent("주변 AP1")); // 탭에 잡힌 AP 수가 보인다

  await userEvent.click(screen.getByTestId("tab-near"));
  expect(screen.queryByTestId("survey-table")).toBeNull();
  expect(within(screen.getByTestId("wifi-live")).getByText("home")).toBeInTheDocument();

  await userEvent.click(screen.getByTestId("tab-frames"));
  const frames = screen.getByTestId("wifi-frames");
  expect(within(within(frames).getByTestId("kinds-table")).getByRole("columnheader", { name: "Wi-Fi 7" })).toBeInTheDocument();
  expect(within(within(frames).getByTestId("kinds-table")).getByText("12")).toBeInTheDocument();
  expect(await within(frames).findByText("처음 자리 잡은 폭: 160 MHz")).toBeInTheDocument();

  const calls = (a.wifiLive as ReturnType<typeof vi.fn>).mock.calls.length;
  await userEvent.click(screen.getByTestId("wifi-live-toggle"));
  expect(within(frames).queryByTestId("kinds-table")).toBeNull();
  await new Promise((r) => setTimeout(r, 400));
  expect((a.wifiLive as ReturnType<typeof vi.fn>).mock.calls.length).toBe(calls); // 끄면 더 받지 않는다
});

test("블루투스: 광고 채널 셋이 기본으로 골라지고, 모니터링 중 주변 기기 탭에 주소·이름·제조사가 나온다", async () => {
  const a = api([state([row("ch37", -70), row("ch38", -71), row("ch39", -72)], { plan: "ble" })]);
  const describe = a.surveyDevice;
  a.surveyDevice = async (id) => {
    const info = await describe(id);
    return { ...info, plans: [{ id: "ble", available: true, channels: 4, widths: [2], map: [37, 0, 38, 39].map((n) => ({ name: `ch${n}`, center_hz: 2402e6, width_hz: 2e6, reachable: true })) }] };
  };
  a.bleScan = vi.fn(async ({ channel }: { channel: number }) => ({
    channel,
    packets: 3,
    crc_failed: 1,
    clipped: false,
    directed: { SCAN_REQ: 2 },
    devices: [{ address: "C0:11:22:33:44:55", address_type: "random" as const, name: "tag", company: "Apple", company_id: 76, services: [], pdu_types: ["ADV_IND"], count: 2, power_db: -20, channel }],
  }));
  renderWithStore(<SpectrumScreen />, a);
  for (const n of [37, 38, 39]) expect(await screen.findByTestId(`cell-ch${n}`)).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("cell-ch0")).toHaveAttribute("aria-pressed", "false");
  await userEvent.click(screen.getByTestId("monitor-start"));
  await waitFor(() => expect(a.bleScan).toHaveBeenCalledWith({ device: "driver=uhd", channel: 37, gain_db: undefined }));
  await waitFor(() => expect(screen.getByTestId("tab-near")).toHaveTextContent("주변 기기1"));
  expect(screen.queryByTestId("tab-frames")).toBeNull();
  await userEvent.click(screen.getByTestId("tab-near"));
  const table = screen.getByTestId("ble-table");
  expect(within(table).getByText("C0:11:22:33:44:55")).toBeInTheDocument();
  expect(within(table).getByText("tag")).toBeInTheDocument();
  expect(within(table).getByText("Apple")).toBeInTheDocument();
  expect(within(table).getByText("임의")).toBeInTheDocument();
  expect(screen.getByTestId("ble-panel")).toHaveTextContent("SCAN_REQ 2"); // 특정 기기를 향한 것은 개수만
});

test("수신이 한두 번 실패해도 모니터링은 멈추지 않고, 잇달아 세 번 실패하면 멈춘다", async () => {
  const a = api([state([row("ch36", -70)])]);
  let calls = 0;
  a.monitorSweep = vi.fn(async () => {
    calls += 1;
    if (calls === 1) throw new Error("Overflow occured in middle of a contiguous burst");
    if (calls >= 4) throw new Error("장비가 응답하지 않습니다");
    return state([row("ch36", -70)], { sweeps: calls });
  });
  renderWithStore(<SpectrumScreen />, a);
  await userEvent.click(await screen.findByTestId("cell-ch36"));
  await userEvent.click(screen.getByTestId("monitor-start"));
  expect(await screen.findByTestId("monitor-hiccup")).toHaveTextContent("Overflow"); // 한 번 실패: 알리고 계속
  expect(await screen.findByTestId("survey-table", undefined, { timeout: 3000 })).toBeInTheDocument(); // 다음 바퀴는 성공
  await waitFor(() => expect(screen.getByTestId("monitor-toggle")).toHaveTextContent("다시 시작"), { timeout: 5000 }); // 세 번 잇달아 실패하면 멈춘다
  expect(calls).toBe(6);
});

test("대역 단추를 누르면 가운데 주파수와 대역폭이 채워지고 바로 본다. 장비보다 넓은 대역은 폭을 줄인다", async () => {
  const a = api();
  a.surveySpectrum = vi.fn(async () => VIEW);
  renderWithStore(<SpectrumScreen />, a);
  const bands = await screen.findByTestId("view-bands");
  await userEvent.click(within(bands).getByRole("button", { name: "433 MHz 리모컨·차 키" }));
  expect(screen.getByTestId("view-center")).toHaveValue("433.92");
  expect(screen.getByTestId("view-width")).toHaveValue("2");
  await waitFor(() => expect(a.surveySpectrum).toHaveBeenCalledWith(expect.objectContaining({ center_hz: 433.92e6, bandwidth_hz: 2e6 })));
  await userEvent.click(within(bands).getByRole("button", { name: "5G 3.5 GHz" }));
  expect(Number((screen.getByTestId("view-width") as HTMLInputElement).value)).toBeLessThan(100);
});

test("내 대역을 등록하면 단추로 남고, 다시 열어도 있으며, 지울 수 있다", async () => {
  localStorage.clear();
  const a = api();
  a.surveySpectrum = vi.fn(async () => VIEW);
  const first = renderWithStore(<SpectrumScreen />, a);
  await userEvent.type(await screen.findByTestId("view-center"), "447.5");
  await userEvent.type(screen.getByTestId("view-width"), "1");
  await userEvent.click(screen.getByRole("button", { name: "+ 내 대역 등록" }));
  await userEvent.type(screen.getByTestId("view-band-name"), "우리 집 차 키");
  await userEvent.click(screen.getByTestId("view-band-save"));
  expect(screen.getByRole("button", { name: "우리 집 차 키" })).toBeInTheDocument();
  first.unmount();

  renderWithStore(<SpectrumScreen />, a);
  await userEvent.click(await screen.findByRole("button", { name: "우리 집 차 키" }));
  expect(screen.getByTestId("view-center")).toHaveValue("447.5");
  await userEvent.click(screen.getByRole("button", { name: "우리 집 차 키 지우기" }));
  expect(screen.queryByRole("button", { name: "우리 집 차 키" })).not.toBeInTheDocument();
  expect(localStorage.getItem("nrtrail.viewBands")).toBe("[]");
});

test("위에서 고른 채널을 '고른 범위 들여다보기'로 아래 칸에 넘긴다", async () => {
  const a = api();
  a.surveySpectrum = vi.fn(async () => VIEW);
  renderWithStore(<SpectrumScreen />, a);
  expect(await screen.findByTestId("look-picked")).toBeDisabled();
  await userEvent.click(screen.getByTestId("cell-ch36"));
  await userEvent.click(screen.getByTestId("cell-ch40"));
  await userEvent.click(screen.getByTestId("look-picked"));
  expect(screen.getByTestId("view-center")).toHaveValue("5190");
  expect(screen.getByTestId("view-width")).toHaveValue("40");
  await waitFor(() => expect(a.surveySpectrum).toHaveBeenCalledWith(expect.objectContaining({ center_hz: 5190e6, bandwidth_hz: 40e6 })));
});
