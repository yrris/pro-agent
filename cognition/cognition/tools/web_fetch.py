"""web_fetch 工具（M12）：抓取网页并抽取可读文本，供深度研究/资料核对。

安全边界（SSRF）：URL 解析后逐个校验解析出的 IP——私网/环回/链路本地/元数据地址
一律拒绝（工具参数是 LLM 可写面，提示注入可让模型去打内网；封禁在服务端做）。
产出限幅：正文截断 MAX_TEXT_CHARS；仅 http/https；重定向后同样校验。
"""

from __future__ import annotations

import ipaddress
import re
import socket
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urlparse

import httpx
from langchain_core.tools import BaseTool, StructuredTool

MAX_TEXT_CHARS = 20_000
_TIMEOUT_S = 20.0
_MAX_BYTES = 2 * 1024 * 1024  # 2MB 响应上限

_SKIP_TAGS = {"script", "style", "noscript", "svg", "head", "iframe", "template"}
_BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
               "section", "article", "header", "footer", "pre", "blockquote"}


class _TextExtractor(HTMLParser):
    """标准库 html.parser 的轻量正文抽取（免第三方依赖；不求完美，够研究场景）。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag):  # noqa: ANN001
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):  # noqa: ANN001
        if self._in_title and not self.title:
            self.title = data.strip()
        if self._skip_depth == 0 and data.strip():
            self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", raw)).strip()


def html_to_text(html: str) -> tuple[str, str]:
    """HTML → (title, 可读文本)（纯函数，可测）。"""
    p = _TextExtractor()
    try:
        p.feed(html)
    except Exception:  # noqa: BLE001 — 残破 HTML 尽力而为
        pass
    return p.title, p.text()


def is_private_host(host: str) -> bool:
    """host（域名或 IP 字面量）是否解析到私网/环回/链路本地/元数据地址（纯逻辑+DNS）。

    任一解析结果命中即拒绝——DNS 多记录里藏一个内网地址是经典 SSRF 绕过。
    """
    if not host:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True  # 解析失败按拒绝（fail-closed）
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str.split("%")[0])
        except ValueError:
            return True
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return True
    return False


def validate_fetch_url(url: str) -> Optional[str]:
    """URL 是否允许抓取；返回 None=允许，否则返回拒绝原因（纯函数+DNS）。"""
    try:
        parsed = urlparse(url)
    except ValueError:
        return "URL 无法解析"
    if parsed.scheme not in ("http", "https"):
        return "仅支持 http/https"
    if not parsed.hostname:
        return "URL 缺少主机名"
    if is_private_host(parsed.hostname):
        return "目标地址不可访问（内网/环回/保留地址被禁止）"
    return None


def build_web_fetch_tool() -> BaseTool:
    """构造 web_fetch 工具。"""

    async def web_fetch(url: str) -> str:
        """抓取一个公开网页并返回其标题与正文文本（截断至 2 万字符）。

        用于查资料/读文档/GitHub 页面等；不能访问内网地址；只支持 http/https。
        """
        reason = validate_fetch_url(url)
        if reason:
            return f"抓取被拒绝：{reason}（{url}）"
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT_S, follow_redirects=True,
                headers={"User-Agent": "pro-agent/1.0 (+research)"},
            ) as client:
                async with client.stream("GET", url) as resp:
                    # 重定向落点再校验（首跳校验可被 302 绕过）。
                    final_reason = validate_fetch_url(str(resp.url))
                    if final_reason:
                        return f"抓取被拒绝：重定向目标 {final_reason}"
                    if resp.status_code >= 400:
                        return f"抓取失败：HTTP {resp.status_code}（{url}）"
                    body = b""
                    async for chunk in resp.aiter_bytes():
                        body += chunk
                        if len(body) > _MAX_BYTES:
                            break
        except httpx.HTTPError as exc:
            return f"抓取失败：{exc}"

        ctype = resp.headers.get("content-type", "")
        text = body.decode(resp.charset_encoding or "utf-8", errors="replace")
        if "html" in ctype or text.lstrip()[:1] == "<":
            title, extracted = html_to_text(text)
            head = f"【{title}】\n" if title else ""
            out = head + extracted
        else:
            out = text  # json/纯文本等原样
        if len(out) > MAX_TEXT_CHARS:
            out = out[:MAX_TEXT_CHARS] + "\n…（超长截断）"
        return out or "（页面无可读文本）"

    tool = StructuredTool.from_function(
        coroutine=web_fetch,
        name="web_fetch",
        description="抓取公开网页并返回标题与正文文本（查资料/读在线文档/GitHub 页面）。不能访问内网。",
    )
    tool.metadata = {"provider": "local"}
    return tool
