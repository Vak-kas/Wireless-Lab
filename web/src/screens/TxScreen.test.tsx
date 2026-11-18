import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { fakeApi, renderWithStore } from "../test-utils";
import { TxScreen } from "./TxScreen";

const usrp = { id: "usrp:B200:S1", label: "USRP B200 (S1)", driver: "uhd" };

function api() {
  const a = fakeApi();
  a.devices = async () => [usrp, { id: "simulated:x", label: "모의 장비 · x", driver: "simulated" }];
  a.txStatus = async () => ({
    available: true,
    warning_version: "v1",
    max_seconds: 30,
    max_gain_db: 89.75,
    default_gain_db: 0,
    standards: [
      { id: "wifi-he", sample_rate_hz: 20e6 },
      { id: "ble-adv", sample_rate_hz: 4e6 },
      { id: "my-sig", sample_rate_hz: 2e6, source: "plugin" as const, label: "내 실험 신호", description: "내가 넣은 설명" },
      { id: "wifi-mgmt", sample_rate_hz: 0, source: "planned" as const },
      { id: "!bad.py", sample_rate_hz: 0, source: "plugin" as const, label: "bad.py", error: "SyntaxError: 틀림" },
    ],
  });
  a.surveyDevice = async () => ({
    device: usrp,
    plans: [
      { id: "wifi-5g", available: true, channels: 2, map: [{ name: "ch36", center_hz: 5180e6, width_hz: 20e6, reachable: true }, { name: "ch40", center_hz: 5200e6, width_hz: 20e6, reachable: false }] },
      { id: "ble", available: true, channels: 1, map: [{ name: "ch38", center_hz: 2426e6, width_hz: 2e6, reachable: true }] },
      { id: "custom", available: true, channels: 0 },
    ],
  });
  a.txStart = vi.fn(async () => ({ seconds: 2.01, stopped: false, underruns: 0 }));
  a.txStop = vi.fn(async () => ({ stopping: true }));
  return a;
}

beforeEach(() => sessionStorage.clear());

test("송신은 경고창에서 책임과 환경 두 가지를 모두 확인해야 나간다. 확인한 값이 요청에 그대로 실린다", async () => {
  const a = api();
  renderWithStore(<TxScreen />, a);
  await userEvent.type(await screen.findByTestId("tx-center"), "2450");
  expect(screen.queryByRole("button", { name: /모의 장비/ })).toBeNull(); // 모의 장비로는 송신하지 않는다
  await userEvent.click(screen.getByTestId("tx-ask"));
  const dialog = await screen.findByRole("alertdialog", { name: "송신하기 전에 확인하세요" });
  expect(within(dialog).getByText(/책임\(전파법 등\)은 사용자에게 있습니다/)).toBeInTheDocument();
  expect(within(dialog).getByText("USRP B200 (S1)")).toBeInTheDocument();
  expect(within(dialog).getByText("2450 MHz")).toBeInTheDocument();
  expect(within(dialog).getByText("0 dB")).toBeInTheDocument(); // 비워 두면 가장 낮은 이득
  expect(within(dialog).getByText("2 s")).toBeInTheDocument();
  expect(screen.getByTestId("tx-confirm")).toBeDisabled();
  await userEvent.click(screen.getByTestId("tx-agree"));
  expect(screen.getByTestId("tx-confirm")).toBeDisabled(); // 하나만으로는 안 된다
  expect(a.txStart).not.toHaveBeenCalled();
  await userEvent.click(screen.getByTestId("tx-closed"));
  await userEvent.click(screen.getByTestId("tx-confirm"));
  await waitFor(() => expect(a.txStart).toHaveBeenCalledTimes(1));
  expect(a.txStart).toHaveBeenCalledWith({
    device: "usrp:B200:S1",
    center_hz: 2450e6,
    sample_rate_hz: 1e6,
    gain_db: 0,
    seconds: 2,
    waveform: { kind: "tone", offset_hz: 100e3, amplitude: 0.3 },
    confirm: { accepted: true, closed_setup: true, version: "v1", shown: { device: "usrp:B200:S1", center_hz: 2450e6, gain_db: 0, seconds: 2 } },
  });
  expect(await screen.findByTestId("tx-done")).toHaveTextContent("2.01초 동안 내보내고 끝났습니다.");
});

