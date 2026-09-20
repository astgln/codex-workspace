/**
 * 代码语法高亮工具：基于 highlight.js，支持按行分割。
 *
 * 核心功能：
 * - getLanguageFromPath：根据文件扩展名推断 highlight.js 语言
 * - highlightCode：对整段代码做语法高亮，返回 HTML 字符串
 * - highlightAndSplitLines：对整段代码做语法高亮，按行分割为 HTML 数组，
 *   保留跨行 span 标签的连续性（多行字符串/注释可正确着色）
 *
 * 用于 DiffViewerDialog：对 diff 的 new/old 版本分别高亮，再映射回各行。
 */

import hljs from "highlight.js";

/** 文件扩展名 → highlight.js 语言名映射 */
const EXT_LANG_MAP: Record<string, string> = {
  py: "python",
  ts: "typescript",
  tsx: "tsx",
  js: "javascript",
  jsx: "jsx",
  mjs: "javascript",
  cjs: "javascript",
  json: "json",
  json5: "json",
  md: "markdown",
  markdown: "markdown",
  sh: "bash",
  bash: "bash",
  zsh: "bash",
  fish: "bash",
  yml: "yaml",
  yaml: "yaml",
  toml: "ini",
  ini: "ini",
  cfg: "ini",
  css: "css",
  scss: "scss",
  less: "less",
  html: "xml",
  htm: "xml",
  xml: "xml",
  svg: "xml",
  sql: "sql",
  go: "go",
  rs: "rust",
  rb: "ruby",
  java: "java",
  kt: "kotlin",
  swift: "swift",
  c: "c",
  h: "c",
  cpp: "cpp",
  cc: "cpp",
  cxx: "cpp",
  hpp: "cpp",
  cs: "csharp",
  php: "php",
  r: "r",
  lua: "lua",
  pl: "perl",
  dockerfile: "dockerfile",
  makefile: "makefile",
  vim: "vim",
  diff: "diff",
  patch: "diff",
};

/** 根据文件路径推断 highlight.js 语言名 */
export function getLanguageFromPath(filePath: string): string | undefined {
  // 先取文件名（处理 Dockerfile / Makefile 等无扩展名情况）
  const fileName = filePath.split(/[/\\]/).pop() || "";
  const lowerName = fileName.toLowerCase();

  // 特殊文件名
  if (lowerName === "dockerfile") return "dockerfile";
  if (lowerName === "makefile" || lowerName === "gnumakefile") return "makefile";

  // 扩展名
  const ext = fileName.split(".").pop()?.toLowerCase();
  if (!ext) return undefined;
  return EXT_LANG_MAP[ext];
}

/** 对整段代码做语法高亮，返回 HTML 字串 */
export function highlightCode(code: string, language?: string): string {
  if (!language || !hljs.getLanguage(language)) {
    // 无匹配语言：转义 HTML 后返回
    return escapeHtml(code);
  }
  try {
    return hljs.highlight(code, { language, ignoreIllegals: true }).value;
  } catch {
    return escapeHtml(code);
  }
}

/**
 * 对整段代码做语法高亮，按行分割为 HTML 数组。
 *
 * 关键：跨行的 span 标签需要在行边界处关闭并重新开启，
 * 使每行成为独立的 HTML 片段，同时保持语法着色连续性。
 *
 * 算法：
 * 1. 用 highlightCode 高亮整段代码
 * 2. 逐字符扫描，跟踪未关闭的 span 标签栈
 * 3. 遇到 \n：关闭所有 open span，保存当前行，下一行重新开启 open span
 * 4. 遇到 <span ...>：入栈并追加到当前行
 * 5. 遇到 </span>：出栈并追加到当前行
 *
 * @returns 按 \n 分割的高亮 HTML 数组（与输入 code 的行数一致）
 */
export function highlightAndSplitLines(code: string, language?: string): string[] {
  const html = highlightCode(code, language);
  const lines: string[] = [];
  let currentLine = "";
  const openSpans: string[] = []; // 存储未关闭的 <span ...> 开标签

  let i = 0;
  while (i < html.length) {
    // 换行：关闭 open span，保存行，下一行重开
    if (html[i] === "\n") {
      currentLine += openSpans.map(() => "</span>").join("");
      lines.push(currentLine);
      currentLine = openSpans.join("");
      i++;
      continue;
    }

    // <span ...> 开标签
    if (html.startsWith("<span", i)) {
      const end = html.indexOf(">", i);
      if (end === -1) {
        currentLine += html[i];
        i++;
        continue;
      }
      const spanTag = html.substring(i, end + 1);
      openSpans.push(spanTag);
      currentLine += spanTag;
      i = end + 1;
      continue;
    }

    // </span> 闭标签
    if (html.startsWith("</span>", i)) {
      currentLine += "</span>";
      openSpans.pop();
      i += 7;
      continue;
    }

    currentLine += html[i];
    i++;
  }

  // 最后一行
  currentLine += openSpans.map(() => "</span>").join("");
  lines.push(currentLine);

  return lines;
}

/** HTML 转义（无语言匹配时使用） */
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
