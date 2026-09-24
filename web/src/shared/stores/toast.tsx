"use client";

/**
 * Toast 通知系统（Context + useReducer）。
 *
 * 全局轻量通知，用于反馈操作结果（如复制成功、git 提交、错误等）。
 *
 * 使用：
 * - 顶层包裹 <ToastProvider>
 * - 组件内 const { toast } = useToast(); toast({ title, description, type })
 *
 * 特性：
 * - 自动消失（默认 3s，可配置 duration）
 * - 支持手动关闭
 * - 四种类型：success / error / info / warning
 * - 最多同时显示 5 条（超出移除最早的）
 */

import {
  createContext,
  useContext,
  useReducer,
  useCallback,
  useRef,
  type ReactNode,
} from "react";

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

export type ToastType = "success" | "error" | "info" | "warning";

export interface ToastItem {
  /** 唯一 ID（自增计数器） */
  id: number;
  /** 标题（粗体，必填） */
  title: string;
  /** 描述（次要文本，可选） */
  description?: string;
  /** 通知类型，决定图标与配色 */
  type: ToastType;
  /** 自动消失延迟（毫秒），0 表示不自动消失 */
  duration: number;
}

interface ToastState {
  toasts: ToastItem[];
}

type ToastAction =
  | { kind: "ADD"; toast: ToastItem }
  | { kind: "REMOVE"; id: number };

interface ToastOptions {
  title: string;
  description?: string;
  type?: ToastType;
  /** 自动消失延迟（毫秒），默认 3000，0 表示不自动消失 */
  duration?: number;
}

interface ToastContextValue {
  toasts: ToastItem[];
  /** 显示一条 toast 通知 */
  toast: (opts: ToastOptions) => void;
  /** 手动移除一条 toast */
  dismiss: (id: number) => void;
}

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

const MAX_TOASTS = 5;

function toastReducer(state: ToastState, action: ToastAction): ToastState {
  switch (action.kind) {
    case "ADD": {
      const toasts = [...state.toasts, action.toast];
      // 超出上限时移除最早的
      if (toasts.length > MAX_TOASTS) {
        return { toasts: toasts.slice(toasts.length - MAX_TOASTS) };
      }
      return { toasts };
    }
    case "REMOVE":
      return { toasts: state.toasts.filter((t) => t.id !== action.id) };
    default:
      return state;
  }
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(toastReducer, { toasts: [] });
  const idCounter = useRef(0);

  const toast = useCallback((opts: ToastOptions) => {
    const id = ++idCounter.current;
    const item: ToastItem = {
      id,
      title: opts.title,
      description: opts.description,
      type: opts.type ?? "info",
      duration: opts.duration ?? 3000,
    };
    dispatch({ kind: "ADD", toast: item });

    // 自动消失
    if (item.duration > 0) {
      setTimeout(() => {
        dispatch({ kind: "REMOVE", id });
      }, item.duration);
    }
  }, []);

  const dismiss = useCallback((id: number) => {
    dispatch({ kind: "REMOVE", id });
  }, []);

  return (
    <ToastContext.Provider value={{ toasts: state.toasts, toast, dismiss }}>
      {children}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within <ToastProvider>");
  }
  return ctx;
}
