import { AnimatePresence, motion } from "framer-motion";
import {
  Bot,
  BrainCircuit,
  CheckCircle2,
  GitBranch,
  ListChecks,
  Loader2,
  ShieldAlert,
  TerminalSquare,
  Wrench,
  XCircle,
} from "lucide-react";
import type { ReactNode } from "react";
import { useMemo } from "react";

export interface AgentEvent {
  type: string;
  event: string;
  profile: string;
  detail?: string;
  ts?: number;
  data?: Record<string, unknown>;
}

type Phase = "plan" | "execute" | "critic" | "done" | "error";

interface EventMeta {
  label: string;
  tone: "default" | "success" | "error" | "accent";
  icon: ReactNode;
}

const PROFILE_LABELS: Record<string, string> = {
  planner: "Планировщик",
  architect: "Архитектор",
  coder: "Исполнитель",
  reviewer: "Ревьюер",
  debugger: "Отладчик",
  qa: "QA",
  researcher: "Исследователь",
  security: "Security",
};

const EVENT_META: Record<string, EventMeta> = {
  agent_started: { label: "Агент запущен", tone: "accent", icon: <Bot className="w-4 h-4" /> },
  agent_completed: { label: "Задача завершена", tone: "success", icon: <CheckCircle2 className="w-4 h-4" /> },
  planning: { label: "Анализ запроса", tone: "accent", icon: <BrainCircuit className="w-4 h-4" /> },
  plan_created: { label: "План создан", tone: "accent", icon: <ListChecks className="w-4 h-4" /> },
  step_started: { label: "Шаг выполняется", tone: "accent", icon: <TerminalSquare className="w-4 h-4" /> },
  tool_call: { label: "Вызов инструмента", tone: "default", icon: <Wrench className="w-4 h-4" /> },
  tool_result: { label: "Результат инструмента", tone: "default", icon: <CheckCircle2 className="w-4 h-4" /> },
  thinking: { label: "Размышление", tone: "default", icon: <BrainCircuit className="w-4 h-4" /> },
  critic_started: { label: "Критик ревьюит", tone: "accent", icon: <ShieldAlert className="w-4 h-4" /> },
  handoff: { label: "Передача агенту", tone: "accent", icon: <GitBranch className="w-4 h-4" /> },
  error: { label: "Ошибка", tone: "error", icon: <XCircle className="w-4 h-4" /> },
};

const PHASE_ORDER: Record<Phase, number> = { plan: 0, execute: 1, critic: 2, done: 3, error: 4 };

function phaseOf(event: AgentEvent): Phase {
  if (event.event === "agent_completed") return "done";
  if (event.event === "error") return "error";
  if (event.event === "critic_started") return "critic";
  if (event.event === "agent_started" || event.event === "planning" || event.event === "plan_created") return "plan";
  return "execute";
}

const TONE_CLASSES: Record<EventMeta["tone"], string> = {
  default: "text-secondary bg-tertiary border-default",
  accent: "text-accent bg-accent-muted border-[var(--dt-colors-accent-muted)]",
  success: "text-success bg-success-muted border-[var(--dt-colors-status-success)]",
  error: "text-danger bg-danger-muted border-[var(--dt-colors-status-error)]",
};

function ProfileBadge({ profile }: { profile: string }) {
  return (
    <span className="px-1.5 py-0.5 rounded-md bg-tertiary border border-default text-[10px] font-mono uppercase tracking-wide text-secondary">
      {PROFILE_LABELS[profile] ?? profile}
    </span>
  );
}

function PlanSteps({ steps }: { steps: unknown }) {
  const items = Array.isArray(steps) ? steps.filter((s): s is string => typeof s === "string") : [];
  if (items.length === 0) return null;
  return (
    <ol className="mt-2 space-y-1">
      {items.map((step, i) => (
        <motion.li
          key={i}
          initial={{ opacity: 0, x: -8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: i * 0.05 }}
          className="flex items-start gap-2 text-sm text-secondary"
        >
          <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-accent-muted text-[10px] font-bold text-accent">
            {i + 1}
          </span>
          {step}
        </motion.li>
      ))}
    </ol>
  );
}