test("취소하면 나가지 않고, 다시 열면 확인 표시는 지워져 있다(매번 새로 확인)", async () => {
  const a = api();
  renderWithStore(<TxScreen />, a);
  await userEvent.type(await screen.findByTestId("tx-center"), "915");
  await userEvent.click(screen.getByTestId("tx-ask"));
  await userEvent.click(screen.getByTestId("tx-agree"));
  await userEvent.click(screen.getByTestId("tx-closed"));
  await userEvent.click(screen.getByTestId("tx-cancel"));
  expect(screen.queryByTestId("tx-warning")).toBeNull();
  expect(a.txStart).not.toHaveBeenCalled();
  await userEvent.click(screen.getByTestId("tx-ask"));
  expect(screen.getByTestId("tx-agree")).not.toBeChecked();
  expect(screen.getByTestId("tx-closed")).not.toBeChecked();
});

test("값이 빠지면 경고창을 띄우지 않고, 송신 중에는 멈출 수 있다", async () => {
  const a = api();
  let finish: (v: { seconds: number; stopped: boolean; underruns: number }) => void = () => undefined;
  a.txStart = vi.fn(() => new Promise<{ seconds: number; stopped: boolean; underruns: number }>((r) => (finish = r)));
  renderWithStore(<TxScreen />, a);
  await userEvent.click(await screen.findByTestId("tx-ask"));
  expect(await screen.findByText(/숫자로 넣어 주세요/)).toBeInTheDocument();
  expect(screen.queryByTestId("tx-warning")).toBeNull();
  await userEvent.type(screen.getByTestId("tx-center"), "2450");
  await userEvent.click(screen.getByTestId("tx-ask"));
  await userEvent.click(screen.getByTestId("tx-agree"));
  await userEvent.click(screen.getByTestId("tx-closed"));
  await userEvent.click(screen.getByTestId("tx-confirm"));
  expect(await screen.findByTestId("tx-sending")).toBeInTheDocument();
  await userEvent.click(screen.getByTestId("tx-stop"));
  expect(a.txStop).toHaveBeenCalled();
  finish({ seconds: 0.4, stopped: true, underruns: 0 });
  expect(await screen.findByTestId("tx-done")).toHaveTextContent("0.4초에서 멈췄습니다.");
});

test("송신 기능이 없는 설치에서는 안내만 보인다", async () => {
  const a = api();
  a.txStatus = async () => ({ available: false });
  renderWithStore(<TxScreen />, a);
  expect(await screen.findByText("이 설치에는 송신 기능이 없습니다.")).toBeInTheDocument();
  expect(screen.queryByTestId("tx-form")).toBeNull();
});

test("대역과 채널을 눌러 주파수를 고르면 가운데 주파수와 샘플레이트가 채워지고, 신호 종류마다 설명이 나온다", async () => {
  const a = api();
  renderWithStore(<TxScreen />, a);
  expect(await screen.findByTestId("tx-kind-desc")).toHaveTextContent("아무 내용도 싣지 않은 사인파"); // 시험 톤이 무엇인지
  await userEvent.click(await screen.findByRole("button", { name: "Wi-Fi 5 GHz" }));
  expect(screen.getByTestId("tx-cell-ch40")).toBeDisabled(); // 장비가 닿지 않는 채널
  await userEvent.click(screen.getByTestId("tx-cell-ch36"));
  expect(screen.getByTestId("tx-center")).toHaveValue("5180");
  expect(screen.getByTestId("tx-rate")).toHaveValue("20");
  await userEvent.click(screen.getByRole("button", { name: "5 MHz" }));
  expect(screen.getByTestId("tx-rate")).toHaveValue("5");
  expect(screen.queryByRole("button", { name: "직접 지정" })).toBeNull(); // 채널 맵이 없는 대역은 고르기에 없다
});

