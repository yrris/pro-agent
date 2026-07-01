// 前端常量。端点全用相对路径（Vite proxy 转发）。

export const AGENT_TYPES = [
  { value: "react", label: "ReAct（单轮 think⇄act）" },
  { value: "plan_solve", label: "Plan-Execute（规划+并行子任务）" },
] as const;

export const HEALTH_POLL_MS = 30_000;

export const SAMPLE_QUESTIONS = [
  "帮我算一下 2*(3+4) 等于多少",
  "写一份关于本周进展的简短报告",
  "什么是混合检索和 RRF？（需开启知识库）",
];
