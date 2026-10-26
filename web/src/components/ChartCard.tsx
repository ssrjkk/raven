import type { ReactNode } from "react";

/**
 * A titled card around one chart. The role and label live here rather than at each call site because
 * recharts paints a series into plain SVG nodes: without a name on the container, a screen reader
 * announces an empty region exactly where the trend is supposed to be.
 */
export function ChartCard({
  title,
  children,
  className = "card",
}: {
  title: string;
  children: ReactNode;
  /** "card" for a chart that stands on its own; "" for one nested inside another surface. */
  className?: string;
}) {
  return (
    <figure className={className} role="img" aria-label={title}>
      <h2 className="text-sm font-semibold mb-3 text-secondary">{title}</h2>
      {children}
    </figure>
  );
}
