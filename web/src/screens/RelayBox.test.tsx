import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { RelayState, RelayTarget } from "../api";
import { StoreProvider } from "../state/store";
import { fakeApi as api, renderWithStore } from "../test-utils";
import { RelayBox } from "./RelayBox";

const TARGET: RelayTarget = {
  host: "relay.example",
  port: 443,
  tls: true,
  room: "abc",
  prefix: "/relay/ws",
  token_set: true,
  url: "wss://relay.example:443/relay/ws/abc/iq/send",
};
const NONE: RelayState = { available: true, target: null, job: null };
const SET: RelayState = { available: true, target: TARGET, job: null };

test("서버에 이 기능이 없으면 아무것도 그리지 않는다", async () => {
  const { container } = renderWithStore(
    <RelayBox file="/s/a.sigmf-meta" />,
    api(),
  );
  await Promise.resolve();
  expect(container.querySelector("[data-testid=relay-box]")).toBeNull();
});

test("보낼 곳을 한 줄로 붙여 넣거나 칸마다 적어 정하고, 연결을 확인한다", async () => {
  const a = api();
  a.relayState = vi.fn(async () => NONE);
  a.relayTarget = vi.fn(async () => SET);
  a.relayCheck = vi.fn(async () => ({
    ok: true,
    rate_limit: 16e6,
    total_limit: null,
    expires_in: 3000,
    receivers: 2,
  }));
  renderWithStore(<RelayBox live={{ running: false, onToggle: vi.fn() }} />, a);
  expect(await screen.findByTestId("relay-box")).toHaveTextContent(
    "보낼 곳을 아직 정하지 않았습니다",
  );
  expect(screen.queryByTestId("relay-live-toggle")).toBeNull(); // 보낼 곳이 없으면 보내는 단추도 없다
  await userEvent.click(screen.getByTestId("relay-edit"));
  expect(screen.getByTestId("relay-save")).toBeDisabled();
  await userEvent.type(screen.getByTestId("relay-host"), "relay.example");
  await userEvent.type(screen.getByTestId("relay-room"), "abc");
  await userEvent.type(screen.getByTestId("relay-token"), "secret");
  await userEvent.click(screen.getByTestId("relay-save"));
  expect(a.relayTarget).toHaveBeenLastCalledWith({
    host: "relay.example",
    port: 443,
    tls: true,
    room: "abc",
    token: "secret",
  });
  expect(await screen.findByText(TARGET.url)).toBeInTheDocument();
  expect(screen.queryByTestId("relay-form")).toBeNull();
  expect(screen.getByTestId("relay-box")).not.toHaveTextContent("secret");

  await userEvent.click(screen.getByTestId("relay-edit"));
  await userEvent.type(
    screen.getByTestId("relay-link"),
    "wss://relay.example/relay/ws/abc/iq/send?token=t",
  );
  expect(screen.getByTestId("relay-host")).toBeDisabled(); // 한 줄을 넣으면 그것만 본다
  await userEvent.click(screen.getByTestId("relay-save"));
  expect(a.relayTarget).toHaveBeenLastCalledWith({
    link: "wss://relay.example/relay/ws/abc/iq/send?token=t",
  });

  await userEvent.click(await screen.findByTestId("relay-check"));
  expect(await screen.findByTestId("relay-checked")).toHaveTextContent(
    "상한 16.0 MB/s · 받는 쪽 2 · 방이 닫히기까지 50분",
  );
});

test("서버가 거절하면 이유를 보여 주고 칸을 닫지 않는다", async () => {
  const a = api();
  a.relayState = vi.fn(async () => NONE);
  a.relayTarget = vi.fn(async () => {
    throw new Error("토큰이 비었거나 올바르지 않습니다.");
  });
  renderWithStore(<RelayBox />, a);
  await userEvent.click(await screen.findByTestId("relay-edit"));
  await userEvent.type(screen.getByTestId("relay-host"), "relay.example");
  await userEvent.type(screen.getByTestId("relay-room"), "abc");
  await userEvent.click(screen.getByTestId("relay-save"));
  expect(await screen.findByRole("alert")).toHaveTextContent("토큰");
  expect(screen.getByTestId("relay-form")).toBeInTheDocument();
});

