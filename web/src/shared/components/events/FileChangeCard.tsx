"use client";

/**
 * FileChangeCard — 文件改动摘要。
 *
 * 显示路径 + change 类型 + +N/-M 摘要，点击打开 DiffViewerDialog。
 */

import { useMemo } from "react";
import type { FileChangeItem } from "@/shared/types/api";
import { FilePlus, FileEdit, FileX, FileOutput, ChevronRight } from "lucide-react";

interface Props {
  item: FileChangeItem;
  onOpenDiff: (item: FileChangeItem) => void;
}

const CHANGE_META: Record<
  FileChangeItem["change"],
  { icon: typeof FileEdit; color: string; label: string }
> = {
  create: { icon: FilePlus, color: "var(--primary)", label: "create" },
  edit: { icon: FileEdit, color: "var(--info)", label: "edit" },
  delete: { icon: FileX, color: "var(--danger)", label: "delete" },
  rename: { icon: FileOutput, color: "var(--accent)", label: "rename" },
};

export function FileChangeCard({ item, onOpenDiff }: Props) {
  const meta = CHANGE_META[item.change] ?? CHANGE_META.edit;
  const Icon = meta.icon;

  const stats = useMemo(() => countDiffStats(item.patch), [item.patch]);
  const clickable = !!item.patch && (item.change === "edit" || item.change === "create");

  return (
    <div className="timeline-item py-1.5 px-2">
      <button
        onClick={() => clickable && onOpenDiff(item)}
        disabled={!clickable}
        className={`flex w-full items-center gap-2 rounded-md border border-[hsl(var(--overlay)/0.05)] bg-[hsl(var(--surface-2))] px-2 py-1.5 text-left transition-colors focus-ring ${
          clickable ? "hover:bg-[hsl(var(--overlay)/0.05)] cursor-pointer" : "cursor-default"
        }`}
      >
        <Icon
          className="h-3.5 w-3.5 shrink-0"
          style={{ color: `hsl(${meta.color})` }}
        />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-foreground/90 truncate">
              {item.path}
            </span>
            {item.change === "rename" && item.oldPath && (
              <>
                <span className="font-mono text-[10px] text-[hsl(var(--muted-foreground))]">
                  ←
                </span>
                <span className="font-mono text-[10px] text-[hsl(var(--muted-foreground))] truncate">
                  {item.oldPath}
                </span>
              </>
            )}
          </div>
        </div>

        {/* 改动统计 */}
        {stats && (
          <span className="shrink-0 font-mono text-[10px] flex items-center gap-1.5">
            <span className="text-[hsl(var(--primary))]">+{stats.added}</span>
            <span className="text-[hsl(var(--danger))]">-{stats.removed}</span>
          </span>
        )}

        <span
          className="shrink-0 rounded-md px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider"
          style={{
            color: `hsl(${meta.color})`,
            background: `hsl(${meta.color} / 0.1)`,
          }}
        >
          {meta.label}
        </span>

        {clickable && (
          <ChevronRight className="h-3 w-3 shrink-0 text-[hsl(var(--muted-foreground))]" />
        )}
      </button>
    </div>
  );
}

/** 从 unified diff 统计增删行数 */
function countDiffStats(patch?: string): { added: number; removed: number } | null {
  if (!patch) return null;
  let added = 0;
  let removed = 0;
  for (const line of patch.split("\n")) {
    if (line.startsWith("+++") || line.startsWith("---")) continue;
    if (line.startsWith("+")) added++;
    else if (line.startsWith("-")) removed++;
  }
  return { added, removed };
}
