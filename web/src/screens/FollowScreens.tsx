import { useState } from "react";
import type { Scalar } from "../api";
import { Chain, NextStageButton, RecordButton, SubNav, Tile, TileHead } from "../components/layout";
import { StageSection } from "../components/StageSection";
import { Button, Chip, Empty, Field } from "../components/ui";
import { t } from "../i18n";
import { go } from "../router";
import { useStore } from "../state/store";

const BANDS = ["n1", "n3", "n28", "n78", "n254", "n255", "n256"];
const TONES = ["light", "dark", "parchment", "dark"] as const;

/** 2. 스캔: 대역 선택 칩, 스캔 진행, 찾은 셀 목록 → 셀 선택. */
export function ScanScreen() {
  const { session, pipeline, results, selectCell } = useStore();
  const [band, setBand] = useState(session?.source.band ?? "n78");
  const [freq, setFreq] = useState("");
  const def = pipeline.stages.find((s) => s.id === "scan");
  if (!session || !def) return null;

  const fixed = session.source.kind !== "device";
  const freqMhz = Number(freq);
  const freqError = freq !== "" && !(freqMhz >= 70 && freqMhz <= 7125) ? t("scan.freq.error") : "";
  const params: Record<string, unknown> = fixed ? {} : freq && !freqError ? { center_freq_hz: freqMhz * 1e6 } : { band };
  const scan = results.scan;
  const selected = (session.selected_cell?.gscn as Scalar | undefined) ?? (scan?.next_inputs.selected_gscn as Scalar | undefined);

  return (
    <>
      <SubNav title={t("nav.scan")} action={<NextStageButton />}>
        <Chain current="scan" />
      </SubNav>
      <Tile tone="parchment">
        <TileHead title={t("scan.where.title")} lead={fixed ? t(`scan.where.fixed.${session.source.kind}`) : t("scan.where.lead")} />
        <div className="stack">
          <div className="chips" role="group" aria-label={t("scan.band")} style={{ justifyContent: "center" }}>
            {(fixed ? [session.source.band ?? band] : BANDS).map((b) => (
              <Chip key={b} selected={b === (fixed ? (session.source.band ?? band) : band)} onSelect={() => setBand(b)} disabled={fixed}>
                {b}
              </Chip>
            ))}
          </div>
          {!fixed && (
            <div style={{ maxWidth: 360, margin: "0 auto", width: "100%" }}>
              <Field label={t("scan.freq.label")} error={freqError}>
                {(p) => <input className="input t-body" inputMode="decimal" placeholder="3508.32" value={freq} onChange={(e) => setFreq(e.target.value)} {...p} />}
              </Field>
            </div>
          )}
        </div>
      </Tile>
      <StageSection
        def={def}
        tone="light"
        runParams={params}
        selected={selected}
        onSelectRow={(row) => void selectCell({ gscn: Number(row.gscn), pci: Number(row.pci) })}
        extraAction={
          <Button variant="secondary" data-testid="follow-cell" onClick={() => go("follow", session.id)}>
            {t("scan.follow")}
          </Button>
        }
      />
      <div className="page-end" />
    </>
  );
}

/** 3. 따라가기: 상단 사슬과 "다음 단계" 버튼, 단계마다 한 구역. */
export function FollowScreen() {
  const { session, pipeline, results } = useStore();
  if (!session) return null;
  const stages = pipeline.stages.filter((s) => s.id !== "scan");
  const scan = results.scan;
  const found = (scan?.next_inputs.cells as { gscn: number; pci: number }[] | undefined) ?? [];
  const cell = session.selected_cell ?? found.find((c) => c.gscn === scan?.next_inputs.selected_gscn) ?? found[0];

  return (
    <>
      <SubNav
        title={t("nav.follow")}
        action={
          <>
            <RecordButton />
            <NextStageButton />
          </>
        }
      >
        <Chain />
      </SubNav>
      {!scan || scan.status === "fail" ? (
        <Tile tone="parchment">
          <Empty action={<Button onClick={() => go("scan", session.id)}>{t("follow.goto_scan")}</Button>}>{t("follow.need_scan")}</Empty>
        </Tile>
      ) : (
        <Tile tone="parchment" className="tile-locked">
          <p className="center t-body" data-testid="following-cell">
            {t("follow.cell", { pci: String(cell?.pci ?? "–"), gscn: String(cell?.gscn ?? "–") })}{" "}
            <a href={`#/s/${session.id}/scan`}>{t("follow.change_cell")}</a>
          </p>
        </Tile>
      )}
      {stages.map((def, i) => (
        <StageSection
          key={def.id}
          def={def}
          tone={TONES[i % TONES.length] ?? "light"}
          extraAction={
            def.id === "sib19" ? (
              <Button variant="secondary" data-testid="open-ntn" onClick={() => go("ntn", session.id)}>
                {t("follow.open_ntn")}
              </Button>
            ) : undefined
          }
        />
      ))}
      <div className="page-end" />
    </>
  );
}
