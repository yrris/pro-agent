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

// 首屏建议问题：每条映射一项真实能力（深度研究检索报告 / GitHub 调研 / 图表 / 生图 / 文档），
// 展示态（截图）与日常演示共用。e2e 不再依赖此列表（helpers.sendMessage 直接输入）。
export const SAMPLE_QUESTIONS = [
  "围绕「2026 年国产大模型 Agent 落地」做一份带引用来源的调研报告",
  "分析 GitHub 上 langchain-ai/langgraph 项目的架构，输出网页版报告",
  "搜索近五年中国新能源汽车渗透率数据，用图表对比展示",
  "生成一张水彩风格的江南水乡海报",
  "帮我规划一个成都三日游行程，输出成文档",
];
