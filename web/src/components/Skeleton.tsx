import { memo } from "react";

const PULSE = "animate-pulse";
const BG = "var(--dt-colors-bg-tertiary)";

interface SkeletonProps {
  width?: string | number;
  height?: string | number;
  rounded?: string;
  className?: string;
}

export const Skeleton = memo(function Skeleton({ width, height = 16, rounded = "lg", className = "" }: SkeletonProps) {
  return (
    <div
      className={`${PULSE} ${className}`}
      style={{
        width: typeof width === "number" ? `${width}px` : width,
        height: typeof height === "number" ? `${height}px` : height,
        borderRadius: `var(--dt-radius-${rounded}, 0.5rem)`,
        backgroundColor: BG,
      }}
    />
  );
});

export const SkeletonText = memo(function SkeletonText({ lines = 3, lastWidth = "60%" }: { lines?: number; lastWidth?: string }) {
  return (
    <div className="space-y-2.5">
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          height={12}
          width={i === lines - 1 ? lastWidth : "100%"}
        />
      ))}
    </div>
  );
});

export const SkeletonCard = memo(function SkeletonCard({ height = 96 }: { height?: number }) {
  return (
    <div
      className={`${PULSE} rounded-xl p-4`}
      style={{
        height,
        backgroundColor: "var(--dt-colors-surface-card, var(--dt-colors-bg-secondary))",
        border: "1px solid var(--dt-colors-border-default)",
      }}
    >
      <div className="flex items-start gap-3">
        <Skeleton width={40} height={40} rounded="md" />
        <div className="flex-1 space-y-2">
          <Skeleton width="50%" height={14} />
          <Skeleton width="80%" height={10} />
        </div>
      </div>
    </div>
  );
});

export const SkeletonTableRow = memo(function SkeletonTableRow({ cols = 4 }: { cols?: number }) {
  return (
    <div
      className={`${PULSE} flex items-center gap-4 p-3 rounded-xl`}
      style={{ backgroundColor: BG }}
    >
      {Array.from({ length: cols }).map((_, i) => (
        <Skeleton key={i} height={12} width={i === 0 ? "30%" : `${15 + Math.random() * 15}%`} />
      ))}
    </div>
  );
});

export const SkeletonCodeBlock = memo(function SkeletonCodeBlock({ lines = 5 }: { lines?: number }) {
  return (
    <div
      className={`${PULSE} rounded-xl p-4 space-y-2.5`}
      style={{ backgroundColor: BG }}
    >
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          height={10}
          width={i === lines - 1 ? "40%" : `${60 + Math.random() * 35}%`}
        />
      ))}
    </div>
  );
});

export const SkeletonPage = memo(function SkeletonPage({
  title,
  sections,
}: {
  title?: string;
  sections?: { type: "card" | "table" | "code" | "text"; count?: number }[];
}) {
  return (
    <div className="space-y-6">
      {title && <Skeleton width={200} height={28} />}
      {(sections ?? [{ type: "card", count: 3 }]).map((sec, i) => (
        <div key={i} className="space-y-3">
          {Array.from({ length: sec.count ?? 3 }).map((_, j) => {
            if (sec.type === "card") return <SkeletonCard key={j} />;
            if (sec.type === "table") return <SkeletonTableRow key={j} />;
            if (sec.type === "code") return <SkeletonCodeBlock key={j} />;
            return <SkeletonText key={j} />;
          })}
        </div>
      ))}
    </div>
  );
});
