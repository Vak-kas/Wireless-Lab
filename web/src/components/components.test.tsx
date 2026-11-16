import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { expect, test, vi } from "vitest";
import type { Plot, StageResult } from "../api";
import { useStore } from "../state/store";
import { fakeApi, PIPELINE, renderWithStore, result } from "../test-utils";
import { Figure } from "./Figure";
import { Chain } from "./layout";
import { ticks } from "./plots/scale";
import { Derivations, Diagnostics, TreeView, Values } from "./result";
import { StageSection } from "./StageSection";
import { Term } from "./ui";

function Opened({ children }: { children: React.ReactNode }) {
  const { ready, session, open } = useStore();
  useEffect(() => {
    if (ready && !session) void open("s1");
  }, [ready, session, open]);
  return session ? <>{children}</> : null;
}

test("눈금은 1·2·5 간격으로 잡힌다", () => {
  expect(ticks(0, 10, 5)).toEqual([0, 2, 4, 6, 8, 10]);
  expect(ticks(-108, -64, 4)).toEqual([-100, -80]);
});

test("용어에 초점을 주면 한 줄 설명이 뜨고, 사전에 없으면 글자만 보인다", async () => {
  renderWithStore(
    <>
      <Term k="ssb">SSB</Term>
      <Term k="없는말">그냥</Term>
    </>,
  );
  const term = await screen.findByRole("button", { name: "SSB" });
  await userEvent.hover(term);
  expect(screen.getByRole("tooltip")).toHaveTextContent("신호등");
  expect(screen.queryByRole("button", { name: "그냥" })).toBeNull();
});

test("값 카드는 종류·원시값·출처를 보여주고 계산 과정으로 연결한다", async () => {
  const show = vi.fn();
  renderWithStore(
    <Values
      onShowDerivation={show}
      values={[
        { key: "sfn", label: "시스템 프레임 번호", value: 412, unit: "", kind: "derived", derivation_id: "d1", primary: true },
        { key: "ta", label: "공통 TA", value: 8000.5, unit: "µs", kind: "decoded", raw: 1964636, source: "SIB19.ta-Common-r17" },
      ]}
    />,
  );
  expect(screen.getByTestId("value-sfn")).toHaveTextContent("412");
  expect(screen.getByTestId("value-sfn")).toHaveTextContent("계산한 값");
  await userEvent.click(screen.getByRole("button", { name: "어떻게 구했나" }));
  expect(show).toHaveBeenCalledWith("d1");
  // primary가 아닌 값은 "전체 값 보기" 안에 있다
  expect(screen.getByTestId("fold-values")).toHaveTextContent("원시값 1964636");
  expect(screen.getByTestId("fold-values")).toHaveTextContent("SIB19.ta-Common-r17");
});

test("계산 과정 카드는 공식, 입력, 풀이, 결과, 표준 조항을 모두 보여준다", () => {
  render(
    <Derivations
      list={[
        {
          id: "d1",
          title: "전체 SFN 계산",
          formula_tex: "SFN = 16 \\cdot SFN_{MSB6} + SFN_{LSB4}",
          inputs: [{ symbol: "SFN_MSB6", value: 25, source: "MIB.systemFrameNumber" }],
          steps: ["16 × 25 + 12 = 412"],
          result: { value: 412, unit: "" },
          spec_ref: "TS 38.212 7.1.1",
        },
      ]}
    />,
  );
  const card = screen.getByTestId("derivation-d1");
  expect(card).toHaveTextContent("전체 SFN 계산");
  expect(card.querySelector(".katex")).not.toBeNull();
  expect(card).toHaveTextContent("MIB.systemFrameNumber");
  expect(card).toHaveTextContent("16 × 25 + 12 = 412");
  expect(card).toHaveTextContent("TS 38.212 7.1.1");
});

test("실패 안내는 원인마다 버튼 하나를 주고 가능성 순위를 붙인다", async () => {
  const onAction = vi.fn();
  render(
    <Diagnostics
      onAction={onAction}
      list={[
        { level: "error", code: "NO_SSB", message_easy: "SSB를 못 찾았습니다.", fix: "이득을 올려 보세요.", action: { label: "이득 +10 dB로 다시 시도", kind: "rerun", params: { gain_delta_db: 10 } } },
        { level: "error", code: "NO_SSB", message_easy: "주파수가 다를 수 있습니다.", fix: "스캔을 다시 하세요.", action: { label: "스캔으로 돌아가기", kind: "goto", target: "scan" } },
      ]}
    />,
  );
  expect(screen.getByLabelText("가능성 1순위")).toBeInTheDocument();
  expect(screen.getByLabelText("가능성 2순위")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "이득 +10 dB로 다시 시도" }));
  expect(onAction.mock.calls[0]?.[0].action.params).toEqual({ gain_delta_db: 10 });
});

