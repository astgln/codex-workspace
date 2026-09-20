"use client";

/**
 * Markdown — 统一的 Markdown 渲染组件。
 *
 * 支持：
 * - GitHub Flavored Markdown（表格、删除线、任务列表）
 * - LaTeX 数学公式（$...$ 行内、$$...$$ 块级），通过 remark-math + rehype-katex
 * - 代码语法高亮，通过 rehype-highlight + highlight.js
 *
 * LaTeX 分隔符预处理：
 * - codex/GPT 输出的 LaTeX 常用 \[...\]（display）和 \(...\)（inline）
 * - remark-math 仅支持 $...$ 和 $$...$$，故在渲染前做转换
 * - 同时处理 \begin{...}...\end{...} 环境（包裹为 $$...$$）
 *
 * 主题适配：
 * - 代码块使用 surface-2 背景，适配 light/dark
 * - 行内 code 使用 overlay 半透明背景
 * - katex 与 hljs 样式在 globals.css 中导入
 */

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeHighlight from "rehype-highlight";
import { memo, useEffect, useMemo, useState } from "react";
import { ImageOff } from "lucide-react";
import { mapMarkdownImageSource } from "@/lib/codex/markdown-image";
import { useLanguage } from "@/components/i18n/LanguageProvider";

interface MarkdownProps {
  /** 允许 undefined/null/空字符串，组件内部做容错（exec 流可能透传缺失 text 的 item） */
  children?: string | null;
  className?: string;
}

/**
 * 将 LaTeX 通用分隔符转换为 remark-math 支持的 $ / $$ 分隔符。
 *
 * 转换规则：
 * 1. \[...\] → $$...$$（display math，非贪婪，跨行）
 * 2. \(...\) → $...$（inline math，同行）
 * 3. 独立的 \begin{env}...\end{env} → 包裹为 $$...$$
 *
 * 同时处理代码块语言标记：
 * - Codex CLI 常用 ```text 标记代码块，但其中可能是 Python/JS 等实际代码
 * - 对 text/plaintext/plain 标记的代码块，用启发式规则检测实际语言并显式指定
 * - 检测失败时去除语言标记，由 rehype-highlight 的 detect:true 自动检测
 * - 保留显式指定的语言（如 ```python、```typescript）
 *
 * 注意：不处理代码块内的内容（``` 或 ~~~ 之间的内容）。
 */

/**
 * 启发式检测代码块的语言。
 *
 * Codex CLI 常用 ```text 标记所有代码块，但其中可能是 Python/JS/Shell 等实际代码。
 * highlight.js 的 auto-detect 对 `key = value` 格式容易误判为 ini，
 * 因此在预处理阶段用关键词启发式显式指定语言，提升高亮准确度。
 *
 * 检测顺序（按特异性从高到低）：
 * 1. Python 关键字（def/class/import/from/self/lambda/yield/raise/elif/except）
 * 2. JS/TS 关键字（const/let/var/function/=>/console/require）
 * 3. Shell 特征（#!/shebang、cd/mkdir/rm/echo/export/sudo）
 * 4. JSON（以 { 或 [ 开头且能解析）
 * 5. Python-like 回退：有 `var = func(` 赋值调用且无分号
 *
 * @returns 检测到的 highlight.js 语言名，未检测到返回 null
 */
