"use client";

/**
 * DiffViewerDialog — 全屏 unified diff 查看器。
 *
 * 渲染解析后的 DiffFile，增/删/上下文行着色，左 gutter 行号。
 * 代码内容使用 highlight.js 做 token 级语法高亮（根据文件扩展名推断语言）。
 *
 * 高亮策略：
 * - 重建 new 版本（context + add）与 old 版本（context + del）
 * - 对完整版本做 highlight.js 高亮后按行分割（保留跨行 span 连续性）
 * - 映射回 diff各行，使多行字符串/注释也能正确着色
 */

import { useMemo, useState, useEffect } from "react";
import type { FileChangeItem } from "@/shared/types/api";
import { parseDiff } from "@/shared/lib/utils/diff";
import { getLanguageFromPath, highlightAndSplitLines } from "@/shared/lib/utils/highlight";
import { X, FileEdit, Copy, Check } from "lucide-react";

interface Props {
  item: FileChangeItem;
  onClose: () => void;
}

export function DiffViewerDialog({ item, onClose }: Props) {
  const diff = useMemo(
    () => (item.patch ? parseDiff(item.patch, item.path) : null),
    [item.patch, item.path],
  );
  const [copied, setCopied] = useState(false);

  // 语法高亮：重建 new/old 版本，高亮后按行分割，映射回 diff 行
  const lineHighlights = useMemo(() => {
    if (!diff) return null;

    const lang = getLanguageFromPath(diff.path);
    if (!lang) return null;

    // 重建 new 与 old 版本，同时记录行映射
    const newCodeLines: string[] = [];
    const oldCodeLines: string[] = [];
    const newLineMap: number[] = []; // newCodeLines 索引 → diff.lines 索引
    const oldLineMap: number[] = [];

    diff.lines.forEach((line, i) => {
      if (line.type === "add" || line.type === "context") {
        newCodeLines.push(line.content);
        newLineMap.push(i);
      }
      if (line.type === "del" || line.type === "context") {
        oldCodeLines.push(line.content);
        oldLineMap.push(i);
      }
    });

    // 高亮并按行分割
    const newHighlighted = highlightAndSplitLines(newCodeLines.join("\n"), lang);
    const oldHighlighted = highlightAndSplitLines(oldCodeLines.join("\n"), lang);

    // 映射回 diff 行
    const highlights = new Map<number, string>();
    newHighlighted.forEach((html, idx) => {
      const diffIdx = newLineMap[idx];
      if (diffIdx !== undefined && diff.lines[diffIdx].type !== "del") {
        highlights.set(diffIdx, html);
      }
    });
    oldHighlighted.forEach((html, idx) => {
      const diffIdx = oldLineMap[idx];
      if (diffIdx !== undefined && diff.lines[diffIdx].type === "del") {
        highlights.set(diffIdx, html);
      }
    });

    return highlights;
  }, [diff]);

  // ESC 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const copyPatch = () => {
    if (!item.patch) return;
    navigator.clipboard.writeText(item.patch);
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm animate-fade-in"
      onClick={onClose}
    >
      <div
        className="flex h-[85vh] w-[90vw] max-w-5xl flex-col rounded-lg border border-[hsl(var(--overlay)/0.1)] bg-[hsl(var(--surface))] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between border-b border-[hsl(var(--overlay)/0.05)] px-4 py-3">
          <div className="flex items-center gap-2 min-w-0">
            <FileEdit className="h-4 w-4 shrink-0 text-[hsl(var(--info))]" />
            <span className="font-mono text-sm text-foreground truncate">
              {item.path}
            </span>
            {diff && (
              <span className="shrink-0 font-mono text-xs flex items-center gap-2">
                <span className="text-[hsl(var(--primary))]">+{diff.added}</span>
                <span className="text-[hsl(var(--danger))]">-{diff.removed}</span>
              </span>
            )}
          </div>

          <div className="flex items-center gap-1">
            {item.patch && (
              <button
                onClick={copyPatch}
                className="rounded-md p-1.5 text-[hsl(var(--muted-foreground))] hover:text-foreground hover:bg-[hsl(var(--overlay)/0.05)] transition-colors focus-ring"
                title="Copy patch"
              >
                {copied ? (
                  <Check className="h-3.5 w-3.5 text-[hsl(var(--primary))]" />
                ) : (
                  <Copy className="h-3.5 w-3.5" />
                )}
              </button>
            )}
            <button
              onClick={onClose}
              className="rounded-md p-1.5 text-[hsl(var(--muted-foreground))] hover:text-foreground hover:bg-[hsl(var(--overlay)/0.05)] transition-colors focus-ring"
              title="Close (Esc)"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* diff 内容 */}
        <div className="flex-1 min-h-0 overflow-auto">
          {diff ? (
            <div className="font-mono text-xs">
              {diff.lines.map((line, i) => (
                <DiffRow
                  key={i}
                  line={line}
                  highlight={lineHighlights?.get(i)}
                />
              ))}
            </div>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-[hsl(var(--muted-foreground))]">
              No patch content
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function DiffRow({
  line,
  highlight,
}: {
  line: import("@/shared/lib/utils/diff").DiffLine;
  highlight?: string;
}) {
  if (line.type === "meta") {
    return (
      <div className="px-3 py-0.5 text-[hsl(var(--muted-foreground))] bg-[hsl(var(--overlay)/0.02)]">
        {line.content}
      </div>
    );
  }

  if (line.type === "hunk") {
    return (
      <div className="px-3 py-1 text-[hsl(var(--diff-hunk))] bg-[hsl(var(--diff-hunk)/0.08)] border-y border-[hsl(var(--diff-hunk)/0.15)]">
        {line.content}
      </div>
    );
  }

  const bg =
    line.type === "add"
      ? "bg-[hsl(var(--diff-add-bg)/0.1)]"
      : line.type === "del"
        ? "bg-[hsl(var(--diff-del-bg)/0.1)]"
        : "";
  // 前缀色：add 绿、del 红、context 默认
  const prefixColor =
    line.type === "add"
      ? "text-[hsl(var(--diff-add-fg))]"
      : line.type === "del"
        ? "text-[hsl(var(--diff-del-fg))]"
        : "text-[hsl(var(--muted-foreground))]";
  // 代码内容色：使用 foreground 让 hljs token 颜色正确显示；
  // del 行稍微弱化以区别于 add/context
  const codeColor = line.type === "del" ? "text-foreground/60" : "text-foreground";
  const prefix = line.type === "add" ? "+" : line.type === "del" ? "-" : " ";

  return (
    <div className={`flex ${bg}`}>
      <span className="w-12 shrink-0 select-none px-2 text-right text-[hsl(var(--muted-foreground))] bg-[hsl(var(--overlay)/0.02)]">
        {line.oldLine ?? ""}
      </span>
      <span className="w-12 shrink-0 select-none px-2 text-right text-[hsl(var(--muted-foreground))] bg-[hsl(var(--overlay)/0.02)] border-l border-[hsl(var(--overlay)/0.05)]">
        {line.newLine ?? ""}
      </span>
      <span className={`shrink-0 w-5 select-none text-center ${prefixColor}`}>{prefix}</span>
      <span
        className={`flex-1 px-2 whitespace-pre-wrap break-all ${codeColor}`}
        dangerouslySetInnerHTML={{ __html: highlight ?? escapeHtml(line.content || " ") }}
      />
    </div>
  );
}

/** HTML 转义（无高亮时的 fallback） */
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
