import en from "./en.json";
import ko from "./ko.json";

export type Lang = "ko" | "en";
type Dict = Record<string, string>;
const dicts: Record<Lang, Dict> = { ko, en };
let current: Lang = "ko";

export function setLang(lang: Lang): void {
  current = lang;
}

export function getLang(): Lang {
  return current;
}

/** 문구를 가져온다. {name} 자리는 vars로 채운다. 영어가 비어 있으면 한국어로 대신한다. */
export function t(key: string, vars: Record<string, string | number> = {}): string {
  const text = dicts[current][key] || dicts.ko[key] || key;
  return text.replace(/\{(\w+)\}/g, (_, name: string) => String(vars[name] ?? `{${name}}`));
}
