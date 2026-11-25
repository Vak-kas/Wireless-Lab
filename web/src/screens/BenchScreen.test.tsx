import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import type { DeviceInfo, TxRequest } from "../api";
import { fakeApi, renderWithStore } from "../test-utils";
import { BenchScreen } from "./BenchScreen";

const a: DeviceInfo = { id: "usrp:B200:S1", label: "USRP B200 (S1)", driver: "uhd", serial: "S1", freq_min_hz: 70e6, freq_max_hz: 6e9, max_sample_rate_hz: 56e6, stages: {} };
const b: DeviceInfo = { ...a, id: "usrp:B210:S2", label: "USRP B210 (S2)", serial: "S2" };

function api(tx = true) {
  const x = fakeApi();
  x.devices = async () => [a, b];
  x.txStatus = async () => ({ available: tx });
  x.surveyDevice = async (id) => ({ device: id === a.id ? a : b, plans: [{ id: "custom", available: true, channels: 0 }] });
  return x;
}

beforeEach(() => sessionStorage.clear());

test("작업판: 장비마다 칸이 하나씩 놓이고, 칸마다 수신·송신을 따로 바꿀 수 있다", async () => {
  sessionStorage.setItem("nrtrail.bench", JSON.stringify([{ device: a.id, mode: "rx" }, { device: b.id, mode: "rx" }]));
  renderWithStore(<BenchScreen />, api());
  const first = await screen.findByTestId(`pane-${a.id}`);
  const second = screen.getByTestId(`pane-${b.id}`);
  expect(screen.getByTestId("bench")).toHaveAttribute("data-count", "2");
  expect(await within(first).findByTestId("survey-controls")).toBeInTheDocument(); // 수신 화면이 칸 안에
  expect(within(first).queryByTestId("device-picker")).toBeNull(); // 장비는 칸이 정한다
  await userEvent.click(within(second).getByTestId("pane-mode-tx"));
  expect(await within(second).findByTestId("tx-form")).toBeInTheDocument(); // 한 칸은 송신, 다른 칸은 수신
  expect(within(first).getByTestId("survey-controls")).toBeInTheDocument();
  expect(JSON.parse(sessionStorage.getItem("nrtrail.bench")!)).toEqual([{ device: a.id, mode: "rx" }, { device: b.id, mode: "tx" }]);
});

test("작업판: 칸을 닫으면 그 장비를 다시 놓을 수 있고, 송신 기능이 없으면 송신으로 바꿀 수 없다", async () => {
  sessionStorage.setItem("nrtrail.bench", JSON.stringify([{ device: a.id, mode: "rx" }, { device: b.id, mode: "rx" }]));
  renderWithStore(<BenchScreen />, api(false));
  const first = await screen.findByTestId(`pane-${a.id}`);
  expect(within(first).getByTestId("pane-mode-tx")).toBeDisabled();
  expect(screen.queryByTestId("bench-add")).toBeNull(); // 남은 장비가 없다
  await userEvent.click(within(first).getByTestId("pane-close"));
  expect(screen.queryByTestId(`pane-${a.id}`)).toBeNull();
  await userEvent.click(within(screen.getByTestId("bench-add")).getByRole("button", { name: "+ USRP B200 (S1)" }));
  expect(await screen.findByTestId(`pane-${a.id}`)).toBeInTheDocument();
});

test("작업판: 놓인 칸이 없으면 첫 화면으로 가라고 안내한다", async () => {
  const x = api();
  x.devices = async () => [];
  renderWithStore(<BenchScreen />, x);
  expect(await screen.findByText(/놓인 칸이 없습니다/)).toBeInTheDocument();
});

