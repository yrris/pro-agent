// 前端常量。端点全用相对路径（Vite proxy 转发）。

// 三档模式（M9）：value 是后端 agent_type，**不可改**（sessions 持久化按值恢复）；
// label 面向用户（快速=ReAct / 深度思考=Plan-Execute / 深度研究=研究变体图）。
export const AGENT_TYPES = [
  { value: "react", label: "快速" },
  { value: "plan_solve", label: "深度思考" },
  { value: "deep_research", label: "深度研究" },
] as const;

// 输出格式选择器（M9）：value 经 startRun.outputFormat → 认知面 metadata；
// 仅深度思考/深度研究可选（快速模式 disabled，对齐原项目）。空串=自由格式。
export const OUTPUT_FORMATS = [
  { value: "", label: "自由格式" },
  { value: "docs", label: "文档" },
  { value: "table", label: "表格" },
  { value: "ppt", label: "PPT" },
  { value: "html", label: "网页" },
] as const;

export const HEALTH_POLL_MS = 30_000;

export const SAMPLE_QUESTIONS = [
  "帮我算一下 2*(3+4) 等于多少",
  "写一份关于本周进展的简短报告",
  "什么是混合检索和 RRF？（需开启知识库）",
];
