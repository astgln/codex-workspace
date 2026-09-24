/**
 * 前后端共享的 API 类型定义。
 *
 * 这些类型贯穿前后端：
 * - 前端 hooks 通过 fetch 调用路由，请求体/响应体使用这些类型。
 * - 后端 Route Handlers 解析请求、构造响应时复用同类型。
 * - SSE 事件流（实时 exec 与回放）共用 SseEvent 联合类型。
 */

// ---------------------------------------------------------------------------
// 请求类型
// ---------------------------------------------------------------------------

/** sandbox 模式枚举（对应 codex --sandbox） */
export type SandboxMode = "read-only" | "workspace-write" | "danger-full-access";

/** 审批策略枚举（通过 -c approval_policy=<value> 传递） */
export type ApprovalPolicy = "never" | "on-failure" | "on-request" | "untrusted";

/** POST /api/exec 请求体 */
export interface ExecRequest {
  /** 用户输入的 prompt */
  prompt: string;
  /** 工作目录（cwd），传给 codex -C */
  cwd: string;
  /** 模型名（如 gpt-5-codex、gpt-5、gpt-5-mini），可选，缺省用 codex 默认 */
  model?: string;
  /** 推理努力级别（minimal/low/medium/high/xhigh），可选 */
  effort?: string;
  /** 协作模式；plan 模式允许 Codex 在 turn 中发起结构化提问。 */
  collaborationMode?: "default" | "plan";
  /** sandbox 模式 */
  sandbox: SandboxMode;
  /** 审批策略 */
  approvalPolicy: ApprovalPolicy;
  /** 续接的会话 ID（UUID）。提供时走 codex exec resume 分支 */
  resumeSessionId?: string;
  /** 跳过 git 仓库检查（非 git 目录时必需） */
  skipGitRepoCheck?: boolean;
  /** 不持久化 rollout（--ephemeral） */
  ephemeral?: boolean;
}

// ---------------------------------------------------------------------------
// codex exec --json 事件流类型（实时）
// ---------------------------------------------------------------------------

/** token 用量（turn.completed.usage） */
export interface Usage {
  input_tokens: number;
  cached_input_tokens: number;
  cache_write_input_tokens: number;
  output_tokens: number;
  reasoning_output_tokens: number;
}

/** codex 速率限制信息（来自 token_count 事件的 rate_limits 字段） */
export interface RateLimits {
  /** 限制 ID（如 "codex"） */
  limitId?: string;
  /** 主限制：使用百分比与重置时间 */
  primary?: {
    usedPercent: number;
    windowMinutes?: number;
    resetsAt?: number;
  };
  /** 次级限制（可选） */
  secondary?: {
    usedPercent: number;
    windowMinutes?: number;
    resetsAt?: number;
  } | null;
  /** 积分信息 */
  credits?: {
    hasCredits: boolean;
    unlimited: boolean;
    balance?: string;
  };
  /** 计划类型（如 "plus" / "pro" / "free"） */
  planType?: string;
  /** 是否已达到速率限制 */
  rateLimitReachedType?: string | null;
}

/** rollout token_count 事件中的权威用量快照。 */
export interface UsageSnapshot {
  /** 会话截至当前的累计用量。 */
  totalUsage?: Usage;
  /** 最近一次模型调用的用量。input_tokens 即当前上下文占用。 */
  lastUsage?: Usage;
  /** 当前上下文占用；不再额外叠加 cached_input_tokens。 */
  contextTokens?: number;
  /** Codex 实际报告的模型上下文窗口。 */
  contextWindow?: number;
  rateLimits?: RateLimits;
  /** 对应 rollout 行时间。 */
  updatedAt?: string;
}

/** GET /api/sessions/[id]/usage 响应。 */
export interface UsageSnapshotResponse {
  sessionId: string;
  snapshot: UsageSnapshot;
}

/** agent_message item */
export interface AgentMessageItem {
  id: string;
  type: "agent_message";
  text: string;
}

