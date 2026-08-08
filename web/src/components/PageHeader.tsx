import { type ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  description?: string;
  icon?: LucideIcon;
  actions?: ReactNode;
}

export default function PageHeader({ title, subtitle, description, icon: Icon, actions }: PageHeaderProps) {
  return (
    <div className="flex items-start justify-between gap-4 mb-6">
      <div className="flex items-start gap-3 min-w-0">
        {Icon && (
          <div
            className="mt-0.5 w-9 h-9 shrink-0 rounded-xl flex items-center justify-center"
            style={{
              backgroundColor: "var(--dt-colors-accent-muted)",
              color: "var(--dt-colors-accent-default)",
            }}
          >
            <Icon size={18} />
          </div>
        )}
        <div className="min-w-0">
          <h1 className="page-title">{title}</h1>
          <p className="page-subtitle mt-1.5">{description ?? subtitle}</p>
        </div>
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </div>
  );
}
