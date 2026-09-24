/**
 * Unified diff 解析。
 *
 * apply_patch 格式与标准 unified diff 略有不同，这里做兼容处理：
 * - apply_patch: *** /path → +++ /path，@@ ... @@，+/-/  行
 * - unified diff: --- /path，+++ /path，@@ ... @@，+/-/  行
 *
 * 解析为行数组，每行带类型（add/del/context/hunk）与原始行号。
 */

export interface DiffLine {
  type: "add" | "del" | "context" | "hunk" | "meta";
  content: string;
  oldLine?: number;
  newLine?: number;
}

export interface DiffFile {
  path: string;
  oldPath?: string;
  lines: DiffLine[];
  added: number;
  removed: number;
}

/** 解析 patch 字符串为 DiffFile */
export function parseDiff(patch: string, path: string): DiffFile {
  const lines = patch.split("\n");
  const result: DiffLine[] = [];
  let oldLine = 0;
  let newLine = 0;
  let added = 0;
  let removed = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // apply_patch 头部：*** /path 或 +++ /path
    if (line.startsWith("*** ") || line.startsWith("--- ")) {
      result.push({ type: "meta", content: line });
      continue;
    }

    // hunk 头：@@ -a,b +c,d @@
    const hunkMatch = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (hunkMatch) {
      oldLine = Number(hunkMatch[1]);
      newLine = Number(hunkMatch[2]);
      result.push({ type: "hunk", content: line });
      continue;
    }

    // apply patch 头部行（无前缀）
    if (line.startsWith("*** End Patch") || line.startsWith("*** Begin Patch")) {
      result.push({ type: "meta", content: line });
      continue;
    }

    // 增行
    if (line.startsWith("+") && !line.startsWith("+++")) {
      result.push({ type: "add", content: line.slice(1), newLine: newLine++ });
      added++;
      continue;
    }

    // 删行
    if (line.startsWith("-") && !line.startsWith("---")) {
      result.push({ type: "del", content: line.slice(1), oldLine: oldLine++ });
      removed++;
      continue;
    }

    // 上下文行（可能以空格开头，或是空行）
    const content = line.startsWith(" ") ? line.slice(1) : line;
    result.push({ type: "context", content, oldLine: oldLine++, newLine: newLine++ });
  }

  return { path, lines: result, added, removed };
}
