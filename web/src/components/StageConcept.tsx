import type { ReactNode } from "react";
import { t } from "../i18n";

/** 오른쪽을 가리키는 짧은 화살표. */
function Arrow({ x1, x2, y, accent }: { x1: number; x2: number; y: number; accent?: boolean }) {
  const cls = accent ? "concept-accent" : "concept-ink";
  return (
    <g className={cls}>
      <line x1={x1} x2={x2} y1={y} y2={y} />
      <polyline points={`${x2 - 6},${y - 4} ${x2},${y} ${x2 - 6},${y + 4}`} />
    </g>
  );
}

/** 읽어 낸 안내문을 나타내는 카드. */
function Card({ title, note }: { title: string; note: string }) {
  return (
    <g>
      <rect className="concept-ink" x={260} y={35} width={80} height={80} rx={6} />
      <text className="concept-text strong" x={300} y={55} textAnchor="middle">
        {title}
      </text>
      {[70, 84, 98].map((y) => (
        <line key={y} className="concept-line" x1={272} x2={328} y1={y} y2={y} />
      ))}
      <text className="concept-text" x={300} y={133} textAnchor="middle">
        {note}
      </text>
    </g>
  );
}

const SSB_PARTS = ["PSS", "PBCH", "SSS", "PBCH"];

