/** 后端 REST 客户端（Tauri 桌面端默认本地 8001，VITE_BACKEND_URL 可覆盖） */
export const BACKEND_URL = import.meta.env.VITE_BACKEND_URL ?? "http://localhost:8001";

export type ProjectVersion = { iteration: number; html: string; created_at: number };

export type Project = {
  id: string;
  topic: string;
  created_at: number;
  status: string;
  steps: number;
  cost: number;
  iterations: number;
  versions?: ProjectVersion[];
  trace_path?: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!r.ok) throw new Error(`请求失败 ${r.status}: ${path}`);
  return (await r.json()) as T;
}

/** 生成历史列表（新的在前） */
export function fetchHistory(): Promise<{ projects: Project[] }> {
  return request("/api/history");
}

/** 单个生成记录（含 versions，可回看） */
export function fetchProject(id: string): Promise<Project> {
  return request(`/api/history/${id}`);
}

/** 重命名历史作品 */
export function renameProject(id: string, topic: string): Promise<{ ok: boolean }> {
  return request(`/api/history/${id}`, { method: "PATCH", body: JSON.stringify({ topic }) });
}

/** 置顶历史作品 */
export function pinProject(id: string): Promise<{ ok: boolean }> {
  return request(`/api/history/${id}/pin`, { method: "POST" });
}

/** 删除历史作品 */
export function deleteProject(id: string): Promise<{ ok: boolean }> {
  return request(`/api/history/${id}`, { method: "DELETE" });
}

export type Skill = {
  id: string;
  name: string;
  type: string;
  icon: string;
  desc: string;
  prompt: string;
  /** 内置 skill（随项目播种，不可删除） */
  builtin: boolean;
};

/** skill 列表（风格/工具） */
export function fetchSkills(skillType?: string): Promise<{ skills: Skill[] }> {
  const q = skillType ? `?skill_type=${encodeURIComponent(skillType)}` : "";
  return request(`/api/skills${q}`);
}

/** 安装 skill（"我的 Skill"下载用） */
export function installSkill(id: string, markdown: string): Promise<Skill> {
  return request("/api/skills/install", {
    method: "POST",
    body: JSON.stringify({ id, markdown }),
  });
}

/** 删除 skill（内置不可删，后端拒绝） */
export function deleteSkill(id: string): Promise<{ ok: boolean }> {
  return request(`/api/skills/${id}`, { method: "DELETE" });
}

export type EventItem = { name: string; category: string };

/** 示例话题列表（空状态建议） */
export function fetchEvents(): Promise<{ events: EventItem[]; total: number }> {
  return request("/api/events");
}

/** 生成参数（前端设置 → 会话级覆盖后端 orchestrator 配置） */
export type GenParams = {
  agentSteps: number;      // Agent 决策循环步数
  llmSteps: number;        // LLM 步数：每类内部重试上限（渲染自检/换词/审查回退）
  budget: number;          // 单次生成成本上限（元）
  searchMax: number;       // 搜索轮数上限
  searchEnabled: boolean;  // 联网搜索开关
  skillId: string;         // 风格 skill（模板资产注入渲染；空=LLM 自由发挥）
};

/** 模型配置（设置页管理，Composer 选择） */
export type ModelItem = {
  id: string;
  name: string;      // 显示名称
  modelId: string;   // 模型 ID（如 deepseek-chat / gpt-4o）
  removable: boolean;
};

/* ── 对话消息类型（App / ToolCard / 会话存储共用） ── */

/** 工具标识（含 think——思考卡片；judge——质量审查） */
export type ToolId = "think" | "search" | "design" | "compose" | "render" | "verify" | "judge";
export type ToolStatus = "pending" | "running" | "done" | "error";

/** 一次工具调用（DSH 工具卡片语义） */
export type ToolCall = {
  id: string;
  tool: ToolId;
  title: string;
  status: ToolStatus;
  /** think 正文 / 执行时的思考（running 时流式展示） */
  thought?: string;
  /** 完成后的一句话结果（卡片收起时显示） */
  summary?: string;
  /** 展开区的附加信息（关键词/来源/自检结果） */
  detail?: string;
  /** 耗时（秒） */
  duration?: number;
  /** 花费（元） */
  cost?: number;
  error?: string;
};

export type Msg = {
  id: number;
  role: "user" | "assistant";
  text: string;
  html?: string;
  /** 工具调用序列（由后端决策日志实时填充） */
  calls?: ToolCall[];
  /** 本次生成累计花费（来自后端 budget） */
  cost?: number;
  source?: string;
};
