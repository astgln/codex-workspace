"use client";

/**
 * AgentMessageCard — agent 消息（markdown 渲染，支持 LaTeX + 代码高亮）。
 *
 * 头像/名字分组逻辑：
 * - showHeader=true（每轮首个 agent_message）：显示 codex 头像 + 名字 + 时间戳
 * - showHeader=false（同一轮后续续接消息）：不显示头像/名字，仅缩进对齐正文，保持回复连贯
 *
 * 头像使用 codex 官方 logo（logo/codex-color.svg），渐变色适配深/浅色主题。
 *
 * Копировать功能：
 * - 鼠标悬停消息卡片时，右下角浮出「Копировать」按钮
 * - 点击Копировать原始 markdown 文本（item.text），Копировать成功后短暂切换为「Скопировано」
 */

import { useState, useCallback } from "react";
import type { AgentMessageItem } from "@/types/api";
import { Copy, Check, Bot } from "lucide-react";
import { Markdown } from "./Markdown";
import { formatItemTime } from "@/lib/utils/format";
import { useToast } from "@/stores/toast";
// codex 官方 logo：渐变色 SVG。
// Next.js 15 静态导入 SVG 返回 StaticImageData 对象（{ src, width, height }），
// 而非 URL 字符串，故取 .src 得到实际资源 URL；兼容字符串导入的旧版本。


interface Props {
  item: AgentMessageItem;
  /** item 时间戳（ISO 字符串） */
  timestamp?: string;
  /** 是否显示头像+名字（每轮首个 agent_message 为 true） */
  showHeader?: boolean;
}

export function AgentMessageCard({ item, timestamp, showHeader = true }: Props) {
  const [copied, setCopied] = useState(false);
  const { toast } = useToast();

  const copy = useCallback(() => {
    navigator.clipboard.writeText(item.text ?? "").then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
      toast({ title: "Скопировано", description: "内容Скопировано到剪贴板", type: "success", duration: 2000 });
    }).catch(() => {
      toast({ title: "Не удалось скопировать", description: "Выделите текст вручную", type: "error", duration: 3000 });
    });
  }, [item.text, toast]);

  // 续接消息（同一轮后续）：不显示头像/名字，缩进对齐正文（与有头像时的正文左边界对齐）
  // 但仍显示时间戳，方便定位每条子回复的时间
  if (!showHeader) {
    return (
      <div className="timeline-item group relative py-1.5 pl-11 pr-2">
        {timestamp && (
          <div className="mb-0.5 flex justify-end">
            <span
              className="text-xs text-[hsl(var(--muted-foreground))]/60"
              title={new Date(timestamp).toString()}
            >
              {formatItemTime(timestamp)}
            </span>
          </div>
        )}
        <Markdown>{item.text}</Markdown>
        <CopyButton copied={copied} onCopy={copy} />
      </div>
    );
  }

  // 首个回复：显示头像 + 名字 + 时间戳
  return (
    <div className="timeline-item group relative flex gap-3 py-2 px-2">
      {/* 头像：无边框无背景，仅 logo 本身 */}
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center">
        {/* codex 官方 logo（渐变色），size 24px */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <Bot aria-hidden="true" className="h-6 w-6" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="mb-1.5 flex items-center gap-2">
          <span className="text-sm font-semibold text-foreground">
            codex
          </span>
          {timestamp && (
            <span
              className="text-xs text-[hsl(var(--muted-foreground))]"
              title={new Date(timestamp).toString()}
            >
              {formatItemTime(timestamp)}
            </span>
          )}
        </div>
        <Markdown>{item.text}</Markdown>
      </div>
      <CopyButton copied={copied} onCopy={copy} />
    </div>
  );
}

/**
 * Копировать按钮：悬停消息卡片（group-hover）或聚焦时显示，Копировать后短暂切换为「Скопировано」。
 * 定位在卡片右下角，不遮挡正文。
 */
function CopyButton({ copied, onCopy }: { copied: boolean; onCopy: () => void }) {
  return (
    <button
      onClick={onCopy}
      className="absolute bottom-1 right-2 flex items-center gap-1 rounded-md p-1 text-[hsl(var(--muted-foreground))] opacity-0 transition-opacity hover:bg-[hsl(var(--overlay)/0.05)] hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100 focus-ring"
      title={copied ? "Скопировано" : "Копировать"}
      aria-label={copied ? "Скопировано" : "Копировать"}
    >
      {copied ? (
        <Check className="h-3 w-3 text-[hsl(var(--primary))]" />
      ) : (
        <Copy className="h-3 w-3" />
      )}
    </button>
  );
}