test("표준 시험 신호를 고르면 샘플레이트가 그 신호의 값으로 정해져 요청에 실린다", async () => {
  const a = api();
  renderWithStore(<TxScreen />, a);
  await userEvent.click(await screen.findByRole("button", { name: "블루투스 (BLE)" }));
  await userEvent.click(screen.getByTestId("tx-cell-ch38"));
  await userEvent.click(screen.getByRole("button", { name: "표준 시험 신호" }));
  await userEvent.click(screen.getByRole("button", { name: "블루투스 시험 광고" }));
  expect(screen.getByTestId("tx-rate")).toHaveValue("4");
  expect(screen.getByTestId("tx-rate")).toBeDisabled();
  await userEvent.click(screen.getByTestId("tx-ask"));
  expect(within(screen.getByRole("alertdialog")).getByText("블루투스 시험 광고")).toBeInTheDocument();
  await userEvent.click(screen.getByTestId("tx-agree"));
  await userEvent.click(screen.getByTestId("tx-closed"));
  await userEvent.click(screen.getByTestId("tx-confirm"));
  await waitFor(() => expect(a.txStart).toHaveBeenCalledWith(expect.objectContaining({ center_hz: 2426e6, sample_rate_hz: 4e6, waveform: { kind: "standard", standard: "ble-adv" } })));
});

test("미구현 칸은 꺼진 채로 보이고, 내가 넣은 생성기는 이름과 설명이 나오며 고를 수 있다", async () => {
  const a = api();
  renderWithStore(<TxScreen />, a);
  await userEvent.click(await screen.findByRole("button", { name: "표준 시험 신호" }));
  expect(screen.getByRole("button", { name: /Wi-Fi 관리 프레임.*미구현/ })).toBeDisabled();
  expect(screen.getByTestId("tx-planned-note")).toHaveTextContent("plugins/tx/");
  expect(screen.getByTestId("tx-plugin-error")).toHaveTextContent("bad.py");
  await userEvent.click(screen.getByRole("button", { name: /내 실험 신호.*내 생성기/ }));
  expect(screen.getByText("내가 넣은 설명")).toBeInTheDocument();
  expect(screen.getByTestId("tx-rate")).toHaveValue("2");
  await userEvent.type(screen.getByTestId("tx-center"), "5180");
  await userEvent.click(screen.getByTestId("tx-ask"));
  expect(within(screen.getByRole("alertdialog")).getByText("내 실험 신호")).toBeInTheDocument(); // 확인 창에도 생성기 이름이 나온다
  await userEvent.click(screen.getByTestId("tx-agree"));
  await userEvent.click(screen.getByTestId("tx-closed"));
  await userEvent.click(screen.getByTestId("tx-confirm"));
  await waitFor(() => expect(a.txStart).toHaveBeenCalledWith(expect.objectContaining({ sample_rate_hz: 2e6, waveform: { kind: "standard", standard: "my-sig" } })));
});

const b210 = { id: "usrp:B210:S2", label: "USRP B210 (S2)", driver: "uhd" };
const rxBase = {
  gain_db: 20,
  num_samples: 200000,
  power_dbfs: -14,
  peak: 0.2,
  clipped: false,
  overflows: 0,
  spectrum: { offset_hz: [-500e3, 0, 100e3, 500e3], db: [-70, -68, -15, -71] },
  meta_path: "/x/sessions/tx/rx-1.sigmf-meta",
};