test("받는 중일 때만 보내기를 켤 수 있고, 켜면 보낸 양과 받는 쪽 수가 보인다", async () => {
  const a = api();
  a.relayState = vi.fn(async () => SET);
  const onToggle = vi.fn();
  const { rerender } = renderWithStore(
    <RelayBox live={{ running: false, onToggle }} />,
    a,
  );
  expect(await screen.findByTestId("relay-live-toggle")).toBeDisabled();
  expect(screen.getByTestId("relay-box")).toHaveTextContent(
    "받는 중일 때 켤 수 있습니다",
  );
  rerender(
    <StoreProvider api={a}>
      <RelayBox live={{ running: true, onToggle }} />
    </StoreProvider>,
  );
  await userEvent.click(screen.getByTestId("relay-live-toggle"));
  expect(onToggle).toHaveBeenLastCalledWith(true);
  const tap = {
    done: 4,
    skipped: 0,
    error: "",
    took_s: 0.01,
    connected: true,
    sent_bytes: 12.5e6,
    dropped_bytes: 1e6,
    receivers: 1,
    need_bps: 4e6,
  };
  rerender(
    <StoreProvider api={a}>
      <RelayBox live={{ running: true, tap, onToggle }} />
    </StoreProvider>,
  );
  expect(screen.getByTestId("relay-status")).toHaveTextContent(
    "보내는 중 · 보낸 양 12.5 MB · 받는 쪽 1 · 버린 양 1.0 MB",
  );
  expect(screen.getByTestId("relay-box")).toHaveTextContent(
    "4.0 MB/s (32 Mbps)",
  );
  expect(screen.getByTestId("relay-edit")).toBeDisabled(); // 보내는 중에는 보낼 곳을 바꾸지 못한다
  await userEvent.click(screen.getByTestId("relay-live-toggle"));
  expect(onToggle).toHaveBeenLastCalledWith(false);
});

test("저장한 파일을 보내고, 보내는 동안 진행을 보여 주며, 멈출 수 있다", async () => {
  const a = api();
  const job = {
    running: true,
    meta_path: "/s/a.sigmf-meta",
    name: "a.sigmf-data",
    loop: true,
    seconds: 1.5,
    total_s: 8,
    rounds: 0,
    to: TARGET.url,
    connected: true,
    error: "",
    sent_bytes: 6e6,
    dropped_bytes: 0,
    receivers: 0,
  };
  a.relayState = vi.fn(async () => SET);
  a.relayFile = vi.fn(async () => ({ ...SET, job }));
  a.relayFileStop = vi.fn(async () => ({
    ...SET,
    job: { ...job, running: false, connected: false },
  }));
  renderWithStore(<RelayBox file="/s/a.sigmf-data" />, a);
  await userEvent.click(await screen.findByTestId("relay-file-loop"));
  await userEvent.click(screen.getByTestId("relay-file-start"));
  expect(a.relayFile).toHaveBeenCalledWith("/s/a.sigmf-data", true);
  expect(await screen.findByTestId("relay-status")).toHaveTextContent(
    "보내는 중 · 1.5 / 8.0 s · 보낸 양 6.0 MB · 받는 쪽 0",
  );
  await userEvent.click(screen.getByTestId("relay-file-stop"));
  expect(a.relayFileStop).toHaveBeenCalled();
  expect(await screen.findByTestId("relay-file-start")).toBeInTheDocument();
  expect(screen.getByTestId("relay-status")).toHaveTextContent("보내기 끝남");
});

test("암호화하지 않는 바깥 주소면 경고한다", async () => {
  const a = api();
  a.relayState = vi.fn(async () => ({
    ...SET,
    target: {
      ...TARGET,
      tls: false,
      url: "ws://relay.example:80/relay/ws/abc/iq/send",
    },
  }));
  renderWithStore(<RelayBox />, a);
  expect(await screen.findByRole("note")).toHaveTextContent(
    "암호화하지 않는 주소",
  );
});