function EventRow({ event }: { event: AgentEvent }) {
  const meta = EVENT_META[event.event] ?? { label: event.event, tone: "default" as const, icon: <Bot className="w-4 h-4" /> };
  const detail = event.detail ?? "";
  const data = event.data;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ type: "spring", damping: 26, stiffness: 320 }}
      className="flex gap-3"
    >
      <div className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border ${TONE_CLASSES[meta.tone]}`}>
        {meta.icon}
      </div>
      <div className="min-w-0 flex-1 pb-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-primary">{meta.label}</span>
          <ProfileBadge profile={event.profile} />
        </div>
        {detail && detail !== meta.label && (
          <p className="mt-0.5 break-words text-sm text-secondary">{detail}</p>
        )}
        {event.event === "plan_created" && <PlanSteps steps={data?.steps} />}
        {event.event === "tool_call" && Boolean(data?.args) && (
          <pre className="mt-1.5 overflow-x-auto rounded-lg border border-default bg-primary px-3 py-2 text-xs text-secondary">
            {JSON.stringify(data?.args, null, 2)}
          </pre>
        )}
        {event.event === "tool_result" && detail.startsWith("error") && (
          <span className="mt-1 inline-flex items-center gap-1 text-xs text-danger">
            <XCircle className="w-3 h-3" /> {detail}
          </span>
        )}
      </div>
    </motion.div>
  );
}

function PhaseTracker({ events }: { events: AgentEvent[] }) {
  const phases = useMemo(() => {
    const order: Phase[] = ["plan", "execute", "critic", "done"];
    const seen = new Set<Phase>();
    for (const event of events) {
      const phase = phaseOf(event);
      seen.add(phase);
    }
    return order.filter((p) => seen.has(p));
  }, [events]);

  const currentIndex = useMemo(() => {
    let last = 0;
    for (const event of events) {
      const phase = phaseOf(event);
      const idx = PHASE_ORDER[phase];
      if (phase === "done" || phase === "error") return orderIndex(phase);
      if (idx > last) last = idx;
    }
    return last;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events]);

  function orderIndex(phase: Phase): number {
    return PHASE_ORDER[phase];
  }

  const labels: Record<Phase, string> = {
    plan: "План",
    execute: "Исполнение",
    critic: "Ревью",
    done: "Готово",
    error: "Ошибка",
  };

  return (
    <div className="flex items-center gap-1.5">
      {phases.map((phase, i) => (
        <div key={phase} className="flex items-center gap-1.5">
          {i > 0 && <div className="h-px w-4 bg-[var(--dt-colors-border-default)]" />}
          <div
            className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium transition-colors ${
              orderIndex(phase) <= currentIndex
                ? "bg-accent-muted text-accent border border-[var(--dt-colors-accent-muted)]"
                : "bg-tertiary text-tertiary border border-default"
            }`}
          >
            {labels[phase]}
          </div>
        </div>
      ))}
    </div>
  );
}

export function AgentStream({ events }: { events: AgentEvent[] }) {
  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 py-10 text-center text-tertiary">
        <Bot className="w-8 h-8 text-tertiary" />
        <p className="text-sm">Агент пока бездействует. Отправьте запрос — здесь появится живой поток работы.</p>
      </div>
    );
  }

  const isRunning = !events.some((e) => e.event === "agent_completed" || e.event === "error");

  return (
    <div className="card p-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="flex h-2 w-2">
            {isRunning && (
              <span className="relative inline-flex h-2 w-2 rounded-full bg-[var(--dt-colors-accent-default)]">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[var(--dt-colors-accent-default)] opacity-60" />
              </span>
            )}
            {!isRunning && <span className="h-2 w-2 rounded-full bg-[var(--dt-colors-status-success)]" />}
          </span>
          <span className="text-sm font-semibold text-primary">Flow State</span>
        </div>
        <PhaseTracker events={events} />
      </div>
      <div className="space-y-0">
        <AnimatePresence initial={false}>
          {events.map((event, i) => (
            <EventRow key={`${event.event}-${i}`} event={event} />
          ))}
        </AnimatePresence>
      </div>
      {isRunning && (
        <div className="mt-2 flex items-center gap-2 text-xs text-accent">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Агенты работают...
        </div>
      )}
    </div>
  );
}