test("작업판: 송신 칸이 둘이면 함께 시작할 수 있고, 경고에서 두 가지를 확인해야 장비마다의 확인이 실려 나간다", async () => {
  sessionStorage.setItem("nrtrail.bench", JSON.stringify([{ device: a.id, mode: "tx" }, { device: b.id, mode: "tx" }]));
  const x = api();
  x.txStatus = async () => ({ available: true, warning_version: "v1", default_gain_db: 0, max_seconds: 30, standards: [] });
  const sent = vi.fn(async (_items: TxRequest[]) => ({ id: "g1", aligned: "host" as const, streams: [{ id: "g1-0", device: a.id, seconds: 2, stopped: false, underruns: 0 }, { id: "g1-1", device: b.id, seconds: 2, stopped: false, underruns: 3 }] }));
  x.txStartGroup = sent;
  renderWithStore(<BenchScreen />, x);
  const first = await screen.findByTestId(`pane-${a.id}`);
  const second = screen.getByTestId(`pane-${b.id}`);
  const start = await screen.findByTestId("together-start");
  expect(start).toBeDisabled(); // 주파수를 아직 안 넣었다
  await userEvent.type(await within(first).findByTestId("tx-center"), "2450");
  await userEvent.type(await within(second).findByTestId("tx-center"), "5200");
  await waitFor(() => expect(start).toBeEnabled());
  await userEvent.click(start);
  const warning = screen.getByTestId("together-warning");
  expect(within(warning).getByText("2450 MHz")).toBeInTheDocument();
  expect(within(warning).getByText("5200 MHz")).toBeInTheDocument();
  expect(screen.getByTestId("together-confirm")).toBeDisabled();
  await userEvent.click(screen.getByTestId("together-agree"));
  await userEvent.click(screen.getByTestId("together-closed"));
  await userEvent.click(screen.getByTestId("together-confirm"));
  const items = sent.mock.calls[0]![0];
  expect(items.map((i) => [i.device, i.center_hz, i.confirm?.accepted, i.confirm?.version, i.confirm?.shown.center_hz])).toEqual([
    [a.id, 2450e6, true, "v1", 2450e6],
    [b.id, 5200e6, true, "v1", 5200e6],
  ]);
  expect(await screen.findByTestId("together-done")).toHaveTextContent("끊김 3번");
});

test("작업판: 컴퓨터의 어댑터 칸에는 주변 보기가 들어가고, 송신으로는 바꿀 수 없다", async () => {
  sessionStorage.setItem("nrtrail.bench", JSON.stringify([{ device: "wifi:en0", mode: "rx", kind: "adapter" }]));
  const x = api();
  x.adapters = async () => [{ id: "wifi:en0", kind: "wifi", attach: "builtin", label: "Wi-Fi", detail: {} }];
  x.adapterWifiScan = async () => ({ adapter: "wifi:en0", networks: [], connected: null }) as never;
  renderWithStore(<BenchScreen />, x);
  const pane = await screen.findByTestId("pane-wifi:en0");
  expect(await within(pane).findByTestId("nearby-toggle")).toBeInTheDocument();
  expect(within(pane).getByTestId("pane-mode-tx")).toBeDisabled();
  expect(pane).toHaveAccessibleName("Wi-Fi · 내장");
});

test("작업판: 하나씩 보기에서는 고른 칸만 보이고 다른 칸은 숨긴 채 남아 있으며, 맨 위 줄의 이름표로 오간다", async () => {
  sessionStorage.setItem("nrtrail.bench", JSON.stringify([{ device: a.id, mode: "rx" }, { device: b.id, mode: "rx" }]));
  renderWithStore(<BenchScreen />, api());
  const first = await screen.findByTestId(`pane-${a.id}`);
  const second = screen.getByTestId(`pane-${b.id}`);
  expect(screen.getByTestId("bench")).toHaveAttribute("data-layout", "side");
  expect(screen.getByTestId("bench-stop-all")).toBeDisabled(); // 아무 칸도 받고 있지 않다
  await userEvent.click(screen.getByTestId("bench-layout-tabs"));
  expect(screen.getByTestId("bench")).toHaveAttribute("data-layout", "tabs");
  expect(first).toHaveAttribute("data-active", "true");
  expect(second).toHaveAttribute("data-active", "false"); // 숨겨질 뿐 지워지지 않는다(하던 일이 계속 돈다)
  await userEvent.click(screen.getByTestId(`bench-tab-${b.id}`));
  expect(second).toHaveAttribute("data-active", "true");
  expect(first).toHaveAttribute("data-active", "false");
});

test("작업판: 받는 칸이 있으면 이름표에 표시되고, 모두 멈추기를 누르면 그 칸의 받기가 멈춘다", async () => {
  sessionStorage.setItem("nrtrail.bench", JSON.stringify([{ device: "wifi:en0", mode: "rx", kind: "adapter" }]));
  const x = api();
  x.adapters = async () => [{ id: "wifi:en0", kind: "wifi", attach: "builtin", label: "Wi-Fi", detail: {} }];
  x.adapterWifiScan = async () => ({ adapter: "wifi:en0", networks: [], connected: null }) as never;
  renderWithStore(<BenchScreen />, x);
  const pane = await screen.findByTestId("pane-wifi:en0");
  await waitFor(() => expect(screen.getByTestId("bench-tab-wifi:en0")).toHaveAttribute("data-busy", "true")); // 주변 보기는 열자마자 되풀이해 본다
  await userEvent.click(screen.getByTestId("bench-stop-all"));
  await waitFor(() => expect(screen.getByTestId("bench-tab-wifi:en0")).toHaveAttribute("data-busy", "false"));
  expect(within(pane).getByTestId("nearby-toggle")).toHaveTextContent("계속 보기");
});
