import { useEffect, useState } from "react";

/** 주소창의 # 뒤를 화면 경로로 쓴다. 예: #/s/abc/follow */
export interface Route {
  screen: "start" | "scan" | "follow" | "ntn" | "track" | "sessions" | "settings" | "spectrum" | "tx" | "nearby" | "sim" | "bench";
  sessionId?: string;
}

const SESSION_SCREENS = ["scan", "follow", "ntn", "track"] as const;

export function parseRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] === "s" && parts[1]) {
    const screen = SESSION_SCREENS.find((s) => s === parts[2]) ?? "follow";
    return { screen, sessionId: parts[1] };
  }
  if (parts[0] === "sessions") return { screen: "sessions" };
  if (parts[0] === "settings") return { screen: "settings" };
  if (parts[0] === "spectrum") return { screen: "spectrum" };
  if (parts[0] === "tx") return { screen: "tx" };
  if (parts[0] === "nearby") return { screen: "nearby" };
  if (parts[0] === "sim") return { screen: "sim" };
  if (parts[0] === "bench") return { screen: "bench" };
  return { screen: "start" };
}

export function href(screen: Route["screen"], sessionId?: string): string {
  if (SESSION_SCREENS.some((s) => s === screen)) return sessionId ? `#/s/${sessionId}/${screen}` : "#/";
  return screen === "start" ? "#/" : `#/${screen}`;
}

export function go(screen: Route["screen"], sessionId?: string): void {
  window.location.hash = href(screen, sessionId);
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const onChange = () => {
      setRoute(parseRoute(window.location.hash));
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
