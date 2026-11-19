import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import type { Adapter, DeviceInfo } from "../api";
import { fakeApi, renderWithStore } from "../test-utils";
import { DeviceHub } from "../devices/DeviceHub";
import { StartScreen } from "./StartScreen";

const usrp: DeviceInfo = { id: "usrp:B200:S1", label: "USRP B200 (S1)", driver: "uhd", serial: "S1", freq_min_hz: 70e6, freq_max_hz: 6e9, stages: { scan: "ok" } };
const sim: DeviceInfo = { id: "simulated:x", label: "모의 장비 · x", driver: "simulated", stages: { scan: "ok" } };

beforeEach(() => {
  sessionStorage.clear();
  window.location.hash = "#/";
});

test("첫 화면은 내 장비와 '이 장비로 할 일'만 보여 주고, 연습·파일·모의 장비는 시뮬레이션 화면으로 가는 단추 뒤에 있다", async () => {
  const api = fakeApi();
  api.devices = async () => [usrp, sim];
  renderWithStore(<StartScreen />, api);
  const card = await screen.findByTestId("home-device-usrp:B200:S1");
  expect(within(card).getByText("USRP B200")).toBeInTheDocument();
  expect(within(card).getByText("S1")).toBeInTheDocument();
  for (const id of ["nr", "wifi", "view", "bt"]) expect(within(card).getByTestId(`task-${id}`)).toBeEnabled();
  expect(within(card).getByTestId("task-tx")).toBeDisabled(); // 송신 기능이 없는 설치에서는 꺼져 있다
  expect(within(card).queryByText(/모의 장비/)).toBeNull();

  for (const id of ["source-practice", "source-file", "source-device"]) expect(screen.queryByTestId(id)).toBeNull();
  await userEvent.click(screen.getByTestId("home-sim"));
  expect(window.location.hash).toBe("#/sim");
});

test("Pro 가 없는 설치(USRP 를 찾는 쪽이 없음)에서는 장비 칸에 Pro 안내가 나온다", async () => {
  const api = fakeApi();
  api.devices = async () => [];
  function Hubbed() {
    return (
      <DeviceHub>
        <StartScreen />
      </DeviceHub>
    );
  }
  sessionStorage.setItem("nrtrail.deviceMode", "device");
  renderWithStore(<Hubbed />, api);
  expect(await screen.findByTestId("home-pro-hint")).toHaveTextContent("Pro 에 있습니다");
});

test("할 일: 'Wi-Fi 보기'는 그 장비와 5 GHz 를 골라 주파수 화면으로, '기지국 따라가기'는 그 장비로 세션을 연다", async () => {
  const api = fakeApi();
  api.devices = async () => [usrp];
  const created = vi.spyOn(api, "createSession");
  renderWithStore(<StartScreen />, api);
  await userEvent.click(await screen.findByTestId("task-wifi"));
  expect(window.location.hash).toBe("#/spectrum");
  expect(JSON.parse(sessionStorage.getItem("nrtrail.spectrumIntent")!)).toEqual({ device: "usrp:B200:S1", plan: "wifi-5g" });
  await userEvent.click(screen.getByTestId("task-bt"));
  expect(JSON.parse(sessionStorage.getItem("nrtrail.spectrumIntent")!)).toEqual({ device: "usrp:B200:S1", plan: "ble" });
  await userEvent.click(screen.getByTestId("task-view"));
  expect(JSON.parse(sessionStorage.getItem("nrtrail.spectrumIntent")!)).toEqual({ device: "usrp:B200:S1", focus: "view" });
  await userEvent.click(screen.getByTestId("task-nr"));
  await waitFor(() => expect(created).toHaveBeenCalled());
  expect(created.mock.calls[0]?.[0]).toEqual({ kind: "device", device: "usrp:B200:S1", device_label: "USRP B200 (S1)" });
  await waitFor(() => expect(window.location.hash).toBe("#/s/s1/scan"));
});

test("장비가 없으면 연결하라고 안내하고, 시뮬레이션으로 가는 단추는 그대로 쓸 수 있다", async () => {
  const api = fakeApi();
  api.devices = async () => [sim];
  renderWithStore(<StartScreen />, api);
  expect(await screen.findByTestId("home-no-device")).toHaveTextContent("연결된 장비가 없습니다");
  expect(screen.queryByTestId("task-nr")).toBeNull();
  expect(screen.getByTestId("home-sim")).toBeEnabled(); // 시뮬레이션 화면으로 가는 길은 남아 있다
});

test("컴퓨터의 Wi-Fi·블루투스 어댑터는 내장/외장 표시와 함께 따로 나오고, 누르면 주변 보기로 간다", async () => {
  const api = fakeApi();
  api.devices = async () => [usrp];
  const found: Adapter[] = [
    { id: "wifi:en0", kind: "wifi", attach: "builtin", label: "Wi-Fi", detail: { interface: "en0" }, abilities: [{ id: "monitor", state: "yes" }] },
    { id: "bt:usb", kind: "bluetooth", attach: "external", label: "Bluetooth", detail: {} },
  ];
  api.adapters = async () => found;
  renderWithStore(<StartScreen />, api);
  const wifi = await screen.findByTestId("home-adapter-wifi:en0");
  expect(within(wifi).getByText("내장")).toBeInTheDocument();
  const bt = screen.getByTestId("home-adapter-bt:usb");
  expect(within(bt).getByText("외장")).toBeInTheDocument();
  expect(within(bt).getByTestId("task-near-bt")).toBeEnabled();
  // SDR 장비의 할 일(스펙트럼·송신)은 어댑터 카드에 없다
  // 모니터 모드를 지원하는 어댑터에는 그 칸이 "준비 중"으로 보인다(아직 누를 수 없다)
  expect(within(wifi).getByTestId("task-monitor")).toBeDisabled();
  expect(within(bt).queryByTestId("task-monitor")).toBeNull();
  expect(within(wifi).queryByTestId("task-view")).toBeNull();
  expect(within(wifi).queryByTestId("task-tx")).toBeNull();
  await userEvent.click(within(wifi).getByTestId("task-near-wifi"));
  expect(window.location.hash).toBe("#/nearby");
  expect(sessionStorage.getItem("nrtrail.nearbyAdapter")).toBe("wifi:en0");
});

test("알아봤지만 쓸 수 없는 장비는 'Pro 필요' 카드로 보이고, 할 일은 전부 꺼져 있다", async () => {
  const api = fakeApi();
  const lockedUsrp: DeviceInfo = { id: "locked:usrp:S9", label: "USRP B200mini (S9)", driver: "uhd", serial: "S9", needs: "pro" };
  api.devices = async () => [lockedUsrp];
  renderWithStore(<StartScreen />, api);
  const card = await screen.findByTestId("home-locked-locked:usrp:S9");
  expect(within(card).getByText("Pro 필요")).toBeInTheDocument();
  expect(within(card).getByTestId("needs-pro-locked:usrp:S9")).toHaveTextContent("이 장비를 사용하려면 Pro 판이 필요합니다");
  for (const id of ["nr", "wifi", "view", "bt", "tx"]) expect(within(card).getByTestId(`task-${id}`)).toBeDisabled();
  // 쓸 수 있는 장비 카드로는 나오지 않고, "장비가 없습니다" 안내도 뜨지 않는다
  expect(screen.queryByTestId("home-device-locked:usrp:S9")).toBeNull();
  expect(screen.queryByTestId("home-no-device")).toBeNull();
});
