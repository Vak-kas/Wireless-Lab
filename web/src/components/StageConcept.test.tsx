import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import stages from "../../../pipeline/stages.json";
import ko from "../i18n/ko.json";
import { CONCEPT_STAGES, StageConcept } from "./StageConcept";

test("사슬의 모든 단계에 개념도가 있고, 설명 문구가 붙는다", () => {
  const ids = (stages as { stages: { id: string }[] }).stages.map((s) => s.id);
  expect(ids.length).toBeGreaterThan(0);
  for (const id of ids) {
    expect(CONCEPT_STAGES).toContain(id);
    const { unmount } = render(<StageConcept stage={id} />);
    const label = (ko as Record<string, string>)[`concept.${id}.label`];
    expect(label).toBeTruthy();
    expect(screen.getByRole("img", { name: label })).toBeInTheDocument();
    // 번역 열쇠가 그대로 화면에 나오면 안 된다
    expect(screen.getByTestId(`concept-${id}`).textContent).not.toMatch(/concept\./);
    unmount();
  }
});

test("개념도가 없는 단계는 아무것도 그리지 않는다", () => {
  const { container } = render(<StageConcept stage="ra" />);
  expect(container).toBeEmptyDOMElement();
});
