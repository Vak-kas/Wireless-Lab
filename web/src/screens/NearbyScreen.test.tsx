import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import type { Adapter } from "../api";
import { saveNearby } from "../devices/intent";
import { fakeApi, renderWithStore } from "../test-utils";
import { NearbyScreen } from "./NearbyScreen";

const wifi: Adapter = { id: "wifi:en0", kind: "wifi", attach: "builtin", label: "Wi-Fi", detail: { interface: "en0" } };
const bt: Adapter = { id: "bt:default", kind: "bluetooth", attach: "external", label: "Bluetooth", detail: {} };
const net = (over: object) => ({ ssid: null, bssid: null, rssi_dbm: -60, channel: 36, band: "5" as const, width_mhz: 80, freq_mhz: 5180, ...over });

function api() {
  const a = fakeApi();
  a.adapters = async () => [wifi, bt];
  a.adapterWifiScan = vi.fn(async () => ({
    device: wifi.id,
    networks: [net({ ssid: "lab-ap", bssid: "00:aa:bb:cc:dd:01" }), net({ rssi_dbm: -75 }), net({ channel: 6, band: "2.4" as const, width_mhz: 20, freq_mhz: 2437 })],
    current: { channel: 36, band: "5", width_mhz: 80, rssi_dbm: -58, noise_dbm: -90 },
    took_s: 4.2,
    names_hidden: false,
  }));
  a.adapterBleScan = vi.fn(async () => ({
    device: bt.id,
    seconds: 4,
    devices: [{ address: "id-1", name: "tag", rssi_dbm: -55, company: "", company_ids: [0x1234], services: 1, count: 7 }],
  }));
  return a;
}

beforeEach(() => sessionStorage.clear());

test("첫 화면에서 고른 Wi-Fi 어댑터로 주변 망을 대역별 그림과 표로 보여 준다", async () => {
  saveNearby(wifi.id);
  const a = api();
  renderWithStore(<NearbyScreen />, a);
  const table = await screen.findByTestId("nearby-wifi-table");
  expect(a.adapterWifiScan).toHaveBeenCalledWith(wifi.id);
  expect(within(table).getByText("lab-ap")).toBeInTheDocument();
  expect(within(table).getAllByRole("row")).toHaveLength(4);
  expect(screen.getByTestId("nearby-chart-5")).toBeInTheDocument();
  expect(screen.getByTestId("nearby-chart-2.4")).toBeInTheDocument();
  expect(screen.queryByTestId("nearby-chart-6")).not.toBeInTheDocument();
  expect(screen.getByTestId("nearby-current")).toHaveTextContent("-58");
  expect(screen.queryByTestId("nearby-hidden")).not.toBeInTheDocument();
});

test("운영체제가 이름을 가렸으면 그 사실을 알린다", async () => {
  saveNearby(wifi.id);
  const a = api();
  a.adapterWifiScan = async () => ({ device: wifi.id, networks: [net({})], current: null, took_s: 4, names_hidden: true });
  renderWithStore(<NearbyScreen />, a);
  expect(await screen.findByTestId("nearby-hidden")).toBeInTheDocument();
});

test("블루투스 어댑터로 바꾸면 광고를 들은 기기 표가 나온다", async () => {
  saveNearby(wifi.id);
  const a = api();
  renderWithStore(<NearbyScreen />, a);
  await screen.findByTestId("nearby-wifi-table");
  await userEvent.click(screen.getByRole("button", { name: /Bluetooth/ }));
  const table = await screen.findByTestId("nearby-ble-table");
  expect(a.adapterBleScan).toHaveBeenCalledWith(bt.id, 4);
  expect(within(table).getByText("tag")).toBeInTheDocument();
  expect(within(table).getByText("0x1234")).toBeInTheDocument();
  expect(screen.queryByTestId("nearby-wifi-table")).not.toBeInTheDocument();
});

