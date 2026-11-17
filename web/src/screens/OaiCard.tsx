import { useEffect, useState } from "react";
import type { OaiStatus } from "../api";
import { Badge, Button, Chip } from "../components/ui";
import { t } from "../i18n";
import { go } from "../router";
import { useStore } from "../state/store";
import { OaiFlow, type FlowPhase } from "./OaiFlow";

const LENGTHS = [0.6, 1, 2];

/** OAI NTN 시뮬레이터에서 새로 기록해 바로 여는 카드. 테스트베드가 설치된 경우에만 보인다. */
export function OaiCard() {
  const { api, start, fail } = useStore();
  const [status, setStatus] = useState<OaiStatus | null>(null);
  const [seconds, setSeconds] = useState(0.6);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<FlowPhase>("idle");

  useEffect(() => {
    void api.oaiStatus().then(setStatus, () => setStatus(null));
  }, [api]);

  // 기록하는 동안 서버에 "지금 어느 단계인지" 물어 그림에 표시한다.
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => {
      void api.oaiProgress().then(
        (p) => setPhase((cur) => (cur === "opening" || p.phase === "idle" ? cur : p.phase)),
        () => undefined,
      );
    }, 1000);
    return () => clearInterval(timer);
  }, [api, busy]);

  if (!status?.available) return null;

  const record = async () => {
    setBusy(true);
    setPhase(status.running ? "waiting" : "starting");
    try {
      const rec = await api.oaiRecord(seconds);
      setPhase("opening");
      const s = await start({ kind: "file", path: rec.meta_path, testbed: true, band: rec.band });
      go("scan", s.id);
    } catch (e) {
      fail(String(e instanceof Error ? e.message : e));
      void api.oaiStatus().then(setStatus, () => undefined);
    } finally {
      setBusy(false);
      setPhase("idle");
    }
  };

  return (
    <div className="card" data-testid="source-oai">
      <h3 className="t-tagline">{t("oai.title")}</h3>
      <p className="t-caption muted">{t("oai.desc")}</p>
      {status.ready ? (
        <div>
          <Badge level={status.running ? "ok" : "info"}>{status.running ? t("oai.running") : t("oai.stopped")}</Badge>
        </div>
      ) : (
        <p className="t-caption" data-testid="oai-reason">
          <span aria-hidden="true">! </span>
          {status.reason}
        </p>
      )}
      <OaiFlow phase={phase} band={status.band ?? ""} seconds={seconds} />
      <div className="chips" role="group" aria-label={t("oai.length")}>
        {LENGTHS.filter((s) => s <= (status.max_seconds ?? 3)).map((s) => (
          <Chip key={s} selected={s === seconds} onSelect={() => setSeconds(s)} disabled={busy}>
            {t("oai.seconds", { s })}
          </Chip>
        ))}
      </div>
      {status.location && <p className="t-caption muted">{t("oai.hint", { lat: status.location.lat, lon: status.location.lon })}</p>}
      <div>
        <Button variant="secondary" disabled={busy || !status.ready} onClick={() => void record()} data-testid="oai-record">
          {busy ? t("oai.busy") : t("oai.button")}
        </Button>
        {busy && phase !== "idle" && (
          <p className="t-caption muted" role="status" data-testid="oai-phase">
            {t(`oai.phase.${phase}`)}
          </p>
        )}
      </div>
    </div>
  );
}
