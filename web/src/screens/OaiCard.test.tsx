import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { fakeApi, renderWithStore } from "../test-utils";
import { OaiCard } from "./OaiCard";

test("테스트베드가 없으면 카드 자체가 보이지 않는다", async () => {
  renderWithStore(<OaiCard />, fakeApi());
  await waitFor(() => expect(screen.queryByTestId("source-oai")).toBeNull());
});

test("준비되지 않았으면 이유를 보여주고 버튼을 막는다", async () => {
  const api = fakeApi();
  api.oaiStatus = async () => ({ available: true, ready: false, running: false, reason: "Docker 가 꺼져 있습니다." });
  renderWithStore(<OaiCard />, api);
  expect(await screen.findByTestId("oai-reason")).toHaveTextContent("Docker 가 꺼져 있습니다.");
  expect(screen.getByTestId("oai-record")).toBeDisabled();
});

test("기록하면 그 파일을 테스트베드 파일로 열어 스캔 화면으로 간다", async () => {
  const api = fakeApi();
  api.oaiStatus = async () => ({ available: true, ready: true, running: true, reason: "", location: { lat: 66.29, lon: -90 }, max_seconds: 3 });
  api.oaiRecord = vi.fn(async () => ({ meta_path: "/x/oai.sigmf-meta", seconds: 1, num_samples: 1, size_mb: 30, band: "n254", location: { lat: 66.29, lon: -90 } }));
  const created = vi.spyOn(api, "createSession");
  renderWithStore(<OaiCard />, api);
  await userEvent.click(await screen.findByRole("button", { name: "1초" }));
  await userEvent.click(screen.getByTestId("oai-record"));
  await waitFor(() => expect(created).toHaveBeenCalled());
  expect(api.oaiRecord).toHaveBeenCalledWith(1);
  expect(created.mock.calls[0]?.[0]).toEqual({ kind: "file", path: "/x/oai.sigmf-meta", testbed: true, band: "n254" });
  expect(window.location.hash).toBe("#/s/s1/scan");
  expect(screen.getByText(/위도 66.29, 경도 -90/)).toBeInTheDocument();
});

test("기록하는 동안 그림에서 지금 하는 칸이 강조되고 단계 문구가 보인다", async () => {
  const api = fakeApi();
  api.oaiStatus = async () => ({ available: true, ready: true, running: false, reason: "", band: "n254", max_seconds: 3 });
  let finish: () => void = () => undefined;
  api.oaiRecord = () => new Promise((_, reject) => (finish = () => reject(new Error("끝"))));
  api.oaiProgress = async () => ({ phase: "recording" });
  renderWithStore(<OaiCard />, api);
  expect(await screen.findByTestId("oai-node-gnb")).toHaveAttribute("data-state", "idle");
  expect(screen.getByText(/대역 n254/)).toBeInTheDocument();
  await userEvent.click(screen.getByTestId("oai-record"));
  expect(screen.getByTestId("oai-node-gnb")).toHaveAttribute("data-state", "active");
  expect(screen.getByTestId("oai-phase")).toHaveTextContent("기지국 프로그램을 켜는 중");
  await waitFor(() => expect(screen.getByTestId("oai-node-recorder")).toHaveAttribute("data-state", "active"), { timeout: 3000 });
  expect(screen.getByTestId("oai-node-gnb")).toHaveAttribute("data-state", "done");
  finish();
  await waitFor(() => expect(screen.getByTestId("oai-node-recorder")).toHaveAttribute("data-state", "idle"));
});
