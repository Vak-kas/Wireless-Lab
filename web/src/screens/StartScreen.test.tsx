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

test("첫 화면은 내 장비와 수신·송신·시나리오만 보여 주고, 연습·파일·모의 장비는 시뮬레이션 화면으로 가는 단추 뒤에 있다", async () => {
  const api = fakeApi();
  api.devices = async () => [usrp, sim];
  renderWithStore(<StartScreen />, api);
  const card = await screen.findByTestId("home-device-usrp:B200:S1");
  expect(within(card).getByText("USRP B200")).toBeInTheDocument();
  expect(within(card).getByText("S1")).toBeInTheDocument();
  expect(within(card).getByTestId("home-pick-usrp:B200:S1")).toHaveAttribute("aria-pressed", "true");
  for (const id of ["rx", "nr"]) expect(screen.getByTestId(`task-${id}`)).toBeEnabled();
  expect(screen.getByTestId("task-tx")).toBeDisabled(); // 송신 기능이 없는 설치에서는 꺼져 있다
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

test("수신을 누르면 고른 장비마다 칸이 놓인 작업판으로 가고, 표시를 끈 장비는 빠진다. 기지국 따라가기는 고른 첫 장비로 세션을 연다", async () => {
  const api = fakeApi();
  const second: DeviceInfo = { ...usrp, id: "usrp:B210:S2", label: "USRP B210 (S2)", serial: "S2" };
  api.devices = async () => [usrp, second];
  const created = vi.spyOn(api, "createSession");
  renderWithStore(<StartScreen />, api);
  await userEvent.click(await screen.findByTestId("task-rx"));
  expect(window.location.hash).toBe("#/bench");
  expect(JSON.parse(sessionStorage.getItem("nrtrail.bench")!)).toEqual([
    { device: "usrp:B200:S1", mode: "rx" },
    { device: "usrp:B210:S2", mode: "rx" },
  ]);
  await userEvent.click(screen.getByTestId("home-pick-usrp:B200:S1"));
  await userEvent.click(screen.getByTestId("task-rx"));
  expect(JSON.parse(sessionStorage.getItem("nrtrail.bench")!)).toEqual([{ device: "usrp:B210:S2", mode: "rx" }]);
  await userEvent.click(screen.getByTestId("task-nr"));
  await waitFor(() => expect(created).toHaveBeenCalled());
  expect(created.mock.calls[0]?.[0]).toEqual({ kind: "device", device: "usrp:B210:S2", device_label: "USRP B210 (S2)" });
  await waitFor(() => expect(window.location.hash).toBe("#/s/s1/scan"));
  await userEvent.click(screen.getByTestId("home-pick-usrp:B210:S2"));
  expect(screen.getByTestId("task-rx")).toBeDisabled(); // 고른 장비가 없으면 들어갈 수 없다
});

test("장비가 없으면 연결하라고 안내하고, 시뮬레이션으로 가는 단추는 그대로 쓸 수 있다", async () => {
  const api = fakeApi();
  api.devices = async () => [sim];
  renderWithStore(<StartScreen />, api);
  const none = await screen.findByTestId("home-no-device");
  expect(none).toHaveTextContent("장비를 확인하는 중"); // 찾기 상태를 아직 못 받았을 때는 "없다"고 하지 않는다
  expect(within(none).getByTestId("search-rescan")).toBeEnabled(); // 다시 찾기는 언제나 누를 수 있다
  expect(screen.queryByTestId("task-nr")).toBeNull();
  expect(screen.getByTestId("home-sim")).toBeEnabled(); // 시뮬레이션 화면으로 가는 길은 남아 있다
});

test("SDR 이 없을 때: 컴퓨터의 Wi-Fi·블루투스 어댑터가 쓸 장비로 나오고, 수신을 누르면 주변 보기 칸이 놓인다", async () => {
  const api = fakeApi();
  api.devices = async () => [];
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
  // SDR 이 없으면 어댑터가 처음부터 "사용"이다. 수신을 누르면 어댑터마다 칸이 놓인다(어댑터는 받기만 한다)
  expect(within(wifi).getByTestId("home-pick-wifi:en0")).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("task-tx")).toBeDisabled();
  await userEvent.click(within(bt).getByTestId("home-pick-bt:usb"));
  await userEvent.click(screen.getByTestId("task-rx"));
  expect(window.location.hash).toBe("#/bench");
  expect(JSON.parse(sessionStorage.getItem("nrtrail.bench")!)).toEqual([{ device: "wifi:en0", mode: "rx", kind: "adapter" }]);
});

test("SDR 이 있으면 컴퓨터의 어댑터는 같은 목록에 나오되 처음에는 꺼져 있고, 켜면 수신 칸에 함께 놓인다", async () => {
  const api = fakeApi();
  api.devices = async () => [usrp];
  api.adapters = async () => [{ id: "wifi:en0", kind: "wifi", attach: "builtin", label: "Wi-Fi", detail: {} }];
  renderWithStore(<StartScreen />, api);
  const pick = await screen.findByTestId("home-pick-wifi:en0");
  expect(pick).toHaveAttribute("aria-pressed", "false");
  expect(pick).toHaveTextContent("사용 안 함");
  await userEvent.click(pick);
  expect(pick).toHaveTextContent("사용");
  await userEvent.click(screen.getByTestId("task-rx"));
  expect(JSON.parse(sessionStorage.getItem("nrtrail.bench")!)).toEqual([
    { device: "usrp:B200:S1", mode: "rx" },
    { device: "wifi:en0", mode: "rx", kind: "adapter" },
  ]);
});

test("알아봤지만 쓸 수 없는 장비는 'Pro 필요' 카드로 보이고, 할 일은 전부 꺼져 있다", async () => {
  const api = fakeApi();
  const lockedUsrp: DeviceInfo = { id: "locked:usrp:S9", label: "USRP B200mini (S9)", driver: "uhd", serial: "S9", needs: "pro" };
  api.devices = async () => [lockedUsrp];
  renderWithStore(<StartScreen />, api);
  const card = await screen.findByTestId("home-locked-locked:usrp:S9");
  expect(within(card).getByText("Pro 필요")).toBeInTheDocument();
  expect(within(card).getByTestId("needs-pro-locked:usrp:S9")).toHaveTextContent("이 장비를 사용하려면 Pro 판이 필요합니다");
  for (const id of ["rx", "tx", "nr"]) expect(within(card).getByTestId(`task-${id}`)).toBeDisabled();
  // 쓸 수 있는 장비 카드로는 나오지 않고, "장비가 없습니다" 안내도 뜨지 않는다
  expect(screen.queryByTestId("home-device-locked:usrp:S9")).toBeNull();
  expect(screen.queryByTestId("home-no-device")).toBeNull();
});
