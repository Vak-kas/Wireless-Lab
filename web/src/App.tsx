import { useEffect } from "react";
import { GlobalNav, StickyBar } from "./components/layout";
import { Empty } from "./components/ui";
import { DeviceHub } from "./devices/DeviceHub";
import { t } from "./i18n";
import { go, useRoute } from "./router";
import { SessionsScreen, SettingsScreen } from "./screens/AdminScreens";
import { FollowScreen, ScanScreen } from "./screens/FollowScreens";
import { NtnScreen, TrackScreen } from "./screens/NtnTrackScreens";
import { SpectrumScreen } from "./screens/SpectrumScreen";
import { StartScreen } from "./screens/StartScreen";
import { NearbyScreen } from "./screens/NearbyScreen";
import { TxScreen } from "./screens/TxScreen";
import { StoreProvider, useStore } from "./state/store";

function Screens() {
  const route = useRoute();
  const { ready, session, open, error, lang } = useStore();

  // 주소에 세션이 있으면 그 세션을 연다. 없는 세션이면 시작 화면으로 돌아간다.
  useEffect(() => {
    if (!ready || !route.sessionId || session?.id === route.sessionId) return;
    open(route.sessionId).catch(() => go("start"));
  }, [ready, route.sessionId, session?.id, open]);

  const waiting = route.sessionId !== undefined && session?.id !== route.sessionId;
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  return (
    <div key={lang}>
      <GlobalNav route={route} />
      <main>
        {!ready || waiting ? (
          <div className="tile" data-tone="parchment">
            <Empty>{error ? t("status.error", { message: error }) : t("status.loading")}</Empty>
          </div>
        ) : (
          <>
            {route.screen === "start" && <StartScreen />}
            {route.screen === "scan" && <ScanScreen />}
            {route.screen === "follow" && <FollowScreen />}
            {route.screen === "ntn" && <NtnScreen />}
            {route.screen === "track" && <TrackScreen />}
            {route.screen === "spectrum" && <SpectrumScreen />}
            {route.screen === "tx" && <TxScreen />}
            {route.screen === "nearby" && <NearbyScreen />}
            {route.screen === "sessions" && <SessionsScreen />}
            {route.screen === "settings" && <SettingsScreen />}
          </>
        )}
      </main>
      <StickyBar />
    </div>
  );
}

export function App() {
  return (
    <StoreProvider>
      <DeviceHub>
        <Screens />
      </DeviceHub>
    </StoreProvider>
  );
}
