# GitHub 抓取 URL 手册（L3 参考）

无 token 的公开 API 速率约 60 次/小时/IP——一次调研控制在 8-12 次抓取内。

## 端点速查
| 目的 | URL 模式 |
|---|---|
| 仓库元数据 | `https://api.github.com/repos/{o}/{r}` |
| README 原文 | `https://raw.githubusercontent.com/{o}/{r}/HEAD/README.md`（大小写变体：readme.md、README.rst） |
| 目录列表 | `https://api.github.com/repos/{o}/{r}/contents/{path}`（path 空=根） |
| 单文件原文 | `https://raw.githubusercontent.com/{o}/{r}/HEAD/{path}` |
| 最近提交 | `https://api.github.com/repos/{o}/{r}/commits?per_page=5` |
| 开放 issues | `https://api.github.com/repos/{o}/{r}/issues?state=open&per_page=5` |
| Releases | `https://api.github.com/repos/{o}/{r}/releases?per_page=3` |
| 语言构成 | `https://api.github.com/repos/{o}/{r}/languages` |

## 技术栈判定文件优先级
`package.json`（Node）> `pyproject.toml`/`requirements.txt`（Python）> `go.mod`（Go）
> `Cargo.toml`（Rust）> `pom.xml`/`build.gradle`（JVM）。

## 常见失败与对策
- 404 on README.md → 试 readme.md / README.rst / docs/README.md。
- API 403（限流）→ 改抓 `https://github.com/{o}/{r}` 网页版（web_fetch 会抽正文）。
- 巨型文件被截断（20k 字符）→ 只结论其可见部分，注明"截断"。
