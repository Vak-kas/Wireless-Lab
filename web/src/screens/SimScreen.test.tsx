import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import type { DeviceInfo } from "../api";
import { fakeApi, renderWithStore } from "../test-utils";
import { SimScreen } from "./SimScreen";

const usrp: DeviceInfo = { id: "usrp:B200:S1", label: "USRP B200 (S1)", driver: "uhd", stages: { scan: "ok" } };
const sim: DeviceInfo = { id: "simulated:x", label: "모의 장비 · x", driver: "simulated", stages: { scan: "ok" } };

beforeEach(() => {
  sessionStorage.clear();
  window.location.hash = "#/sim";
});

test("시뮬레이션 화면에 연습 모드, 저장 파일, 모의 장비가 모여 있고 실제 장비는 나오지 않는다", async () => {
  const api = fakeApi();
  api.devices = async () => [usrp, sim];
  renderWithStore(<SimScreen />, api);
  expect(await screen.findByTestId("source-practice")).toBeInTheDocument();
  expect(screen.getByTestId("source-file")).toBeInTheDocument();
  const mock = await screen.findByTestId("source-device");
  expect(within(mock).getByRole("button", { name: "x" })).toBeInTheDocument();
  expect(screen.queryByText(/USRP/)).toBeNull();
});

test("연습 시작을 누르면 연습 세션을 만들어 스캔 화면으로 간다", async () => {
  const api = fakeApi();
  const created = vi.spyOn(api, "createSession");
  renderWithStore(<SimScreen />, api);
  await userEvent.click(await screen.findByTestId("start-practice"));
  expect(created).toHaveBeenCalledWith({ kind: "synthetic", scenario: "x", band: undefined }, { practice: true, name: "위성 연습" });
  expect(window.location.hash).toBe("#/s/s1/scan");
});

test("저장 파일은 .sigmf-meta 가 아니면 열지 않는다", async () => {
  const api = fakeApi();
  const created = vi.spyOn(api, "createSession");
  renderWithStore(<SimScreen />, api);
  await userEvent.type(await screen.findByPlaceholderText("/path/to/capture.sigmf-meta"), "/x/y.bin");
  await userEvent.click(screen.getByTestId("start-file"));
  expect(created).not.toHaveBeenCalled();
});