/** reasoning 项中 summary 数组的元素类型
 *
 * codex rollout 中 reasoning.summary 的实际结构是对象数组：
 * [{ "type": "summary_text", "text": "..." }, ...]
 * 而非字符串数组。CLI 显示的明文思考过程即来自此处。
 */
export interface ReasoningSummaryItem {
  type: "summary_text";
  text: string;
}

/** reasoning item
 *
 * codex rollout 中 reasoning 项的实际结构：
 * - summary: 对象数组（ReasoningSummaryItem[]），每项含 {type:"summary_text", text:"..."}
 *   非空时即推理摘要明文，CLI 显示的思考过程就是这里来的
 * - encrypted_content: 加密的推理内容（无法本地解密显示）
 * - text: 通常不存在；mapResponseItem 会将 summary 数组拼接后写入 text
 * - content: 通常为 null
 */
export interface ReasoningItem {
  id: string;
  type: "reasoning";
  /** 推理文本（由 summary 数组拼接而来，可能为空字符串） */
  text?: string;
  /** 推理摘要数组（codex 原始字段，每项为 {type:"summary_text", text:"..."}） */
  summary?: ReasoningSummaryItem[];
  /** 加密的推理内容（无法本地解密） */
  encrypted_content?: string;
  /** 原始 content 字段（通常为 null） */
  content?: unknown;
}

/** 命令执行 item
 *
 * codex exec --json 实际输出结构：
 * - command: 完整命令行字符串（如 '"C:\...\pwsh.exe" -Command ...'），非数组
 * - aggregated_output: 合并的 stdout+stderr（含 ANSI 颜色码）
 * - exit_code: 退出码（null 表示仍在执行）
 * - status: "in_progress" | "completed"
 * 兼容旧字段：stdout / stderr / cwd / metadata
 */
export interface CommandExecutionItem {
  id: string;
  type: "command_execution";
  /** 完整命令行字符串（codex 实际输出为 string，非数组） */
  command: string;
  /** 合并输出（stdout+stderr，可能含 ANSI 码） */
  aggregated_output?: string;
  /** 工作目录 */
  cwd?: string;
  /** 退出码（null 表示仍在执行） */
  exit_code?: number | null;
  /** 标准输出（兼容旧格式，优先使用 aggregated_output） */
  stdout?: string;
  /** 标准错误（兼容旧格式） */
  stderr?: string;
  /** 执行状态 */
  status?: "in_progress" | "completed";
  /** 是否被用户拒绝 */
  metadata?: { denial_reason?: string };
}

/** 文件改动 item（apply_patch） */
export interface FileChangeItem {
  id: string;
  type: "file_change";
  /** 改动类型：create / edit / delete / rename */
  change: "create" | "edit" | "delete" | "rename";
  /** 目标文件路径 */
  path: string;
  /** unified diff patch 内容 */
  patch?: string;
  /** 旧路径（仅 rename） */
  oldPath?: string;
  metadata?: { rewrite?: boolean };
}

/** MCP 工具调用 item */
export interface McpToolCallItem {
  id: string;
  type: "mcp_tool_call";
  /** MCP 服务器名 */
  server: string;
  /** 工具名 */
  tool: string;
  /** 调用参数（JSON 字符串） */
  arguments?: string;
  /** 返回结果（JSON 字符串） */
  output?: string;
  /** 错误信息 */
  error?: string;
}

/** web 搜索 item */
export interface WebSearchItem {
  id: string;
  type: "web_search";
  query?: string;
  results?: Array<{ title: string; url: string; snippet?: string }>;
  summary?: string;
}

/** 计划更新 item */
export interface PlanUpdateItem {
  id: string;
  type: "plan_update";
  plan?: Array<{ step: string; status: string }>;
  status?: string;
}

/** 用户消息 item（回放时从 rollout 映射） */
export interface UserMessageItem {
  id: string;
  type: "user_message";
  text: string;
  /** Browser-comment screenshots or other images attached to the user turn. */
  images?: string[];
  /** Compact metadata for files explicitly attached to the user turn. */
  attachments?: Array<{ name: string; path: string }>;
}

export interface UserInputOption {
  label: string;
  description: string;
}

