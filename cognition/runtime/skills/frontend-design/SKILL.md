---
name: frontend-design
description: 生成单文件自包含的现代网页（落地页/看板/表单/原型），产出 site.html 可在产物区实时预览。
---

# 前端页面设计

把需求变成**单文件自包含 HTML**（内联 CSS/JS，零外链——产物区 iframe 沙箱可直接渲染）。

## 用法

先在回复里想清结构，再把**完整 HTML** 交给渲染脚本落盘：

```
script_runner(
  skill="frontend-design",
  script="render_page.py",
  script_args={"title": "产品落地页", "html": "<!DOCTYPE html><html>…完整文档…</html>"}
)
```
产出 `site.html`（产物区自动预览，allow-scripts 下交互可用）。

## 设计准则（生成 HTML 时遵守）

- **自包含**：所有 CSS 写 `<style>`、JS 写 `<script>`；不引外部字体/CDN（沙箱无网络凭据）。
- **现代观感**：系统字体栈；8px 间距体系；圆角 12-16px；一个主色 + 中性灰阶；
  暗色页配 `color-scheme: dark`。
- **响应式**：max-width 容器 + flex/grid；图片 `max-width:100%`。
- **可交互**：按钮 hover/表单校验/选项卡切换用原生 JS 实现（不引框架）。
- 中文排版：`font-family: system-ui, "PingFang SC", "Microsoft YaHei", sans-serif`；
  行高 1.6-1.8。

需要配图时先用 image_generate 生成，再以产物 URL 说明（沙箱内无法内联外部图，
可用纯 CSS 装饰/emoji/inline SVG 替代）。
