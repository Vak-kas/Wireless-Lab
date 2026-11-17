import { useCallback, useEffect, useMemo, useState } from "react";
import type { Plot, StageResult, TrackChange, TrackData } from "../api";
import { Figure } from "../components/Figure";
import { Chain, SubNav, Tile, TileHead } from "../components/layout";
import { Derivations, Diagnostics, ExpertInfo, Values } from "../components/result";
import { Badge, Button, Chip, Empty, Field, Fold } from "../components/ui";
import { t } from "../i18n";
import { go } from "../router";
import { useStore } from "../state/store";

const num = (s: string) => (s.trim() === "" ? NaN : Number(s));

/** 4. SIB19 / NTN: 위성 위치·TA·도플러 계산, 하늘 지도, 이상 징후 배지. */
export function NtnScreen() {
  const { api, session, results, pipeline } = useStore();
  const view = pipeline.views?.find((v) => v.id === "ntn");
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [alt, setAlt] = useState("");
  const [result, setResult] = useState<StageResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [highlight, setHighlight] = useState<string | null>(null);
  const hasSib19 = results.sib19?.status === "ok";

  const errors = {
    lat: Number.isNaN(num(lat)) || Math.abs(num(lat)) > 90 ? t("ntn.error.lat") : "",
    lon: Number.isNaN(num(lon)) || Math.abs(num(lon)) > 180 ? t("ntn.error.lon") : "",
    alt: Number.isNaN(num(alt)) ? t("ntn.error.alt") : "",
  };
  const valid = !errors.lat && !errors.lon && !errors.alt;

  const compute = useCallback(
    async (la: number, lo: number, al: number) => {
      if (!session) return;
      setBusy(true);
      setError("");
      try {
        setResult(await api.ntn(session.id, { lat: la, lon: lo, alt_m: al }));
      } catch (e) {
        setError(String(e instanceof Error ? e.message : e));
      } finally {
        setBusy(false);
      }
    },
    [api, session],
  );

  // 처음 들어오면 설정의 기본 위치로 한 번 계산한다.
  useEffect(() => {
    if (!hasSib19) return;
    void api.settings().then((s) => {
      setLat(String(s.location.lat));
      setLon(String(s.location.lon));
      setAlt(String(s.location.alt_m));
      void compute(s.location.lat, s.location.lon, s.location.alt_m);
    });
  }, [api, hasSib19, compute]);

  if (!session) return null;
  const anomalies = result?.diagnostics.filter((d) => d.level !== "info") ?? [];
  const figures = result?.plots.filter((p) => p.type !== "table") ?? [];
  const tables = result?.plots.filter((p) => p.type === "table") ?? [];

  return (
    <>
      <SubNav
        title={t("nav.ntn")}
        action={
          <Button disabled={!hasSib19 || !valid || busy} onClick={() => void compute(num(lat), num(lon), num(alt))} data-testid="ntn-compute">
            {t("ntn.compute")}
          </Button>
        }
      >
        <Chain />
      </SubNav>
      {!hasSib19 ? (
        <Tile tone="parchment">
          <Empty action={<Button onClick={() => go("follow", session.id)}>{t("ntn.goto_follow")}</Button>}>{t("ntn.need_sib19")}</Empty>
        </Tile>
      ) : (
        <>
          <Tile tone="parchment">
            <TileHead title={t("ntn.where.title")} lead={t("ntn.where.lead")} />
            <div className="form-row">
              <Field label={t("ntn.lat")} error={lat === "" ? "" : errors.lat}>
                {(p) => <input className="input t-body" inputMode="decimal" value={lat} onChange={(e) => setLat(e.target.value)} {...p} />}
              </Field>
              <Field label={t("ntn.lon")} error={lon === "" ? "" : errors.lon}>
                {(p) => <input className="input t-body" inputMode="decimal" value={lon} onChange={(e) => setLon(e.target.value)} {...p} />}
              </Field>
              <Field label={t("ntn.alt")} error={alt === "" ? "" : errors.alt}>
                {(p) => <input className="input t-body" inputMode="decimal" value={alt} onChange={(e) => setAlt(e.target.value)} {...p} />}
              </Field>
            </div>
          </Tile>
          <Tile tone="dark" id="ntn-result">
            <TileHead eyebrow={view?.question ?? t("ntn.eyebrow")} title={view?.title ?? t("ntn.title")} lead={result?.summary_easy ?? (busy ? t("status.running") : error)}>
              {result && (
                <span data-testid="ntn-anomalies">
                  {anomalies.length === 0 ? (
                    <Badge level="ok">{t("ntn.anomaly.none")}</Badge>
                  ) : (
                    <Badge level={anomalies.some((d) => d.level === "error") ? "error" : "warn"}>{t("ntn.anomaly.count", { n: anomalies.length })}</Badge>
                  )}
                </span>
              )}
            </TileHead>
            {result && (
              <>
                <Diagnostics
                  list={result.diagnostics}
                  onAction={(d) => {
                    const target = d.action?.target;
                    if (d.action?.kind === "rerun") void compute(num(lat), num(lon), num(alt));
                    else if (target === "settings") go("settings");
                    else if (target === "scan") go("scan", session.id);
                    else if (target) go("follow", session.id);
                  }}
                />
                {figures.length > 0 && <Figure plots={figures} />}
              </>
            )}
          </Tile>
          {result && (
            <Tile tone="light">
              {tables.map((p) => (
                <Figure key={p.id} plots={[p]} />
              ))}
              <Values
                values={result.values}
                groups={view?.groups}
                onShowDerivation={(id) => {
                  setHighlight(id);
                  const fold = document.getElementById("ntn-derivations") as HTMLDetailsElement | null;
                  if (fold) fold.open = true;
                  setTimeout(() => document.getElementById(`deriv-${id}`)?.scrollIntoView({ block: "center" }), 30);
                }}
              />
              <details className="fold" id="ntn-derivations" data-testid="fold-derivations-ntn">
                <summary className="t-body">{t("stage.show_derivations", { n: result.derivations.length })}</summary>
                <div className="fold-body">
                  <Derivations list={result.derivations} highlight={highlight} />
                </div>
              </details>
              <Fold title={t("stage.expert")}>
                <ExpertInfo result={result} />
              </Fold>
            </Tile>
          )}
        </>
      )}
      <div className="page-end" />
    </>
  );
}

