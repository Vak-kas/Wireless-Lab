import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import type { DeviceInfo } from "../api";
import { fakeApi, renderWithStore } from "../test-utils";
import { StartScreen } from "./StartScreen";

const usrp: DeviceInfo = { id: "usrp:B200:S1", label: "USRP B200 (S1)", driver: "uhd", serial: "S1", freq_min_hz: 70e6, freq_max_hz: 6e9, stages: { scan: "ok" } };
const sim: DeviceInfo = { id: "simulated:x", label: "모의 장비 · x", driver: "simulated", stages: { scan: "ok" } };

beforeEach(() => {
  sessionStorage.clear();
  window.location.hash = "#/";
});

test("첫 화면은 내 장비와 '이 장비로 할 일'로 시작하고, 연습·파일·모의 장비는 '장비 없이 해 보기'에 있다", async () => {
  const api = fakeApi();
  api.devices = async () => [usrp, sim];
  renderWithStore(<StartScreen />, api);
  const card = await screen.findByTestId("home-device-usrp:B200:S1");
  expect(within(card).getByText("USRP B200")).toBeInTheDocument();
  expect(within(card).getByText("S1")).toBeInTheDocument();
  for (const id of ["nr", "wifi", "view", "bt"]) expect(within(card).getByTestId(`task-${id}`)).toBeEnabled();
  expect(within(card).getByTestId("task-tx")).toBeDisabled(); // 송신 기능이 없는 설치에서는 꺼져 있다
  expect(within(card).queryByText(/모의 장비/)).toBeNull();

  expect(screen.getByRole("heading", { name: "저장해 둔 신호로 연습하기" })).toBeInTheDocument();
  expect(screen.getByTestId("source-practice")).toBeInTheDocument();
  expect(screen.getByTestId("source-file")).toBeInTheDocument();
  expect(within(screen.getByTestId("source-device")).getByRole("button", { name: "x" })).toBeInTheDocument();
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

test("장비가 없으면 연결하라고 안내하고, 장비 없이 하는 구역은 그대로 쓸 수 있다", async () => {
  const api = fakeApi();
  api.devices = async () => [sim];
  renderWithStore(<StartScreen />, api);
  expect(await screen.findByTestId("home-no-device")).toHaveTextContent("연결된 장비가 없습니다");
  expect(screen.queryByTestId("task-nr")).toBeNull();
  expect(screen.getByTestId("start-practice")).toBeInTheDocument();
});
