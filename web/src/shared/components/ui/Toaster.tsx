"use client";

/**
 * Toaster — 全局通知渲染器（固定在右下角）。
 *
 * 消费 ToastProvider 的 toasts 状态，渲染通知卡片：
 * - 每条通知含图标、标题、描述、关闭按钮
 * - 不同类型对应不同配色（success 绿 / error 红 / info 蓝 / warning 黄）
 * - 入场动画：从右滑入 + 淡入
 *
 * 需在 ToastProvider 内部使用，通常放在 AppShell 末尾。
 */

import { useToast, type ToastType } from "@/shared/stores/toast";
import { CheckCircle2, XCircle, Info, AlertTriangle, X } from "lucide-react";

/** 类型 → 图标映射 */
const ICONS: Record<ToastType, typeof CheckCircle2> = {
  success: CheckCircle2,
  error: XCircle,
  info: Info,
  warning: AlertTriangle,
};

/** 类型 → 配色映射（复用 theme 变量：primary=emerald/成功, accent=amber/警告, danger=rose/错误, info=blue/信息） */
const STYLES: Record<ToastType, { icon: string; border: string }> = {
  success: {
    icon: "text-[hsl(var(--primary))]",
    border: "border-l-[hsl(var(--primary))]",
  },
  error: {
    icon: "text-[hsl(var(--danger))]",
    border: "border-l-[hsl(var(--danger))]",
  },
  info: {
    icon: "text-[hsl(var(--info))]",
    border: "border-l-[hsl(var(--info))]",
  },
  warning: {
    icon: "text-[hsl(var(--accent))]",
    border: "border-l-[hsl(var(--accent))]",
  },
};

export function Toaster() {
  const { toasts, dismiss } = useToast();

  if (toasts.length === 0) return null;

  return (
    <div
      className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-80 flex-col gap-2"
      role="region"
      aria-label="通知"
    >
      {toasts.map((t) => {
        const Icon = ICONS[t.type];
        const style = STYLES[t.type];
        return (
          <div
            key={t.id}
            className={`pointer-events-auto flex items-start gap-2.5 rounded-md border border-[hsl(var(--overlay)/0.1)] border-l-2 ${style.border} bg-[hsl(var(--surface))] px-3 py-2.5 shadow-lg animate-in slide-in-from-right fade-in duration-200`}
            role="alert"
          >
            <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${style.icon}`} />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-foreground">{t.title}</p>
              {t.description && (
                <p className="mt-0.5 text-xs text-[hsl(var(--muted-foreground))]">
                  {t.description}
                </p>
              )}
            </div>
            <button
              onClick={() => dismiss(t.id)}
              className="shrink-0 rounded-md p-0.5 text-[hsl(var(--muted-foreground))] hover:text-foreground hover:bg-[hsl(var(--overlay)/0.05)] transition-colors focus-ring"
              aria-label="关闭通知"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