const INTERVALS = [2, 5, 10, 30];

/** 5. 추적: 시간에 따른 변화 그래프와 SIB19 변경 이력. */
export function TrackScreen() {
  const { api, session, results, setSession } = useStore();
  const [data, setData] = useState<TrackData | null>(null);
  const [changes, setChanges] = useState<TrackChange[]>([]);
  const [interval, setIntervalS] = useState(5);
  const id = session?.id;

  const refresh = useCallback(async () => {
    if (!id) return;
    setData(await api.trackData(id));
    setChanges(await api.trackChanges(id));
  }, [api, id]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!data?.running) return;
    const timer = setInterval(() => void refresh(), 1000);
    return () => clearInterval(timer);
  }, [data?.running, refresh]);

  const plots = useMemo<Plot[]>(
    () =>
      (data?.series ?? []).map((s) => ({
        id: `track-${s.key}`,
        type: "timeseries",
        title: s.label,
        x: { label: t("track.time"), unit: "s" },
        y: { label: s.label, unit: s.unit },
        series: [
          {
            name: s.label,
            x: (data?.points ?? []).filter((p) => p[s.key] != null).map((p) => p.t_s),
            y: (data?.points ?? []).filter((p) => p[s.key] != null).map((p) => p[s.key] as number),
            role: "accent",
          },
        ],
        annotations: [],
      })),
    [data],
  );

  if (!session || !id) return null;
  const canTrack = results.ssb?.status === "ok";
  const toggle = async () => {
    if (data?.running) await api.trackStop(id);
    else await api.trackStart(id, interval);
    setSession(await api.getSession(id));
    await refresh();
  };

  return (
    <>
      <SubNav
        title={t("nav.track")}
        action={
          <Button disabled={!canTrack} onClick={() => void toggle()} data-testid="track-toggle">
            {data?.running ? t("track.stop") : t("track.start")}
          </Button>
        }
      >
        <Chain />
      </SubNav>
      <Tile tone="light">
        <TileHead title={t("track.title")} lead={canTrack ? t("track.lead") : t("track.need_ssb")}>
          <div className="chips" role="group" aria-label={t("track.interval")}>
            {INTERVALS.map((s) => (
              <Chip key={s} selected={s === interval} onSelect={() => setIntervalS(s)} disabled={data?.running}>
                {t("track.every", { s })}
              </Chip>
            ))}
          </div>
          {data?.running && <Badge level="ok">{t("track.running", { n: data.points.length })}</Badge>}
          {data?.replay && (data?.points.length ?? 0) > 0 && <Badge level="info">{t("track.replay")}</Badge>}
        </TileHead>
        {plots.length > 0 && (data?.points.length ?? 0) > 0 ? <Figure plots={plots} /> : <Empty>{t("track.empty")}</Empty>}
        {(data?.points.length ?? 0) > 0 && (
          <p className="center">
            <a href={api.trackCsvUrl(id)} download data-testid="track-csv">
              {t("track.csv")}
            </a>
          </p>
        )}
      </Tile>
      <Tile tone="dark">
        <TileHead title={t("track.changes.title")} lead={t("track.changes.lead")} />
        {changes.length === 0 ? (
          <Empty>{t("track.changes.none")}</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data t-caption" data-testid="track-changes">
              <thead>
                <tr>
                  <th scope="col" className="right">
                    {t("track.time")} (s)
                  </th>
                  <th scope="col">{t("track.changes.field")}</th>
                  <th scope="col">{t("track.changes.before")}</th>
                  <th scope="col">{t("track.changes.after")}</th>
                </tr>
              </thead>
              <tbody>
                {changes.map((c, i) => (
                  <tr key={i}>
                    <td className="right num">{c.t_s}</td>
                    <td>
                      {c.label} {c.anomaly && <Badge level="warn">{t("track.changes.anomaly")}</Badge>}
                    </td>
                    <td className="mono">{c.before}</td>
                    <td className="mono">{c.after}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Tile>
      <div className="page-end" />
    </>
  );
}
