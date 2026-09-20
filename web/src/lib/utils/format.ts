/**
 * 显示格式化工具：token 数、时间、路径、reasoning summary。
 */

/** 格式化 token 数（1234 → 1.2k） */
export function formatTokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1000000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1000000).toFixed(2)}M`;
}

/**
 * 格式化持续时长（毫秒 → 可读），对齐 codex cli 的 "Xm Ys" 风格。
 * - < 60s：保留 1 位小数（如 "12.3s"）
 * - >= 60s：分 + 整秒（如 "2m 1s"）
 */
export function formatDuration(ms?: number): string | null {
  if (!ms || !Number.isFinite(ms) || ms <= 0) return null;
  const sec = ms / 1000;
  if (sec < 60) return `${sec.toFixed(1)}s`;
  const min = Math.floor(sec / 60);
  const remSec = Math.round(sec % 60);
  return `${min}m ${remSec}s`;
}

/**
 * 从 reasoning.summary 数组提取明文文本。
 *
 * codex rollout 中 reasoning.summary 的实际结构是对象数组：
 * [{ "type": "summary_text", "text": "..." }, ...]
 * 而非字符串数组。CLI 显示的明文思考过程即来自此处。
 *
 * 本函数安全提取所有 summary_text 项的 text 字段并拼接，
 * 容错处理：元素可能是字符串、对象、或其他类型。
 *
 * @param summary reasoning.summary 原始值（未知类型）
 * @returns 拼接后的明文摘要（可能为空字符串）
 */
export function extractReasoningSummaryText(summary: unknown): string {
  if (!Array.isArray(summary)) return "";
  return summary
    .map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object" && typeof (item as { text?: unknown }).text === "string") {
        return (item as { text: string }).text;
      }
      return "";
    })
    .filter((s) => s.length > 0)
    .join("\n");
}

/** 缩短路径：C:\Users\alice\projects\foo → ~/projects/foo */
export function shortPath(p: string): string {
  if (!p) return "";
  const home = typeof process !== "undefined" && process.env
    ? (process.env.USERPROFILE || process.env.HOME || "")
    : "";
  if (home && (p.startsWith(home) || p.toLowerCase().startsWith(home.toLowerCase()))) {
    return "~" + p.slice(home.length).replace(/\\/g, "/");
  }
  // 仅保留最后两段
  const parts = p.replace(/\\/g, "/").split("/").filter(Boolean);
  if (parts.length <= 2) return p;
  return "…/" + parts.slice(-2).join("/");
}

/** 提取项目名：取 cwd 最后一段作为项目名（如 D:\Projects\foo → foo） */
export function projectName(p: string): string {
  if (!p) return "(no project)";
  const parts = p.replace(/\\/g, "/").replace(/\/+$/, "").split("/").filter(Boolean);
  return parts.length > 0 ? parts[parts.length - 1] : "(no project)";
}

/**
 * Codex desktop stores ad-hoc conversations under Documents/Codex/<date>/….
 * These directories are session artifacts, not user projects, so the sidebar
 * groups them under one virtual "standalone conversations" entry.
 */
export function isStandaloneConversationCwd(p: string): boolean {
  if (!p) return false;
  const normalized = p.replace(/\//g, "\\").replace(/\\+$/, "");
  return /^[a-z]:\\users\\[^\\]+\\documents\\codex\\.+/i.test(normalized);
}

/**
 * 规范化 cwd：Windows 驱动器字母统一大写。
 *
 * Windows 路径不区分大小写，但 codex CLI 传入的 cwd 可能因启动方式不同
 * 出现 `d:\Projects\foo` 与 `D:\Projects\foo` 两种形式。归一化后：
 * - 分组 key 用 toLowerCase 做大小写无关比较
 * - 显示路径统一为首字母大写，避免同一项目出现两个条目
 *
 * 仅处理驱动器字母开头（如 `d:\` / `D:\`），其余路径原样返回。
 */
export function normalizeCwd(p: string): string {
  if (!p) return p;
  const driveMatch = p.match(/^([a-zA-Z]):([\\/])(.*)$/);
  if (driveMatch) {
    return `${driveMatch[1].toUpperCase()}:${driveMatch[2]}${driveMatch[3]}`;
  }
  return p;
}

/** 格式化时间戳为简短形式 */
export function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    if (sameDay) {
      return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
    }
    const sameYear = d.getFullYear() === now.getFullYear();
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      ...(sameYear ? {} : { year: "numeric" }),
    });
  } catch {
    return iso;
  }
}

/** 格式化 item 时间戳为带秒的简短形式（HH:MM:SS 或 MM-DD HH:MM:SS） */
export function formatItemTime(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    const time = d.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
    if (sameDay) return time;
    const sameYear = d.getFullYear() === now.getFullYear();
    const date = d.toLocaleDateString("en-US", {
      month: "2-digit",
      day: "2-digit",
      ...(sameYear ? {} : { year: "2-digit" }),
    });
    return `${date} ${time}`;
  } catch {
    return iso;
  }
}

/** 相对时间（3m ago / 2h ago / 1d ago） */
export function timeAgo(iso: string): string {
  try {
    const d = new Date(iso).getTime();
    const now = Date.now();
    const diff = Math.max(0, now - d);
    const sec = Math.floor(diff / 1000);
    if (sec < 60) return "just now";
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min}m ago`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}h ago`;
    const day = Math.floor(hr / 24);
    if (day < 30) return `${day}d ago`;
    return formatTime(iso);
  } catch {
    return iso;
  }
}