test("보내면서 받기: 다른 장비를 받는 쪽으로 고르고, 경고창에 받는 장비가 보이며, 결과에 받았는지와 근거가 나온다", async () => {
  const a = api();
  a.devices = async () => [usrp, b210];
  a.txStatus = async () => ({ available: true, warning_version: "v1", max_seconds: 30, max_gain_db: 89.75, default_gain_db: 0, standards: [], receive: { max_seconds: 1, max_samples: 8e6, skip_seconds: 0.2, default_gain_db: 20 } });
  a.txStart = vi.fn(async () => ({
    seconds: 2,
    stopped: false,
    underruns: 0,
    received: { ...rxBase, device: b210.id, check: { kind: "tone", found: true, expected_offset_hz: 100e3, found_offset_hz: 100.6e3, above_floor_db: 54.2 } },
  }));
  renderWithStore(<TxScreen />, a);
  await userEvent.type(await screen.findByTestId("tx-center"), "2450");
  expect(screen.queryByTestId("tx-rx-gain")).toBeNull(); // 켜기 전에는 받는 쪽 설정이 없다
  await userEvent.click(screen.getByTestId("tx-rx-on"));
  // 따로 고르지 않으면 보내는 장비가 아닌 쪽이 받는다
  expect(screen.getByTestId("tx-rx-wiring")).toHaveTextContent("받는 장비의 RX 포트");
  await userEvent.click(screen.getByTestId("tx-ask"));
  const dialog = await screen.findByRole("alertdialog");
  expect(within(dialog).getByText("USRP B210 (S2) · 20 dB")).toBeInTheDocument();
  await userEvent.click(screen.getByTestId("tx-agree"));
  await userEvent.click(screen.getByTestId("tx-closed"));
  await userEvent.click(screen.getByTestId("tx-confirm"));
  await waitFor(() => expect(a.txStart).toHaveBeenCalledTimes(1));
  expect(vi.mocked(a.txStart).mock.calls[0]?.[0].receive).toEqual({ device: b210.id, gain_db: 20, seconds: 0.2 });
  const rx = await screen.findByTestId("tx-rx");
  expect(within(rx).getByText("보낸 신호를 받았습니다")).toBeInTheDocument();
  expect(within(rx).getByTestId("tx-rx-tone")).toHaveTextContent("100.6 kHz (보낸 곳 100 kHz), 바닥보다 54.2 dB 높음");
  expect(within(rx).getByTestId("tx-rx-spectrum")).toBeInTheDocument();
  expect(within(rx).getByText("/x/sessions/tx/rx-1.sigmf-meta")).toBeInTheDocument();
});

test("보내면서 받기: 장비가 한 대면 같은 장비로 받고, 못 받았으면 그렇게 알리고 넘침도 알린다", async () => {
  const a = api();
  a.devices = async () => [usrp];
  a.txStart = vi.fn(async () => ({
    seconds: 2,
    stopped: false,
    underruns: 0,
    received: { ...rxBase, device: usrp.id, clipped: true, overflows: 3, check: { kind: "waveform", found: false, match: 0.04 } },
  }));
  renderWithStore(<TxScreen />, a);
  await userEvent.type(await screen.findByTestId("tx-center"), "2450");
  await userEvent.click(screen.getByTestId("tx-rx-on"));
  expect(screen.getByTestId("tx-rx-wiring")).toHaveTextContent("같은 장비의 TX 포트와 RX 포트");
  await userEvent.click(screen.getByTestId("tx-ask"));
  await userEvent.click(await screen.findByTestId("tx-agree"));
  await userEvent.click(screen.getByTestId("tx-closed"));
  await userEvent.click(screen.getByTestId("tx-confirm"));
  const rx = await screen.findByTestId("tx-rx");
  expect(vi.mocked(a.txStart).mock.calls[0]?.[0].receive?.device).toBe(usrp.id);
  expect(within(rx).getByText("보낸 신호가 받은 쪽에서 확인되지 않았습니다")).toBeInTheDocument();
  expect(within(rx).getByTestId("tx-rx-match")).toHaveTextContent("0.04");
  expect(within(rx).getByText(/너무 셉니다/)).toBeInTheDocument();
  expect(within(rx).getByText(/3번 끊겼습니다/)).toBeInTheDocument();
});

test("받기를 켜지 않으면 요청에 receive 가 없다", async () => {
  const a = api();
  renderWithStore(<TxScreen />, a);
  await userEvent.type(await screen.findByTestId("tx-center"), "2450");
  await userEvent.click(screen.getByTestId("tx-ask"));
  await userEvent.click(await screen.findByTestId("tx-agree"));
  await userEvent.click(screen.getByTestId("tx-closed"));
  await userEvent.click(screen.getByTestId("tx-confirm"));
  await waitFor(() => expect(a.txStart).toHaveBeenCalledTimes(1));
  expect(vi.mocked(a.txStart).mock.calls[0]?.[0]).not.toHaveProperty("receive");
  expect(screen.queryByTestId("tx-rx")).toBeNull();
});
