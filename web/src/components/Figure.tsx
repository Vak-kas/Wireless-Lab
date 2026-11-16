import { useState } from "react";
import type { Plot, Scalar } from "../api";
import { GridPlot } from "./plots/GridPlot";
import { LinePlot } from "./plots/LinePlot";
import { ConstellationPlot, SkyPlot, TablePlot } from "./plots/OtherPlots";
import { Chip } from "./ui";

interface TableProps {
  selected?: Scalar;
  onSelect?: (row: Record<string, Scalar>) => void;
}

export function PlotView({ plot, ...table }: { plot: Plot } & TableProps) {
  switch (plot.type) {
    case "spectrum":
    case "correlation":
    case "timeseries":
      return <LinePlot plot={plot} />;
    case "resource_grid":
    case "waterfall":
      return plot.grid ? <GridPlot plot={plot} /> : null;
    case "constellation":
      return <ConstellationPlot plot={plot} />;
    case "sky_geometry":
      return <SkyPlot plot={plot} />;
    case "table":
      return <TablePlot plot={plot} {...table} />;
  }
}

/** 그림 틀. 화면의 주인공이라 유일하게 그림자를 쓴다. 그림이 여럿이면 칩으로 바꿔 본다("큰 그림 하나"). */
export function Figure({ plots, ...table }: { plots: Plot[] } & TableProps) {
  const [index, setIndex] = useState(0);
  const plot = plots[Math.min(index, plots.length - 1)];
  if (!plot) return null;
  return (
    <figure className="figure" data-testid={`figure-${plot.id}`}>
      {plots.length > 1 && (
        <div className="figure-tabs" role="group">
          {plots.map((p, i) => (
            <Chip key={p.id} selected={i === index} onSelect={() => setIndex(i)}>
              {p.title}
            </Chip>
          ))}
        </div>
      )}
      {plots.length === 1 && <h3 className="figure-title t-body-strong center">{plot.title}</h3>}
      <PlotView plot={plot} {...table} />
      {plot.caption && <figcaption className="t-caption">{plot.caption}</figcaption>}
    </figure>
  );
}
