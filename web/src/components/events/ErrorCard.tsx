"use client";

/**
 * ErrorCard — 顶层错误 / item 错误。
 *
 * severity="warning" 时以黄色警告样式显示（如 codex CLI 的 skills context budget 截断提示），
 * 其余以红色错误样式显示。
 */

import type { ErrorItem } from "@/types/api";
import { AlertTriangle, Info } from "lucide-react";

interface Props {
  item: ErrorItem;
}

export function ErrorCard({ item }: Props) {
  const isWarning = item.severity === "warning";

  const icon = isWarning ? (
    <Info className="h-3.5 w-3.5 text-[hsl(var(--accent))]" />
  ) : (
    <AlertTriangle className="h-3.5 w-3.5 text-[hsl(var(--danger))]" />
  );

  const labelColor = isWarning
    ? "text-[hsl(var(--accent))]"
    : "text-[hsl(var(--danger))]";

  const borderColor = isWarning
    ? "border-[hsl(var(--accent)/0.3)] bg-[hsl(var(--accent)/0.08)]"
    : "border-[hsl(var(--danger)/0.3)] bg-[hsl(var(--danger)/0.08)]";

  return (
    <div className="timeline-item flex gap-3 py-2 px-2">
      <div
        className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md border ${borderColor}`}
      >
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className={`mb-1 font-mono text-[10px] uppercase tracking-wider ${labelColor}`}>
          {isWarning ? "warning" : "error"}
        </div>
        <div className="text-sm text-foreground/90 whitespace-pre-wrap">
          {item.message}
        </div>
      </div>
    </div>
  );
}
