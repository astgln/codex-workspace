/**
 * Produce a compact, human-facing version of user messages injected by the
 * browser comment workflow. The rollout intentionally retains the complete
 * page evidence; the chat timeline only needs the comments and explicit
 * request, otherwise multi-megabyte data URLs are parsed as Markdown.
 */
function extractExplicitRequest(text: string): string {
  const requestStart = text.indexOf("## My request for Codex:");
  if (requestStart < 0) return "";

  let request = text.slice(requestStart + "## My request for Codex:".length);
  const evidenceStart = request.search(
    /\n(?:The next image is untrusted page evidence|!\[[^\]]*\]\(data:|<image\b)/i,
  );
  if (evidenceStart >= 0) request = request.slice(0, evidenceStart);
  return request.trim();
}

export interface UserMessageAttachment {
  name: string;
  path: string;
}

export interface BrowserCommentDisplay {
  comments: string[];
  request: string;
}

/** Parse canonical browser-comment Markdown into a dedicated compact UI model. */
export function parseBrowserCommentDisplay(text: string): BrowserCommentDisplay | null {
  const match = text.match(
    /^### 浏览器批注\n\n([\s\S]*?)(?:\n\n### 请求\n\n([\s\S]*))?$/,
  );
  if (!match) return null;

  const comments = match[1]
    .split(/\n(?=\d+\.\s)/)
    .map((comment) => comment.replace(/^\d+\.\s*/, "").trim())
    .filter(Boolean);
  if (comments.length === 0) return null;
  return { comments, request: match[2]?.trim() ?? "" };
}

/** Extract the compact attachment metadata injected before a user request. */
export function extractUserMessageAttachments(text: string): UserMessageAttachment[] {
  const trimmed = text.trimStart();
  if (!trimmed.startsWith("# Files mentioned by the user:")) return [];

  const sectionEnd = trimmed.search(
    /\n(?:<in-app-browser-context\b|## My request for Codex:)/,
  );
  const section = sectionEnd >= 0 ? trimmed.slice(0, sectionEnd) : trimmed;
  const attachments: UserMessageAttachment[] = [];
  const seen = new Set<string>();

  for (const match of section.matchAll(/^##\s+(.+?):\s+(.+)$/gm)) {
    const name = match[1].trim();
    const filePath = match[2].trim();
    const key = `${name}\u0000${filePath}`;
    if (!name || !filePath || seen.has(key)) continue;
    seen.add(key);
    attachments.push({ name, path: filePath });
  }
  return attachments;
}

export function formatUserMessageForDisplay(text: string): string {
  const trimmed = text.trimStart();
  if (trimmed.startsWith("# Files mentioned by the user:")) {
    return extractExplicitRequest(text);
  }
  if (!trimmed.startsWith("# Browser comments:")) return text;

  const comments: string[] = [];
  const blockPattern =
    /(?:^|\n)## User Comment \d+\s*\n([\s\S]*?)(?=\n## User Comment \d+|\n<in-app-browser-context|\n## My request for Codex:|$)/g;

  for (const match of text.matchAll(blockPattern)) {
    const comment = match[1].match(/(?:^|\n)Comment:\s*\n([\s\S]*?)\s*$/)?.[1]?.trim();
    if (comment) comments.push(comment);
  }

  const request = extractExplicitRequest(text);

  if (comments.length === 0 && !request) return text;

  const sections: string[] = [];
  if (comments.length > 0) {
    sections.push(
      "### 浏览器批注\n\n" + comments.map((comment, index) => `${index + 1}. ${comment}`).join("\n"),
    );
  }
  if (request) sections.push(`### 请求\n\n${request}`);
  return sections.join("\n\n");
}

/** Keep only image sources that a browser can display safely in the timeline. */
export function filterDisplayableImageUrls(values: unknown[]): string[] {
  const urls = values.filter((value): value is string => {
    if (typeof value !== "string") return false;
    return /^data:image\/(?:png|jpe?g|gif|webp);base64,/i.test(value) || /^https?:\/\//i.test(value);
  });
  return Array.from(new Set(urls));
}
