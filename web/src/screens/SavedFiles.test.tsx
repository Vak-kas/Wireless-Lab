import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { SavedState } from "../api";
import { fakeApi as api, renderWithStore } from "../test-utils";
import { RecordFile, SaveFolder } from "./SavedFiles";

const STATE: SavedState = { folder: "/s/saved", default: "/s/saved", is_default: true, free_bytes: 50e9, can_choose: true, platform: "darwin", formats: ["cf32", "cs16", "wav"] };

test("저장 위치를 보여 주고, 바꾸기를 누르면 폴더 고르는 창으로 바꾸며, 기본 위치로 되돌릴 수 있다", async () => {
  const a = api();
  a.savedState = vi.fn(async () => STATE);
  a.savedChoose = vi.fn(async () => ({ ...STATE, folder: "/Volumes/ssd/iq", is_default: false, chosen: true }));
  a.savedFolder = vi.fn(async () => STATE);
  a.savedReveal = vi.fn(async () => ({ ok: true }));
  renderWithStore(<SaveFolder />, a);
  expect(await screen.findByTestId("save-folder")).toHaveTextContent("/s/saved");
  expect(screen.getByTestId("save-folder")).toHaveTextContent("남은 자리 50 GB");
  expect(screen.queryByTestId("save-folder-default")).toBeNull();
  await userEvent.click(screen.getByTestId("save-folder-change"));
  expect(await screen.findByText("/Volumes/ssd/iq")).toBeInTheDocument();
  await userEvent.click(screen.getByTestId("save-folder-open"));
  expect(a.savedReveal).toHaveBeenCalledWith("/Volumes/ssd/iq");
  expect(screen.getByTestId("save-folder-open")).toHaveTextContent("Finder에서 열기");
  await userEvent.click(screen.getByTestId("save-folder-default"));
  expect(a.savedFolder).toHaveBeenCalledWith(null);
});

test("폴더 고르는 창을 띄울 수 없으면 경로를 직접 적고, 서버가 거절하면 이유를 보여 준다", async () => {
  const a = api();
  a.savedState = vi.fn(async () => ({ ...STATE, can_choose: false, platform: "linux" }));
  a.savedFolder = vi.fn(async (path: string | null) => {
    if (path === "iq") throw new Error("폴더는 전체 경로로 적어야 합니다.");
    return { ...STATE, can_choose: false, platform: "linux", folder: path ?? "/s/saved", is_default: false };
  });
  renderWithStore(<SaveFolder />, a);
  await userEvent.click(await screen.findByTestId("save-folder-change"));
  await userEvent.type(screen.getByTestId("save-folder-path"), "iq{Enter}");
  expect(await screen.findByRole("alert")).toHaveTextContent("전체 경로");
  await userEvent.clear(screen.getByTestId("save-folder-path"));
  await userEvent.type(screen.getByTestId("save-folder-path"), "/data/iq{Enter}");
  expect(await screen.findByText("/data/iq")).toBeInTheDocument();
  expect(screen.queryByTestId("save-folder-path")).toBeNull();
  expect(screen.getByTestId("save-folder-open")).toHaveTextContent("폴더에서 열기");
});

test("녹화한 파일을 Finder 에서 보여 주고, 끝난 녹화는 다른 형식으로 내보낸다", async () => {
  const a = api();
  a.savedState = vi.fn(async () => STATE);
  a.savedReveal = vi.fn(async () => ({ ok: true }));
  a.savedExport = vi.fn(async () => ({ path: "/s/saved/r.cs16", format: "cs16", bytes: 4e6, datatype: "ci16_le", sample_rate_hz: 20e6, center_freq_hz: 5180e6 }));
  const first = renderWithStore(<RecordFile dataPath="/s/saved/r.sigmf-data" metaPath="/s/saved/r.sigmf-meta" done={false} />, a);
  await userEvent.click(await screen.findByTestId("record-reveal"));
  expect(a.savedReveal).toHaveBeenCalledWith("/s/saved/r.sigmf-data");
  expect(screen.queryByTestId("record-export")).toBeNull(); // 녹화 중에는 내보내지 않는다(파일이 아직 자란다)
  first.unmount();
  renderWithStore(<RecordFile dataPath="/s/saved/r.sigmf-data" metaPath="/s/saved/r.sigmf-meta" done />, a);
  await screen.findByTestId("record-reveal");
  await userEvent.selectOptions(screen.getByTestId("record-format"), "cs16");
  await userEvent.click(screen.getByTestId("record-export"));
  expect(a.savedExport).toHaveBeenCalledWith("/s/saved/r.sigmf-meta", "cs16");
  const made = await screen.findByTestId("record-made");
  expect(made).toHaveTextContent("/s/saved/r.cs16");
  expect(made).toHaveTextContent("샘플 속도 20 MS/s, 가운데 주파수 5180 MHz");
});

test("서버에 이 기능이 없으면 아무것도 그리지 않는다", async () => {
  const { container } = renderWithStore(<SaveFolder />, api());
  await Promise.resolve();
  expect(container.querySelector("[data-testid='save-folder']")).toBeNull();
});