test("권한이 없어 실패하면 문구를 보여 주고 되풀이를 멈춘다", async () => {
  saveNearby(bt.id);
  const a = api();
  a.adapterBleScan = vi.fn(async () => {
    throw new Error("운영체제가 블루투스 사용을 막았습니다.");
  });
  renderWithStore(<NearbyScreen />, a);
  expect(await screen.findByTestId("nearby-error")).toHaveTextContent("블루투스 사용을 막았습니다");
  await waitFor(() => expect(screen.getByTestId("nearby-toggle")).toHaveTextContent("계속 보기"));
  expect(a.adapterBleScan).toHaveBeenCalledTimes(1);
});

test("어댑터가 없으면 처음 화면으로 돌아가는 길을 준다", async () => {
  renderWithStore(<NearbyScreen />, fakeApi());
  expect(await screen.findByTestId("nearby-none")).toBeInTheDocument();
});

test("이름이 가려졌고 아직 권한을 물은 적이 없으면 '허용 요청하기'로 운영체제 창을 띄우고, 허용되면 다시 찾는다", async () => {
  saveNearby(wifi.id);
  const a = api();
  let allowed = false;
  a.adapterWifiScan = vi.fn(async () => ({
    device: wifi.id,
    networks: [net(allowed ? { ssid: "lab-ap", bssid: "00:aa:bb:cc:dd:01" } : {})],
    current: null,
    took_s: 4,
    names_hidden: !allowed,
    location: allowed ? null : ("undetermined" as const),
  }));
  a.adapterAskLocation = vi.fn(async () => {
    allowed = true;
    return { state: "authorized" };
  });
  renderWithStore(<NearbyScreen />, a);
  await userEvent.click(await screen.findByTestId("perm-ask"));
  expect(a.adapterAskLocation).toHaveBeenCalledTimes(1);
  expect(await screen.findByText("lab-ap")).toBeInTheDocument();
  expect(screen.queryByTestId("nearby-hidden")).toBeNull();
});

test("권한이 거부돼 있으면 묻는 단추 대신 설정 창을 여는 단추만 나온다", async () => {
  saveNearby(wifi.id);
  const a = api();
  a.adapterWifiScan = async () => ({ device: wifi.id, networks: [net({})], current: null, took_s: 4, names_hidden: true, location: "denied" as const });
  a.adapterOpenSettings = vi.fn(async (pane: "location" | "bluetooth") => ({ opened: pane }));
  renderWithStore(<NearbyScreen />, a);
  await userEvent.click(await screen.findByTestId("perm-open"));
  expect(screen.queryByTestId("perm-ask")).toBeNull();
  expect(a.adapterOpenSettings).toHaveBeenCalledWith("location");
  expect(await screen.findByTestId("perm-note")).toHaveTextContent("설정 창을 열었습니다");
});

test("Wi-Fi 가 잠깐 바쁜 것(409)은 멈추지 않고 계속 보고, 블루투스 권한 거부(403)는 설정 단추를 보여 준다", async () => {
  const { ApiError } = await import("../api/http");
  saveNearby(wifi.id);
  const a = api();
  a.adapterWifiScan = vi.fn(async () => {
    throw new ApiError(409, "Wi-Fi 가 지금 다른 찾기를 하고 있습니다.");
  });
  a.adapterBleScan = vi.fn(async () => {
    throw new ApiError(403, "운영체제가 블루투스 사용을 막았습니다.");
  });
  a.adapterOpenSettings = vi.fn(async (pane: "location" | "bluetooth") => ({ opened: pane }));
  renderWithStore(<NearbyScreen />, a);
  expect(await screen.findByTestId("nearby-error")).toHaveTextContent("다른 찾기");
  expect(screen.getByTestId("nearby-toggle")).toHaveTextContent("멈추기"); // 계속 보는 중
  await userEvent.click(screen.getByRole("button", { name: /Bluetooth/ }));
  await userEvent.click(await screen.findByTestId("perm-open-bt"));
  expect(a.adapterOpenSettings).toHaveBeenCalledWith("bluetooth");
  await waitFor(() => expect(screen.getByTestId("nearby-toggle")).toHaveTextContent("계속 보기"));
});