export interface UserInputQuestion {
  id: string;
  header: string;
  question: string;
  isOther: boolean;
  isSecret: boolean;
  options: UserInputOption[] | null;
}

/** Codex 在当前 turn 中暂停并等待用户回答的结构化问题。 */
export interface UserInputRequestItem {
  id: string;
  type: "user_input_request";
  interactionId: string;
  questions: UserInputQuestion[];
  autoResolutionMs: number | null;
}

/** POST /api/exec/respond 请求体。 */
export interface UserInputResponseRequest {
  interactionId: string;
  answers: Record<string, string[] | string>;
}

/** error item */
export interface ErrorItem {
  id: string;
  type: "error";
  message: string;
  /**
   * 严重级别：
   * - "error"：真正的错误（如 spawn 失败、子进程非 0 退出）
   * - "warning"：codex CLI 的非致命警告（如 skills context budget 截断提示）
   *
   * 警告不应将 session 状态置为 failed，仅以黄色卡片形式在时间线提示。
   */
  severity?: "error" | "warning";
}

/** 所有 item 类型的联合 */
export type ResponseItem =
  | AgentMessageItem
  | ReasoningItem
  | CommandExecutionItem
  | FileChangeItem
  | McpToolCallItem
  | WebSearchItem
  | PlanUpdateItem
  | UserMessageItem
  | UserInputRequestItem
  | ErrorItem;

/** item.type 字面量联合，用于运行时分发 */
export type ItemType = ResponseItem["type"];

// ---------------------------------------------------------------------------
// codex exec --json 顶层事件类型
// ---------------------------------------------------------------------------

export interface ThreadStartedEvent {
  type: "thread.started";
  thread_id: string;
}

export interface TurnStartedEvent {
  type: "turn.started";
  /** turn 开始时间（Unix 秒，回放来自 task_started.started_at；实时用 Date.now()） */
  startedAt?: number;
}

export interface ItemCompletedEvent {
  type: "item.completed";
  item: ResponseItem;
  /** item 时间戳（ISO 字符串） */
  timestamp?: string;
}

export interface TurnCompletedEvent {
  type: "turn.completed";
  usage: Usage;
  /** turn 开始时间（Unix 秒） */
  startedAt?: number;
  /** turn 完成时间（Unix 秒，回放来自 task_complete.completed_at） */
  completedAt?: number;
  /** turn 持续时长（毫秒，回放来自 task_complete.duration_ms） */
  durationMs?: number;
}

export interface TurnFailedEvent {
  type: "turn.failed";
  /** 错误信息 */
  error?: string;
  message?: string;
}

export interface ErrorEvent {
  type: "error";
  message: string;
  /** 附加 stderr（服务端封装） */
  stderr?: string;
  /** 严重级别：warning 不将 session 状态置为 failed */
  severity?: "error" | "warning";
}

/** codex exec --json 原始事件联合 */
export type CodexEvent =
  | ThreadStartedEvent
  | TurnStartedEvent
  | ItemCompletedEvent
  | TurnCompletedEvent
  | TurnFailedEvent
  | ErrorEvent;

// ---------------------------------------------------------------------------
// 会话元数据与列表
// ---------------------------------------------------------------------------

/** rollout 首行 session_meta 的 payload */
export interface SessionMeta {
  session_id: string;
  id: string;
  timestamp: string;
  cwd: string;
  originator?: string;
  cli_version?: string;
  /**
   * 会话来源。
   * - 字符串："exec" / "cli" / "vscode" 等（正常用户会话）
   * - 对象：{"subagent":{"other":"guardian"}} 等（子代理会话，应从列表过滤）
   */
  source?: string | Record<string, unknown>;
  thread_source?: string;
  model_provider?: string;
  instructions?: string;
  /** git 信息（可选） */
  git_branch?: string;
  git_sha?: string;
  git_origin_url?: string;
}

