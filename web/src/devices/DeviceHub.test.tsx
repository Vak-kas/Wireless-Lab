import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { Api, DeviceInfo, DeviceSearch } from "../api";
import { fakeApi, renderWithStore } from "../test-utils";
import { DeviceHub, useUsableDevices } from "./DeviceHub";

const usrp: DeviceInfo = { id: "usrp:B200:S1", label: "USRP B200 (S1)", driver: "uhd", serial: "S1", freq_min_hz: 70e6, freq_max_hz: 6e9, max_sample_rate_hz: 56e6 };
const sim: DeviceInfo = { id: "simulated:x", label: "모의 장비 · x", driver: "simulated" };

let lastApi: Api;

function Probe() {
  const { devices, mode } = useUsableDevices();
  return <div data-testid="probe">{`${mode}:${(devices ?? []).map((d) => d.id).join(",")}`}</div>;
}

function setup(first: DeviceInfo[], search: DeviceSearch = { backends: [] }) {
  const api = fakeApi();
  let list = first;
  api.devices = async () => list;
  api.deviceSearch = async () => search;
  api.deviceRescan = vi.fn(async () => search);
  api.deviceReset = vi.fn(async () => search);
  lastApi = api;
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
  const { set } = setup([sim], { backends: [{ backend: "usrp-matlab", searching: true, found: 0, error: "", searching_for_s: 4 }] });
  expect(await screen.findByTestId("connect-searching")).toHaveTextContent("4초째");
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

test("못 찾은 이유를 알려 주고(다른 프로그램이 쓰는 중, 오류) 다시 찾을 수 있다", async () => {
  const { user } = setup([], { backends: [{ backend: "usrp-matlab", searching: false, found: 0, error: "", busy_devices: ["B200 S1: Busy"], checked_s_ago: 3 }] });
  expect(await screen.findByTestId("search-busy")).toHaveTextContent("B200 S1: Busy");
  await user.click(screen.getByTestId("search-rescan"));
  expect(lastApi.deviceRescan).toHaveBeenCalled();
  await user.click(screen.getByTestId("search-reset")); // 그래도 안 되면 연결을 처음부터 다시
  expect(lastApi.deviceReset).toHaveBeenCalled();
});

test("찾기가 실패하면 오류 내용을, 그냥 없으면 언제 확인했는지를 보여 준다", async () => {
  setup([], { backends: [{ backend: "usrp-matlab", searching: false, found: 0, error: "RuntimeError: MATLAB 을 띄우지 못했다", checked_s_ago: 2 }] });
  expect(await screen.findByTestId("search-error")).toHaveTextContent("MATLAB 을 띄우지 못했다");
});

test("SDR 이 없어도 컴퓨터의 어댑터가 있으면 연결 창에 보이고 그것으로 시작할 수 있다. 장비 없이 시작해도 어댑터는 남는다", async () => {
  const api = fakeApi();
  api.devices = async () => [sim];
  api.adapters = async () => [{ id: "wifi:en0", kind: "wifi", attach: "builtin", label: "Wi-Fi", detail: { interface: "en0" } }];
  function AdapterProbe() {
    const { adapters, mode } = useUsableDevices();
    return <div data-testid="aprobe">{`${mode}:${adapters.map((a) => a.id).join(",")}`}</div>;
  }
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  renderWithStore(
    <DeviceHub>
      <AdapterProbe />
    </DeviceHub>,
    api,
  );
  const dialog = await screen.findByRole("dialog", { name: "장비를 연결하세요" });
  const card = await within(dialog).findByTestId("adapter-card-wifi:en0");
  expect(within(card).getByText("내장")).toBeInTheDocument();
  const start = within(dialog).getByTestId("connect-start");
  expect(start).toBeEnabled();
  expect(start).toHaveTextContent("이 컴퓨터의 장비로 시작");
  await user.click(start);
  expect(screen.getByTestId("aprobe")).toHaveTextContent("device:wifi:en0");
  expect(screen.getByTestId("my-devices-button")).toHaveTextContent("1");

  await user.click(screen.getByTestId("my-devices-button"));
  await user.click(screen.getByTestId("my-devices-connect"));
  await user.click(screen.getByTestId("connect-skip"));
  expect(screen.getByTestId("aprobe")).toHaveTextContent("none:wifi:en0");
  expect(screen.getByTestId("my-devices-button")).toHaveTextContent("1");
  await user.click(screen.getByTestId("my-devices-button"));
  expect(within(screen.getByTestId("my-devices")).getByTestId("adapter-card-wifi:en0")).toBeInTheDocument();
});

test("어댑터 카드는 할 수 있는 일을 보여 준다: 대역·규격은 값으로, 모니터 모드는 되는지 여부로", async () => {
  const { AdapterCard } = await import("./DeviceHub");
  renderWithStore(
    <AdapterCard
      adapter={{
        id: "wifi:en0",
        kind: "wifi",
        attach: "external",
        label: "Wi-Fi",
        detail: { interface: "en0" },
        abilities: [
          { id: "scan", state: "yes" },
          { id: "bands", value: "2.4 / 5 GHz" },
          { id: "monitor", state: "yes" },
          { id: "capture", state: "admin" },
        ],
      }}
    />,
  );
  const list = screen.getByTestId("abilities-wifi:en0");
  expect(within(list).getByTestId("ability-bands")).toHaveTextContent("대역 2.4 / 5 GHz");
  expect(within(list).getByTestId("ability-monitor")).toHaveTextContent("모니터 모드 됨");
  expect(within(list).getByTestId("ability-capture")).toHaveTextContent("관리자 권한 필요");
  expect(screen.getByText(/모니터 모드로 프레임을 읽는 기능은 아직 없습니다/)).toBeInTheDocument();
});

test("모니터 모드를 지원하지 않는 어댑터에는 그 안내가 나오지 않는다", async () => {
  const { AdapterCard } = await import("./DeviceHub");
  renderWithStore(<AdapterCard adapter={{ id: "wifi:x", kind: "wifi", attach: "builtin", label: "Wi-Fi", detail: {}, abilities: [{ id: "monitor", state: "no" }] }} />);
  expect(screen.getByTestId("ability-monitor")).toHaveTextContent("모니터 모드 안 됨");
  expect(screen.queryByText(/아직 없습니다/)).toBeNull();
});

const linuxWifi = {
  id: "wifi:wlan1",
  kind: "wifi" as const,
  attach: "external" as const,
  label: "Wi-Fi",
  detail: { interface: "wlan1" },
  mode: "managed",
  mode_switch: { how: "pkexec" as const, to_monitor: ["nmcli device set wlan1 managed no", "sudo iw dev wlan1 set type monitor"], to_managed: ["sudo iw dev wlan1 set type managed"] },
};

test("모드 전환: 실행될 명령과 영향을 보여 주고, 확인을 표시해야 바뀐다. 바뀐 뒤에는 되돌리기 단추가 된다", async () => {
  const { ModeSwitch } = await import("./DeviceHub");
  const api = fakeApi();
  api.adapterSetMode = vi.fn(async (_d: string, mode: string) => ({ device: "wifi:wlan1", mode, changed: true }));
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  renderWithStore(<ModeSwitch adapter={linuxWifi} />, api);
  expect(screen.getByTestId("mode-now")).toHaveTextContent("지금 모드 일반 (연결용)");
  await user.click(screen.getByTestId("mode-ask"));
  const dialog = screen.getByRole("alertdialog", { name: "모니터 모드로 바꿀까요?" });
  expect(within(dialog).getByTestId("mode-commands")).toHaveTextContent("sudo iw dev wlan1 set type monitor");
  expect(within(dialog).getByText(/이 도구는 암호를 받지 않습니다/)).toBeInTheDocument();
  expect(within(dialog).getByText(/인터넷을 쓰고 있었다면 끊깁니다/)).toBeInTheDocument();
  expect(screen.getByTestId("mode-confirm")).toBeDisabled();
  expect(api.adapterSetMode).not.toHaveBeenCalled();
  await user.click(screen.getByTestId("mode-agree"));
  await user.click(screen.getByTestId("mode-confirm"));
  await waitFor(() => expect(api.adapterSetMode).toHaveBeenCalledWith("wifi:wlan1", "monitor", true));
  await waitFor(() => expect(screen.getByTestId("mode-now")).toHaveTextContent("지금 모드 모니터"));
  expect(screen.queryByTestId("mode-dialog")).toBeNull();
  expect(screen.getByTestId("mode-ask")).toHaveTextContent("일반 모드로 되돌리기");
});

test("모드 전환: 실패하면 창 안에 이유가 나오고, 인증 창을 못 쓰는 경우에는 명령만 보여 준다", async () => {
  const { ModeSwitch } = await import("./DeviceHub");
  const api = fakeApi();
  api.adapterSetMode = vi.fn(async () => {
    throw new Error("인증이 취소됐습니다.");
  });
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  const view = renderWithStore(<ModeSwitch adapter={linuxWifi} />, api);
  await user.click(screen.getByTestId("mode-ask"));
  await user.click(screen.getByTestId("mode-agree"));
  await user.click(screen.getByTestId("mode-confirm"));
  expect(await screen.findByTestId("mode-error")).toHaveTextContent("인증이 취소됐습니다.");
  expect(screen.getByTestId("mode-now")).toHaveTextContent("일반 (연결용)");
  view.unmount();
  renderWithStore(<ModeSwitch adapter={{ ...linuxWifi, mode_switch: { ...linuxWifi.mode_switch, how: "manual" } }} />, api);
  await user.click(screen.getByTestId("mode-ask"));
  expect(screen.getByText(/터미널에서 아래 명령을 직접 실행하세요/)).toBeInTheDocument();
  expect(screen.queryByTestId("mode-confirm")).toBeNull();
});

test("모드 전환: macOS 에서는 단추 대신 이유를 알려 준다", async () => {
  const { ModeSwitch } = await import("./DeviceHub");
  renderWithStore(<ModeSwitch adapter={{ ...linuxWifi, id: "wifi:en0", mode: null, mode_switch: { how: "no", reason: "macos" } }} />);
  expect(screen.getByTestId("mode-note-wifi:en0")).toHaveTextContent("받는 동안에만 모니터 모드가 켜지는 방식");
  expect(screen.queryByTestId("mode-ask")).toBeNull();
});

test("잠긴 장비(Pro 필요)는 연결 창에 보이지만, 화면들이 쓰는 장비 목록에는 들어가지 않는다", async () => {
  const lockedUsrp: DeviceInfo = { id: "locked:usrp:S9", label: "USRP B200mini (S9)", driver: "uhd", serial: "S9", needs: "pro" };
  function LockProbe() {
    const { devices, locked } = useUsableDevices();
    return <div data-testid="lprobe">{`${(devices ?? []).map((d) => d.id).join(",")}|${locked.map((d) => d.id).join(",")}`}</div>;
  }
  const api = fakeApi();
  api.devices = async () => [lockedUsrp, sim];
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  renderWithStore(
    <DeviceHub>
      <LockProbe />
    </DeviceHub>,
    api,
  );
  const dialog = await screen.findByRole("dialog", { name: "장비를 연결하세요" });
  expect(await within(dialog).findByTestId("needs-pro-locked:usrp:S9")).toBeInTheDocument();
  await user.click(within(dialog).getByTestId("connect-start"));
  expect(screen.getByTestId("lprobe")).toHaveTextContent("simulated:x|locked:usrp:S9");
});
