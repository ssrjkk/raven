import type { TooltipPayloadEntry } from "recharts";

interface ChartTooltipProps {
  active?: boolean;
  payload?: readonly TooltipPayloadEntry[];
  label?: string | number;
  formatLabel?: (label: string | number | undefined, payload: readonly TooltipPayloadEntry[]) => string;
}

/** Recharts hands this the hovered row and paints nothing itself: the panel, the ink and the order of label,
 *  name and value are the sheet's (.chart-tooltip), so a tooltip is themed like every other floating surface.
 *  The label formatter is the one part that belongs to the page, because it reads the page's own data. */
export function ChartTooltip({ active, payload, label, formatLabel }: ChartTooltipProps) {
  if (!active || !payload?.length) return null;
  const text = formatLabel
    ? formatLabel(label, payload)
    : label === undefined || label === ""
      ? ""
      : String(label);
  return (
    <div className="chart-tooltip">
      {text && <p className="chart-tooltip-label">{text}</p>}
      <ul className="chart-tooltip-list">
        {payload.map((item, i) => (
          <li key={String(item.dataKey ?? item.name ?? i)} className="chart-tooltip-item">
            <span>{String(item.name ?? "")}</span>
            <span className="chart-tooltip-value">
              {String(item.value ?? "")}
              {item.unit}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