test("그림: 선 그림의 강조선에 초점을 주면 설명이 뜨고, 격자 범례에 올리면 영역 설명이 뜬다", async () => {
  const line: Plot = {
    id: "pss_corr",
    type: "correlation",
    title: "PSS 상관",
    x: { label: "시간", unit: "샘플" },
    y: { label: "상관" },
    series: [{ name: "PSS 1", x: [0, 1, 2, 3], y: [0.1, 0.9, 0.2, 0.1] }],
    annotations: [{ kind: "vline", x: 1, label: "피크", description: "여기서 가장 잘 맞습니다." }],
  };
  const grid: Plot = {
    id: "ssb_grid",
    type: "resource_grid",
    title: "SSB 자원 격자",
    grid: { rows: 2, cols: 2, values: [[1, 0.5], [0.2, 0]], categories: [[0, 1], [-1, -1]], category_names: ["PSS", "PBCH"] },
    annotations: [{ kind: "box", label: "PSS", category: 0, description: "1차 동기 신호", x0: 0, x1: 0, y0: 0, y1: 0 }],
  };
  renderWithStore(<Figure plots={[line, grid]} />);
  fireEvent.focus(screen.getByLabelText(/^피크\./));
  expect(screen.getByText(/여기서 가장 잘 맞습니다/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "SSB 자원 격자" }));
  expect(document.querySelectorAll(".grid-cell")).toHaveLength(4);
  await userEvent.hover(screen.getByRole("button", { name: "PSS" }));
  expect(screen.getByText(/1차 동기 신호/)).toBeInTheDocument();
});

test("표에서 행을 고르면 선택이 전달된다 (키보드 포함)", async () => {
  const onSelect = vi.fn();
  const table: Plot = {
    id: "cells",
    type: "table",
    title: "찾은 기지국",
    table: { columns: [{ key: "gscn", label: "GSCN" }, { key: "pci", label: "PCI", align: "right" }], rows: [{ gscn: 5460, pci: 502 }, { gscn: 5487, pci: 77 }], select_key: "gscn" },
    annotations: [],
  };
  renderWithStore(<Figure plots={[table]} selected={5460} onSelect={onSelect} />);
  const rows = screen.getAllByRole("row").slice(1);
  expect(rows[0]).toHaveAttribute("aria-selected", "true");
  rows[1]!.focus();
  await userEvent.keyboard("{Enter}");
  expect(onSelect).toHaveBeenCalledWith({ gscn: 5487, pci: 77 });
});

test("ASN.1 트리는 가지를 펼침으로, 잎을 이름: 값으로 보여준다", () => {
  render(<TreeView data={{ cellAccessRelatedInfo: { plmn: ["001", "01"], tac: "000A01" }, q: -62 }} />);
  expect(screen.getByText("cellAccessRelatedInfo")).toBeInTheDocument();
  expect(screen.getByText("000A01")).toBeInTheDocument();
  expect(screen.getByText("-62")).toBeInTheDocument();
});

test("사슬은 상태 넷을 문구와 함께 보여주고, 잠긴 단계에는 이유가 붙는다", async () => {
  renderWithStore(
    <Opened>
      <Chain current="scan" />
    </Opened>,
  );
  const scan = await screen.findByTestId("chain-scan");
  expect(scan).toHaveAttribute("data-state", "next");
  expect(scan).toHaveAttribute("aria-current", "step");
  const ssb = screen.getByTestId("chain-ssb");
  expect(ssb).toHaveAttribute("aria-disabled", "true");
  expect(ssb).toHaveAccessibleName(/잠김.*먼저 스캔을 해야 합니다/);
});

test("단계 구역: 잠김 → 실행 → 진행 문구 → 결과와 다시 시도 버튼", async () => {
  const api = fakeApi();
  const [scanDef, ssbDef] = PIPELINE.stages;
  renderWithStore(
    <Opened>
      <StageSection def={scanDef!} tone="light" runParams={{ band: "n256" }} />
      <StageSection def={ssbDef!} tone="dark" />
    </Opened>,
    api,
  );
  expect(await screen.findByText(/먼저 스캔을 해야 합니다/)).toBeInTheDocument();
  expect(screen.queryByTestId("run-ssb")).toBeNull();

  await userEvent.click(screen.getByTestId("run-scan"));
  expect(api.runs).toEqual([{ stage: "scan", params: { band: "n256" } }]);
  act(() => api.emit({ type: "job.progress", stage: "scan", progress: 0.5, message: "동기 신호를 찾는 중" }));
  expect(screen.getByText("동기 신호를 찾는 중")).toBeInTheDocument();

  const failed: StageResult = result("scan", {
    status: "fail",
    summary_easy: "기지국 신호를 찾지 못했습니다.",
    diagnostics: [{ level: "error", code: "NO_CELL", message_easy: "신호가 안 보입니다.", fix: "이득을 올려 보세요.", action: { label: "이득 +10 dB로 다시 시도", kind: "rerun", params: { gain_delta_db: 10 } } }],
  });
  act(() => api.emit({ type: "job.finished", stage: "scan", result: failed }));
  await waitFor(() => expect(screen.getByTestId("status-scan")).toHaveTextContent("실패"));
  expect(screen.getByText("기지국 신호를 찾지 못했습니다.")).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "이득 +10 dB로 다시 시도" }));
  expect(api.runs[1]).toEqual({ stage: "scan", params: { gain_delta_db: 10 } });
});