function detectCodeLanguage(code: string): string | null {
  // Python 关键字（特异性最高）
  if (/\b(def\s+\w+\s*\(|class\s+\w+\s*[(:]|from\s+\w+\s+import|import\s+\w+|if\s+__name__|self\.|lambda\s+|yield\s+|raise\s+|elif\s+|except\s+\w*|with\s+\w+\s+as\s+|@\w+\s*$)/m.test(code)) {
    return "python";
  }
  // JS/TS 关键字
  if (/\b(const\s+\w+\s*=|let\s+\w+\s*=|var\s+\w+\s*=|function\s+\w+\s*\(|=>\s|console\.log|require\s*\(|import\s+\w+\s+from\s+['"])/m.test(code)) {
    return "typescript";
  }
  // Shell 特征
  if (/^(#!\/|cd\s+\S|mkdir\s|rm\s+-|cp\s|mv\s|echo\s|export\s|sudo\s|pip\s|npm\s|git\s)/m.test(code)) {
    return "bash";
  }
  // JSON：以 { 或 [ 开头且能解析
  const trimmed = code.trim();
  if ((trimmed.startsWith("{") || trimmed.startsWith("[")) && (trimmed.endsWith("}") || trimmed.endsWith("]"))) {
    try {
      JSON.parse(trimmed);
      return "json";
    } catch {
      // not valid JSON
    }
  }
  // Python-like 回退：有 `var = func(` 赋值调用且无分号（排除 JS）
  if (/\w+\s*=\s*\w+\s*\(/.test(code) && !code.includes(";")) {
    return "python";
  }
  return null;
}

function preprocessLatex(text: string | null | undefined): string {
  // 容错：exec 流或 rollout 可能传入 undefined/null
  if (!text || typeof text !== "string") return "";

  // 先按代码块分割，只处理非代码部分
  const codeBlockRegex = /(```[\s\S]*?```|~~~[\s\S]*?~~~)/g;
  const parts = text.split(codeBlockRegex);

  return parts
    .map((part, idx) => {
      // 偶数索引为非代码部分，奇数索引为代码块
      if (idx % 2 === 1) {
        // 代码块语言处理：
        // 1. 提取围栏标记与语言
        const fenceMatch = part.match(/^(```|~~~)(\w*)/);
        if (!fenceMatch) return part;
        const fence = fenceMatch[1];
        const lang = fenceMatch[2].toLowerCase();

        // 仅处理 text/plaintext/plain 标记的代码块
        if (lang === "text" || lang === "plaintext" || lang === "plain" || lang === "") {
          // 提取代码内容（去掉首行围栏和末尾围栏）
          const codeContent = part.replace(/^(```|~~~)\w*\n?/, "").replace(/(```|~~~)\s*$/, "");
          const detected = detectCodeLanguage(codeContent);
          if (detected) {
            // 显式指定检测到的语言
            return part.replace(/^(```|~~~)\w*/, `${fence}${detected}`);
          }
          // 未检测到：去除语言标记，由 detect:true 自动检测
          return part.replace(/^(```|~~~)\w*/, fence);
        }
        return part;
      }

      let result = part;

      // \[...\] → $$...$$（display math，跨行）
      result = result.replace(
        /\\\[([\s\S]*?)\\\]/g,
        (_, content) => `$$${content}$$`,
      );

      // \(...\) → $...$（inline math）
      result = result.replace(
        /\\\(([\s\S]*?)\\\)/g,
        (_, content) => `$${content}$`,
      );

      // 独立的 \begin{...}...\end{...} → 包裹为 $$...$$
      // 仅匹配未被 $$ 包裹的 \begin/\end
      result = result.replace(
        /(?<!\$)\\begin\{(\w+)\}([\s\S]*?)\\end\{\1\}(?!\$)/g,
        (_, env, content) => `$$\\begin{${env}}${content}\\end{${env}}$$`,
      );

      return result;
    })
    .join("");
}

function MarkdownImpl({ children, className }: MarkdownProps) {
  // 预处理 LaTeX 分隔符（memoized，避免每次渲染都做正则替换）
  // 注意：useMemo 必须在条件返回之前调用（Rules of Hooks）
  const processed = useMemo(() => preprocessLatex(children), [children]);

  // 容错：空内容直接返回 null，避免渲染空 prose 容器
  if (!processed) return null;
  return (
    <div
      className={`prose prose-base min-w-0 max-w-none overflow-hidden [overflow-wrap:anywhere] text-foreground/90
        prose-p:my-2 prose-p:leading-7
        prose-headings:font-semibold prose-headings:tracking-tight prose-headings:text-foreground prose-headings:my-3
        prose-code:font-mono prose-code:text-[0.9em] prose-code:text-[hsl(var(--primary))] prose-code:bg-[hsl(var(--overlay)/0.06)] prose-code:rounded prose-code:px-1 prose-code:py-0.5 prose-code:before:content-none prose-code:after:content-none
        prose-pre:max-w-full prose-pre:bg-[hsl(var(--surface-2))] prose-pre:border prose-pre:border-[hsl(var(--overlay)/0.08)] prose-pre:rounded-md prose-pre:overflow-x-auto prose-pre:text-[0.875em] prose-pre:my-3
        prose-a:text-[hsl(var(--info))] prose-a:no-underline hover:prose-a:underline
        prose-strong:text-foreground prose-strong:font-semibold
        prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5
        prose-blockquote:border-[hsl(var(--primary)/0.4)] prose-blockquote:text-[hsl(var(--muted-foreground))]
        prose-table:block prose-table:max-w-full prose-table:overflow-x-auto prose-table:text-sm prose-th:border-[hsl(var(--overlay)/0.1)] prose-td:border-[hsl(var(--overlay)/0.1)]
        prose-img:max-w-full
        ${className ?? ""}`}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }], rehypeKatex]}
        components={{
          a: ({ href, children }) => <a href={/^https?:\/\//.test(href || "") ? href : undefined} target="_blank" rel="noopener noreferrer">{children}</a>,
          img: ({ src, alt }) => <MarkdownImage source={src} alt={alt} />,
        }}
      >
        {processed}
      </ReactMarkdown>
    </div>
  );
}

function MarkdownImage({ source, alt }: { source?: string | Blob; alt?: string }) {
  const { t } = useLanguage();
  const mappedSource = useMemo(() => mapMarkdownImageSource(source), [source]);
  const [failed, setFailed] = useState(false);

  useEffect(() => setFailed(false), [mappedSource]);

  if (!mappedSource || failed) {
    return (
      <span
        role="img"
        aria-label={alt || t("image.unavailable")}
        className="my-3 flex max-w-sm items-center gap-2 rounded-lg border border-dashed border-[hsl(var(--overlay)/0.16)] bg-[hsl(var(--surface-2))] px-3 py-2 text-xs text-[hsl(var(--muted-foreground))]"
      >
        <ImageOff className="h-4 w-4 shrink-0" />
        <span className="truncate">{alt || t("image.unavailable")}</span>
      </span>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={mappedSource}
      alt={alt || ""}
      loading="lazy"
      onError={() => setFailed(true)}
      className="my-3 max-h-[32rem] w-auto max-w-full rounded-lg border border-[hsl(var(--overlay)/0.1)] bg-[hsl(var(--surface-2))] object-contain shadow-sm"
    />
  );
}

export const Markdown = memo(MarkdownImpl);
