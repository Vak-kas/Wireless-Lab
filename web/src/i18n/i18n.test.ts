import { expect, test } from "vitest";
import en from "./en.json";
import { setLang, t } from "./index";
import ko from "./ko.json";

test("한국어 문구를 돌려주고 변수를 채운다", () => {
  setLang("ko");
  expect(t("app.name")).toBe("nrtrail");
  expect(t("없는.키")).toBe("없는.키");
});

test("영어 사전은 한국어와 같은 키를 가진다", () => {
  expect(Object.keys(en).sort()).toEqual(Object.keys(ko).sort());
});
