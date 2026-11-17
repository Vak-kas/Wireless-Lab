import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { fakeApi, renderWithStore } from "../test-utils";
import { PhoneTile } from "./PhoneTile";

test("휴대폰 셀 정보를 보여주고, 장비가 없으면 따라가기 버튼을 막는다", async () => {
  const api = fakeApi();
  api.phoneCells = async () => ({
    status: "ok",
    device: "Pixel",
    cells: [{ registered: true, rat: "NR", arfcn: 632628, band: "n78", pci: 101, tac: "000A01", mcc: "001", mnc: "01", rsrp_dbm: -92, freq_mhz: 3489.42 }],
    limits: ["루팅 없이 SIB 원문은 얻을 수 없습니다."],
  });
  renderWithStore(<PhoneTile devices={[]} />, api);
  await userEvent.click(await screen.findByTestId("phone-read"));
  const cells = await screen.findByTestId("phone-cells");
  expect(cells).toHaveTextContent("PCI 101");
  expect(cells).toHaveTextContent("3489.42 MHz");
  expect(cells).toHaveTextContent("접속 중");
  expect(screen.getByRole("button", { name: "이 셀을 SDR로 따라가기" })).toBeDisabled();
  expect(screen.getByTestId("phone-limits")).toHaveTextContent("루팅 없이");
});

test("해석하지 못하면 원문을 보여주고 계속 쓸 수 있다", async () => {
  const api = fakeApi();
  api.phoneCells = async () => ({ status: "unparsed", cells: [], raw: "mCellInfo=???", limits: [] });
  renderWithStore(<PhoneTile devices={[]} />, api);
  await userEvent.click(await screen.findByTestId("phone-read"));
  expect(await screen.findByTestId("phone-status")).toHaveTextContent("해석하지 못했습니다");
  expect(screen.getByText("mCellInfo=???")).toBeInTheDocument();
});