/** 단계마다 "이 단계가 하는 일"을 한 장으로 보여 주는 그림. 실제 결과가 아니라 개념도다. */
const DRAWINGS: Record<string, () => ReactNode> = {
  // 주파수 축을 따라 창을 옮기며 솟은 곳을 찾는다
  scan: () => (
    <>
      <line className="concept-line" x1={20} x2={340} y1={110} y2={110} />
      {Array.from({ length: 10 }, (_, i) => 36 + i * 32).map((x) => (
        <line key={x} className="concept-line" x1={x} x2={x} y1={104} y2={116} />
      ))}
      <polyline className="concept-ink" points="20,100 60,98 100,101 140,99 180,100 205,98 216,70 228,30 240,70 251,98 290,100 340,99" />
      <rect className="concept-accent dashed" x={116} y={22} width={32} height={94} rx={4} />
      <Arrow x1={154} x2={190} y={34} accent />
      <text className="concept-text" x={132} y={15} textAnchor="middle">
        {t("concept.scan.window")}
      </text>
      <text className="concept-text" x={262} y={42}>
        {t("concept.scan.peak")}
      </text>
      <text className="concept-text" x={36} y={136}>
        {t("concept.scan.slots")}
      </text>
      <text className="concept-text" x={340} y={136} textAnchor="end">
        {t("concept.axis.freq")}
      </text>
    </>
  ),
  // 되풀이되는 블록 하나를 확대해 시작 시점을 맞춘다
  ssb: () => (
    <>
      <line className="concept-line" x1={20} x2={340} y1={118} y2={118} />
      {[40, 150, 260].map((x) => (
        <rect key={x} className={x === 150 ? "concept-accent soft" : "concept-ink soft"} x={x} y={100} width={28} height={14} rx={2} />
      ))}
      <line className="concept-line" x1={150} y1={100} x2={110} y2={78} />
      <line className="concept-line" x1={178} y1={100} x2={250} y2={78} />
      {SSB_PARTS.map((name, i) => (
        <g key={i}>
          <rect className={i === 0 ? "concept-accent soft" : "concept-ink"} x={110 + i * 35} y={22} width={35} height={56} />
          <text className="concept-text" x={127.5 + i * 35} y={54} textAnchor="middle">
            {name}
          </text>
        </g>
      ))}
      <line className="concept-accent" x1={110} x2={110} y1={10} y2={86} />
      <text className="concept-text" x={104} y={18} textAnchor="end">
        {t("concept.ssb.start")}
      </text>
      <text className="concept-text" x={20} y={94}>
        {t("concept.ssb.repeat")}
      </text>
      <text className="concept-text" x={340} y={136} textAnchor="end">
        {t("concept.axis.time")}
      </text>
    </>
  ),
  // 블록 안의 PBCH → 비트 → MIB
  mib: () => (
    <>
      {SSB_PARTS.map((name, i) => (
        <rect key={i} className={name === "PBCH" ? "concept-accent soft" : "concept-ink"} x={20 + i * 20} y={45} width={20} height={60} />
      ))}
      <text className="concept-text" x={60} y={122} textAnchor="middle">
        {t("concept.mib.block")}
      </text>
      <Arrow x1={106} x2={134} y={75} />
      <rect className="concept-ink dashed" x={140} y={60} width={80} height={30} rx={4} />
      <text className="concept-text mono" x={180} y={79} textAnchor="middle">
        0 1 1 0 1 …
      </text>
      <text className="concept-text" x={180} y={108} textAnchor="middle">
        {t("concept.mib.bits")}
      </text>
      <Arrow x1={226} x2={254} y={75} />
      <Card title="MIB" note={t("concept.mib.card")} />
    </>
  ),
  // PDCCH 가 가리키는 PDSCH 에서 SIB1 을 읽는다
  sib1: () => (
    <>
      <rect className="concept-line" x={20} y={20} width={200} height={100} />
      <rect className="concept-accent soft" x={36} y={42} width={28} height={58} />
      <text className="concept-text" x={50} y={36} textAnchor="middle">
        PDCCH
      </text>
      <rect className="concept-ink soft" x={110} y={52} width={92} height={40} />
      <text className="concept-text" x={156} y={76} textAnchor="middle">
        PDSCH
      </text>
      <Arrow x1={68} x2={106} y={72} accent />
      <text className="concept-text" x={120} y={112} textAnchor="middle">
        {t("concept.sib1.points")}
      </text>
      <text className="concept-text" x={20} y={14}>
        {t("concept.axis.freq_short")}
      </text>
      <text className="concept-text" x={220} y={136} textAnchor="end">
        {t("concept.axis.time")}
      </text>
      <Arrow x1={228} x2={254} y={75} />
      <Card title="SIB1" note={t("concept.sib1.card")} />
    </>
  ),
  // 위성 위치·속도와 수신기 사이 거리
  sib19: () => (
    <>
      <path className="concept-ink" d="M20 140 Q180 90 340 140" />
      <line className="concept-ink" x1={120} x2={120} y1={118} y2={102} />
      <line className="concept-ink" x1={112} x2={128} y1={102} y2={102} />
      <text className="concept-text" x={120} y={143} textAnchor="middle">
        {t("concept.sib19.receiver")}
      </text>
      <rect className="concept-accent soft" x={244} y={24} width={12} height={12} rx={2} />
      <line className="concept-accent" x1={230} x2={244} y1={30} y2={30} />
      <line className="concept-accent" x1={256} x2={270} y1={30} y2={30} />
      <Arrow x1={278} x2={316} y={30} accent />
      <text className="concept-text" x={250} y={16} textAnchor="middle">
        {t("concept.sib19.orbit")}
      </text>
      <line className="concept-accent dashed" x1={246} y1={38} x2={124} y2={104} />
      <text className="concept-text" x={200} y={84}>
        {t("concept.sib19.delay")}
      </text>
      <text className="concept-text" x={340} y={58} textAnchor="end">
        {t("concept.sib19.carried")}
      </text>
    </>
  ),
};

export const CONCEPT_STAGES = Object.keys(DRAWINGS);

export function StageConcept({ stage }: { stage: string }) {
  const draw = DRAWINGS[stage];
  if (!draw) return null;
  return (
    <svg className="concept" viewBox="0 0 360 150" role="img" aria-label={t(`concept.${stage}.label`)} data-testid={`concept-${stage}`}>
      {draw()}
    </svg>
  );
}
