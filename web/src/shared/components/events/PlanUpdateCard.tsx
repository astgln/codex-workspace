"use client";

/**
 * PlanUpdateCard — 计划更新（步骤列表）。
 */

import type { PlanUpdateItem } from "@/shared/types/api";
import { ListChecks, Circle, CheckCircle2, XCircle, Loader2 } from "lucide-react";

interface Props {
  item: PlanUpdateItem;
}

export function PlanUpdateCard({ item }: Props) {
  const steps = item.plan ?? [];
  if (steps.length === 0 && !item.status) return null;

  return (
    <div className="timeline-item py-1.5 px-2">
      <div className="flex items-center gap-2 mb-1.5">
        <ListChecks className="h-3.5 w-3.5 text-[hsl(var(--info)/0.8)]" />
        <span className="font-mono text-[10px] uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
          plan
        </span>
        {item.status && (
          <span className="font-mono text-[10px] text-foreground/70">{item.status}</span>
        )}
      </div>

      {steps.length > 0 && (
        <ol className="ml-5 space-y-0.5">
          {steps.map((step, i) => (
            <li key={i} className="flex items-start gap-2 text-xs">
              <StepIcon status={step.status} />
              <span
                className={
                  step.status === "completed"
                    ? "text-[hsl(var(--muted-foreground))] line-through"
                    : "text-foreground/80"
                }
              >
                {step.step}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function StepIcon({ status }: { status: string }) {
  const s = status.toLowerCase();
  if (s === "completed" || s === "done")
    return <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-[hsl(var(--primary))]" />;
  if (s === "failed" || s === "error")
    return <XCircle className="mt-0.5 h-3 w-3 shrink-0 text-[hsl(var(--danger))]" />;
  if (s === "in_progress" || s === "running")
    return <Loader2 className="mt-0.5 h-3 w-3 shrink-0 animate-spin text-[hsl(var(--info))]" />;
  return <Circle className="mt-0.5 h-3 w-3 shrink-0 text-[hsl(var(--muted-foreground))]" />;
}
