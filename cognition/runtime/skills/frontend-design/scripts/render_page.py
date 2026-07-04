"""前端页面落盘脚本：接收完整 HTML 写为 site.html 产物（补最小骨架/校验非空）。"""

import json
import os
import sys


def main() -> None:
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    title = str(args.get("title") or "页面")
    html = str(args.get("html") or "")
    if not html.strip():
        print("渲染失败: html 不能为空（需传完整 HTML 文档或片段）")
        sys.exit(1)
    # 片段则补最小骨架（保证 iframe 可独立渲染）。
    if "<html" not in html.lower():
        html = (
            "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>{title}</title>"
            "</head><body>" + html + "</body></html>"
        )
    out_dir = os.environ.get("SKILL_OUTPUT_DIR", ".")
    path = os.path.join(out_dir, "site.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"已生成 site.html（{os.path.getsize(path)} 字节，标题：{title}）")


if __name__ == "__main__":
    main()
