import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { RelayRecv, RelayState, RelayTarget } from "../api";
import { fakeApi as api, renderWithStore } from "../test-utils";
import { RelayReceive } from "./RelayReceive";

const FROM: RelayTarget = { host: "relay.example", port: 443, tls: true, room: "abc", prefix: "/relay/ws", token_set: true, url: "wss://relay.example:443/relay/ws/abc/iq/recv" };
const BASE: RelayState = { available: true, target: null, job: null, recv_target: null, recv: null };
const RECV: RelayRecv = {
  running: true,
  error: "",
  note: "",
  to: FROM.url,
  record: true,
  sending: true,
  signal: { format: "sc16", sample_rate_hz: 1e6, center_hz: 433.92e6, source: "device", name: "B200mini" },
  bytes: 8e6,
  seconds: 2,
  gaps: 1,
  lost_samples: 40,
  files: [{ meta_path: "/s/x-relay.sigmf-meta", data_path: "/s/x-relay.sigmf-data", bytes: 8e6, seconds: 2, gaps: 1, full: false, done: false }],
  view: null,
};

test("서버에 이 기능이 없으면 아무것도 그리지 않는다", async () => {
  const { container } = renderWithStore(<RelayReceive onOpen={vi.fn()} />, api());
  await Promise.resolve();
  expect(container.querySelector("[data-testid=relay-recv]")).toBeNull();
});

test("받을 곳을 정하고 받기 시작하면 오는 신호의 조건과 받은 양이 보이고, 멈춘 뒤 남긴 파일을 분석으로 넘긴다", async () => {
  const a = api();
  a.relayState = vi.fn(async () => BASE);
  a.relayRecvTarget = vi.fn(async () => ({ ...BASE, recv_target: FROM }));
  a.relayRecvStart = vi.fn(async () => ({ ...BASE, recv_target: FROM, recv: RECV }));
  a.relayRecvStop = vi.fn(async () => ({ ...BASE, recv_target: FROM, recv: { ...RECV, running: false, sending: false, files: [{ ...RECV.files[0]!, done: true }] } }));
  const onOpen = vi.fn();
  renderWithStore(<RelayReceive onOpen={onOpen} />, a);
  expect(await screen.findByTestId("relay-recv")).toHaveTextContent("중계 서버에서 받기받을 곳을 아직 정하지 않았습니다");
  expect(screen.queryByTestId("relay-recv-start")).toBeNull(); // 받을 곳이 없으면 받는 단추도 없다
  await userEvent.click(screen.getByTestId("relay-recv-edit"));
  await userEvent.type(screen.getByTestId("relay-recv-link"), "wss://relay.example/relay/ws/abc/iq/recv?token=t");
  await userEvent.click(screen.getByTestId("relay-recv-save"));
  expect(a.relayRecvTarget).toHaveBeenCalledWith({ link: "wss://relay.example/relay/ws/abc/iq/recv?token=t" });
  expect(await screen.findByText(FROM.url)).toBeInTheDocument();

  await userEvent.click(screen.getByTestId("relay-recv-record"));
  await userEvent.click(screen.getByTestId("relay-recv-record"));
  await userEvent.click(screen.getByTestId("relay-recv-start"));
  expect(a.relayRecvStart).toHaveBeenCalledWith(true);
  expect(await screen.findByTestId("relay-recv-status")).toHaveTextContent("오는 중 2.0 s · 8.0 MB · 빠진 곳 1군데 (샘플 40개)");
  expect(screen.getByTestId("relay-recv-signal")).toHaveTextContent("가운데 433.920 MHz · 1 MS/s · sc16 · B200mini · 지금 받는 신호");
  expect(screen.getByTestId("relay-recv-open")).toBeDisabled(); // 쓰는 중인 파일은 아직 열지 않는다
  expect(screen.getByTestId("relay-recv-edit")).toBeDisabled();

  await userEvent.click(screen.getByTestId("relay-recv-stop"));
  expect(await screen.findByTestId("relay-recv-start")).toBeInTheDocument();
  expect(screen.getByTestId("relay-recv-status")).toHaveTextContent("멈춤");
  await userEvent.click(screen.getByTestId("relay-recv-open"));
  expect(onOpen).toHaveBeenCalledWith("/s/x-relay.sigmf-meta");
});

test("보내는 쪽이 아직 없으면 기다린다고 말하고, 서버가 거절하면 이유를 보여 준다", async () => {
  const a = api();
  a.relayState = vi.fn(async () => ({ ...BASE, recv_target: FROM, recv: { ...RECV, sending: false, signal: null, bytes: 0, seconds: 0, gaps: 0, files: [] } }));
  a.relayRecvStop = vi.fn(async () => {
    throw new Error("방이 없거나 토큰이 맞지 않습니다.");
  });
  renderWithStore(<RelayReceive onOpen={vi.fn()} />, a);
  expect(await screen.findByTestId("relay-recv-status")).toHaveTextContent("보내는 쪽을 기다리는 중");
  expect(screen.queryByTestId("relay-recv-signal")).toBeNull();
  await userEvent.click(screen.getByTestId("relay-recv-stop"));
  expect(await screen.findByRole("alert")).toHaveTextContent("토큰");
});