/** 会话列表项（GET /api/sessions 返回） */
export interface ThreadItem {
  /** 会话/线程 ID（UUID） */
  id: string;
  /** 首条用户消息预览 */
  preview: string;
  /** 工作目录 */
  cwd: string;
  /** 创建时间（ISO 字符串） */
  createdAt: string;
  /** 最后修改时间（ISO 字符串） */
  updatedAt: string;
  /** 来源（exec / chat 等） */
  source?: string;
  /** CLI 版本 */
  cliVersion?: string;
  /** 模型提供商 */
  modelProvider?: string;
  /** git 分支 */
  gitBranch?: string;
  /** rollout 文件绝对路径 */
  path: string;
  /** 是否为 zstd 压缩 */
  compressed: boolean;
}

// ---------------------------------------------------------------------------
// 统一 SSE 事件类型（实时 exec + 回放共用）
// ---------------------------------------------------------------------------

/**
 * 回放时注入的会话元数据事件。
 * 实时 exec 流不产生该事件（用 thread.started 携带 thread_id）。
 */
export interface SessionMetaSseEvent {
  type: "session.meta";
  meta: SessionMeta;
}

/** 速率限制更新事件（来自 token_count 事件的 rate_limits 字段） */
export interface RateLimitsUpdatedSseEvent {
  type: "rate_limits.updated";
  rateLimits: RateLimits;
}

/** token 用量、上下文窗口与额度限制的权威快照。 */
export interface UsageUpdatedSseEvent {
  type: "usage.updated";
  snapshot: UsageSnapshot;
}

/** 统一 SSE 事件联合：前端 reducer 只处理这些事件 */
export type SseEvent =
  | CodexEvent
  | SessionMetaSseEvent
  | RateLimitsUpdatedSseEvent
  | UsageUpdatedSseEvent;

// ---------------------------------------------------------------------------
// 配置
// ---------------------------------------------------------------------------

export interface ConfigResponse {
  models: ModelOption[];
  /** 全局可选的 effort 级别（minimal/low/medium/high/xhigh/max/ultra） */
  efforts: EffortOption[];
  sandboxes: SandboxMode[];
  approvals: ApprovalPolicy[];
  defaults: {
    model?: string;
    /** 默认 effort（来自 codex config 或模型默认） */
    effort?: string;
    sandbox: SandboxMode;
    approvalPolicy: ApprovalPolicy;
  };
}

export interface ModelOption {
  value: string;
  label: string;
  description?: string;
  /** 上下文窗口大小（tokens） */
  contextWindow?: number;
  /** 该模型默认的 reasoning effort */
  defaultEffort?: string;
  /** 该模型支持的 effort 列表 */
  supportedEfforts?: string[];
}

export interface EffortOption {
  value: string;
  label: string;
  description?: string;
}

// ---------------------------------------------------------------------------
// 文件系统浏览
// ---------------------------------------------------------------------------

export interface FsEntry {
  name: string;
  isDir: boolean;
}

export interface FsListResponse {
  path: string;
  parent: string | null;
  entries: FsEntry[];
}

// ---------------------------------------------------------------------------
// Skills（/skills @ 补全）
// ---------------------------------------------------------------------------

/**
 * Skill 来源类型：
 * - "user"：用户安装的 skill（~/.codex/skills/<name>/）
 * - "system"：系统内置 skill（~/.codex/skills/.system/<name>/）
 * - "plugin"：插件提供的 skill（~/.codex/plugins/cache/.../skills/<name>/）
 */
export type SkillSource = "user" | "system" | "plugin";

/** 单个 skill 元数据（GET /api/skills 返回） */
export interface SkillInfo {
  /** skill 名称（来自 SKILL.md frontmatter 的 name 字段） */
  name: string;
  /** 简短描述（来自 frontmatter description，可能为空） */
  description: string;
  /** 来源类型 */
  source: SkillSource;
  /** 插件名（仅 source === "plugin"） */
  plugin?: string;
  /** 插件市场名（仅 source === "plugin"） */
  marketplace?: string;
  /** skill 目录名（文件系统名，用于显示标签） */
  dirName: string;
}

/** GET /api/skills 响应 */
export interface SkillsResponse {
  skills: SkillInfo[];
}
