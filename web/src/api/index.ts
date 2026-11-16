import { httpApi } from "./http";
import { mockApi } from "./mock";
import type { Api } from "./types";

/** VITE_API=mock 이면 서버 없이 고정 데이터로 돈다. 기본은 로컬 서버. */
export const api: Api = import.meta.env.VITE_API === "mock" ? mockApi : httpApi;
export type * from "./types";
