import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { DeviceInfo } from "../api";
import { fakeApi, renderWithStore } from "../test-utils";
import { DeviceHub, useUsableDevices } from "./DeviceHub";

const usrp: DeviceInfo = { id: "usrp:B200:S1", label: "USRP B200 (S1)", driver: "uhd", serial: "S1", freq_min_hz: 70e6, freq_max_hz: 6e9, max_sample_rate_hz: 56e6 };
const sim: DeviceInfo = { id: "simulated:x", label: "모의 장비 · x", driver: "simulated" };

function Probe() {
  const { devices, mode } = useUsableDevices();
  return <div data-testid="probe">{`${mode}:${(devices ?? []).map((d) => d.id).join(",")}`}</div>;
}

function setup(first: DeviceInfo[]) {
  const api = fakeApi();
  let list = first;
  api.devices = async () => list;
  renderWithStore(
    <DeviceHub>
      <Probe />
    </DeviceHub>,
    api,
  );
  return {
    set: async (next: DeviceInfo[]) => {
      list = next;
      await act(() => vi.advanceTimersByTimeAsync(5100));
    },
    user: userEvent.setup({ advanceTimers: vi.advanceTimersByTime }),
  };
}

beforeEach(() => {
  sessionStorage.clear();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});
afterEach(() => vi.useRealTimers());

test("처음 열면 장비 연결 창이 뜨고, 찾은 장비를 카드(이름·일련번호)로 보여 준다", async () => {
  const { user } = setup([usrp, sim]);
  const dialog = await screen.findByRole("dialog", { name: "장비를 연결하세요" });
  const card = await within(dialog).findByTestId("device-card-usrp:B200:S1");
  expect(within(card).getByText("USRP B200")).toBeInTheDocument();
  expect(within(card).getByText("S1")).toBeInTheDocument();
  expect(within(card).getByText("70 ~ 6000 MHz")).toBeInTheDocument();
  expect(within(dialog).queryByText(/모의 장비/)).toBeNull(); // 연결 창에는 실제 장비만
  await user.click(screen.getByTestId("connect-start"));
  expect(screen.queryByRole("dialog", { name: "장비를 연결하세요" })).toBeNull();
  expect(screen.getByTestId("probe")).toHaveTextContent("device:usrp:B200:S1,simulated:x");
  expect(sessionStorage.getItem("nrtrail.deviceMode")).toBe("device");
});

test("장비가 없으면 찾는 중이라고 알리고 시작 단추를 막는다. 창이 떠 있는 동안 꽂으면 바로 나타난다", async () => {
  const { set } = setup([sim]);
  expect(await screen.findByTestId("connect-searching")).toBeInTheDocument();
  expect(screen.getByTestId("connect-start")).toBeDisabled();
  await set([usrp, sim]);
  expect(await screen.findByTestId("device-card-usrp:B200:S1")).toBeInTheDocument();
  expect(screen.getByTestId("connect-start")).toBeEnabled();
  expect(screen.queryByTestId("device-arrived")).toBeNull(); // 창에서 이미 보이므로 따로 알리지 않는다
});

test("장비 없이 시작하면 실제 장비는 화면에 넘기지 않고, 나중에 꽂으면 알림에서 바로 쓸 수 있다", async () => {
  const { set, user } = setup([sim]);
  await user.click(await screen.findByTestId("connect-skip"));
  expect(screen.getByTestId("probe")).toHaveTextContent("none:simulated:x");
  expect(screen.getByTestId("my-devices-button")).toHaveTextContent("0");

  await set([usrp, sim]);
  const toast = await screen.findByTestId("device-arrived");
  expect(within(toast).getByText("새로운 장비가 등록되었습니다")).toBeInTheDocument();
  expect(within(toast).getByText("S1")).toBeInTheDocument();
  expect(screen.getByTestId("probe")).toHaveTextContent("none:simulated:x"); // 아직은 장비 없이
  await user.click(screen.getByTestId("arrived-use"));
  expect(screen.queryByTestId("device-arrived")).toBeNull();
  expect(screen.getByTestId("probe")).toHaveTextContent("device:usrp:B200:S1,simulated:x");
});

test("내 장비 단추: 누르면 장비 카드가 펼쳐지고, 연결 창을 다시 열 수 있다. 같은 창에서는 다시 묻지 않는다", async () => {
  sessionStorage.setItem("nrtrail.deviceMode", "device");
  const { set, user } = setup([usrp]);
  await waitFor(() => expect(screen.getByTestId("my-devices-button")).toHaveTextContent("1"));
  expect(screen.queryByTestId("connect-overlay")).toBeNull();
  expect(screen.queryByTestId("device-arrived")).toBeNull(); // 처음부터 있던 장비는 알리지 않는다
  await user.click(screen.getByTestId("my-devices-button"));
  expect(within(screen.getByTestId("my-devices")).getByText("S1")).toBeInTheDocument();

  await set([]); // 뽑으면 목록에서 사라진다
  expect(within(screen.getByTestId("my-devices")).getByText("연결된 장비가 없습니다.")).toBeInTheDocument();
  await set([usrp]); // 다시 꽂으면 알린다
  expect(await screen.findByTestId("device-arrived")).toBeInTheDocument();
  await user.click(screen.getByTestId("arrived-ok"));
  expect(screen.queryByTestId("device-arrived")).toBeNull();

  await user.click(screen.getByTestId("my-devices-connect"));
  expect(screen.getByRole("dialog", { name: "장비를 연결하세요" })).toBeInTheDocument();
});
