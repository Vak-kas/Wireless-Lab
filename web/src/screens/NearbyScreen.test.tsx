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
