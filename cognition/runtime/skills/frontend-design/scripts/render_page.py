"""前端页面落盘脚本：接收完整 HTML 写为 site.html 产物（补最小骨架/校验非空）。

B.1：把 HTML 里对生成图的引用 src="generated/xxx.png" 替换成内联 data-URI——
沙箱 iframe 带 X-User-Id 拿不到 /artifacts，唯有 data-URI 才能在预览里真正显示那张生成图。
生成图由 image_generate 暂存、经 SKILL_GENERATED_DIR 只读挂进沙箱。
"""

import base64
import json
import mimetypes
import os
import re
import sys


def _inline_generated_images(html: str) -> tuple[str, int]:
    """把 src="generated/NAME"（或 './generated/NAME'）替换成 data:URI。返回 (html, 内联数)。"""
    gen_dir = os.environ.get("SKILL_GENERATED_DIR")
    if not gen_dir or not os.path.isdir(gen_dir):
        return html, 0
    count = 0

    def repl(m: "re.Match[str]") -> str:
        nonlocal count
        quote, name = m.group(1), m.group(2)
        path = os.path.join(gen_dir, os.path.basename(name))
        if not os.path.isfile(path):
            return m.group(0)  # 找不到就原样（模型可能引了不存在的名）
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return m.group(0)
        mime = mimetypes.guess_type(path)[0] or "image/png"
        b64 = base64.b64encode(data).decode("ascii")
        count += 1
        return f"src={quote}data:{mime};base64,{b64}{quote}"

    # 匹配 src="generated/NAME" / src='./generated/NAME'
    new_html = re.sub(r"""src=(["'])\.?/?generated/([^"']+)\1""", repl, html)
    return new_html, count


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
    html, inlined = _inline_generated_images(html)
    out_dir = os.environ.get("SKILL_OUTPUT_DIR", ".")
    path = os.path.join(out_dir, "site.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    extra = f"，内联生成图 {inlined} 张" if inlined else ""
    print(f"已生成 site.html（{os.path.getsize(path)} 字节，标题：{title}{extra}）")


if __name__ == "__main__":
    main()
