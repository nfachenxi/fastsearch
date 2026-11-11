# FastSearch MCP

[![powered by Codex](docs/assets/powered-by-codex.svg)](https://developers.openai.com/codex/)
[![powered by Claude](https://img.shields.io/badge/powered_by-Claude-D97757?style=flat-square&logo=claude&logoColor=white)](https://claude.ai/)

让 AI 助手更方便地查文件、搜代码、读内容，重点照顾 Windows 上的使用体验。

你只需要像平时一样告诉 AI 要找什么。连接 FastSearch MCP 后，AI 就能使用这里的工具完成搜索，不必每次临时编写搜索命令。MCP 是 AI 助手连接外部工具的一种方式。

适用于支持 MCP 的客户端，例如 Claude Desktop、Claude Code、Codex、Cursor 和 Cline。

## 为什么使用 FastSearch

| **Agent 在 Windows 上的典型问题** | **本项目的处理** |
| --- | --- |
| 搜索大项目时，花很多时间翻依赖、缓存等无关目录 | 默认跳过常见的依赖和缓存目录，并遵守项目的忽略规则 |
| 一次返回成千上万行，AI 很难抓住重点 | 限制结果数量和内容长度，支持只看文件名或指定几行 |
| Windows 路径写法不统一，容易找错位置 | 识别常见路径写法，统一后再查找 |
| 老项目里的中文搜不到，读出来又是乱码 | 读取时自动识别常见编码，搜索时可以指定 GBK 等编码 |
| 搜索词带引号、括号或反斜杠，命令容易出错 | 直接把搜索条件交给工具，减少命令行转义造成的问题 |
| 搜索时弹出黑色窗口，或长时间没有响应 | Windows 下隐藏搜索进程窗口，超时后停止并提示 |
| 换台电脑还要单独找齐搜索工具 | 分享版附带所需的 Windows x64 程序，按说明安装即可 |
| 反复导出同一个 DLL，或者误读更新前的代码 | 按 DLL 内容和导出工具版本保存副本，相同版本复用，更新后重新生成 |

## 它能帮你做什么

你可以这样对 AI 说：

- “先看看这个项目的目录，告诉我代码主要放在哪里。”
- “帮我找到 PlayerController 这个脚本。”
- “查一下哪些文件用到了这个函数。”
- “只读这个文件的第 100 到 150 行。”
- “这个项目只有 DLL，帮我导出可以查看的 C# 代码，再找一下相关逻辑。”

FastSearch 默认遵守项目的 `.gitignore`，并跳过 `.git`、`node_modules`、`.venv` 等通常不需要搜索的目录。它会控制返回内容的长度，结果太多时提醒 AI 缩小范围，避免一次返回大量无关内容。

它还处理了 Windows 常见的路径写法、中文文件名和部分旧文件的中文编码问题。底层搜索使用 [fd](https://github.com/sharkdp/fd) 和 [ripgrep](https://github.com/BurntSushi/ripgrep)。

## 选择哪个版本

**日常使用，推荐下载分享版。** 从 [Releases](https://github.com/nfachenxi/fastsearch/releases) 下载 `Fastsearch-MCP-Share.zip`。它包含全部六个工具、所需的 Windows x64 程序、安装脚本和自检程序，不记录调用历史。

**需要改代码或查看使用情况，可以安装本仓库的开发版。** 开发版额外提供本机调用记录和离线报告。两个版本的搜索功能来自同一份源码。

## 安装

需要 Python 3.10 或更新版本，以及 [uv](https://docs.astral.sh/uv/)。Windows 上可以用下面的命令安装 uv：

```powershell
winget install astral-sh.uv
```

### 分享版

1. 从 [Releases](https://github.com/nfachenxi/fastsearch/releases) 下载 `Fastsearch-MCP-Share.zip`。
2. 解压到一个准备长期保留的位置。
3. 按包内 `README.md` 运行 `01-install.ps1`。
4. 用安装脚本输出的程序路径配置 AI 客户端。

也可以把包内的 `AI-INSTALL.md` 交给有终端权限的 AI 助手，让它按说明安装。

### 从源码安装

在 PowerShell 中执行：

```powershell
git clone https://github.com/nfachenxi/fastsearch.git C:\tools\fastsearch
cd C:\tools\fastsearch
uv run python scripts/bundle.py fetch
uv tool install --force .
fastsearch-mcp --doctor
```

其中 `fetch` 会下载搜索和 DLL 代码导出所需的程序，`--doctor` 用来检查 fd 和 ripgrep 是否可用。

## 连接 AI 客户端

下面的示例使用从源码安装后得到的 `fastsearch-mcp` 命令。**分享版请把命令替换为安装脚本输出的完整程序路径**，路径以 `.venv\Scripts\fastsearch-mcp.exe` 结尾。

### Claude Desktop

在 `%APPDATA%\Claude\claude_desktop_config.json` 中添加以下配置；已有其他工具时，把 `fastsearch` 合并进去：

```json
{
  "mcpServers": {
    "fastsearch": {
      "command": "fastsearch-mcp"
    }
  }
}
```

填写 Windows 完整路径时，JSON 中的反斜杠要写成 `\\`，例如 `C:\\tools\\Fastsearch-MCP-Share\\.venv\\Scripts\\fastsearch-mcp.exe`。

### Claude Code

```powershell
claude mcp add fastsearch -s user -- fastsearch-mcp
```

### Codex

在 `~/.codex/config.toml` 中添加：

```toml
[mcp_servers.fastsearch]
command = "fastsearch-mcp"
```

### 其他客户端

Cursor 的配置文件是 `~/.cursor/mcp.json`，格式与上面的 Claude Desktop 示例相同。Cline 等客户端可以在 MCP 设置中填写启动命令。

保存配置后，重新连接 MCP 或重启客户端。如果提示找不到 `fastsearch-mcp`，请改用程序的完整路径。

## 开始使用

连接成功后，直接告诉 AI 项目的完整路径和你要找的内容，例如：

> 请使用 FastSearch，查看 C:/projects/my-game 的目录，再找到负责玩家移动的脚本。

AI 可以根据问题选择下面的工具：

| 工具 | 用途 |
| --- | --- |
| `tree` | 查看目录结构 |
| `find_files` | 按文件名、类型、大小或修改时间找文件 |
| `count_matches` | 看一个词在哪些文件中出现、各出现多少次 |
| `search_text` | 搜索文件里的文字或代码 |
| `read_lines` | 读取文件的指定几行 |
| `decompile` | 将 .NET DLL 中的代码导出到本机，方便继续查找 |

已知文件和行号时，可以直接读取，不必先搜索一遍。查 DLL 时，同一份 DLL 和同一版本的导出工具只需导出一次；DLL 更新后会生成新的副本。

如果希望 AI 持续遵守搜索规则，可以把本仓库 [AGENTS.md](AGENTS.md) 中的规则加入项目的 `AGENTS.md`、`CLAUDE.md` 或客户端规则文件。这些规则用于指导 AI，不会拦截终端命令。

## 常见问题

**会修改我的文件吗？**

搜索和读取不会修改原文件。DLL 导出的代码保存在 `%LOCALAPPDATA%/fastsearch-mcp/decompile`，旧副本不会自动清理。

**为什么找不到文件或中文？**

文件可能被忽略或隐藏了，可以让 AI 调整搜索范围，必要时包含这些文件。老项目中的中文搜不到时，可以让 AI 尝试 `encoding="gbk"`。同一个目录混有多种编码时，可能需要分开搜索。

**结果不完整怎么办？**

结果太多或搜索超时时，工具会提示只返回了部分内容，可以缩小范围后重试。没有匹配结果本身不代表工具出错。搜索支持关键词和正则表达式；正则写错时，`search_text` 会尝试按普通文字重新搜索，并在开头说明。

**只能搜索当前项目吗？**

没有额外的工作区路径限制，可以访问哪些文件取决于运行程序的系统权限。

## 查看使用情况（仅开发版）

开发版默认在本机记录调用时间、文件路径、查询内容、耗时和错误信息，不保存返回的源码正文，也不会自动上传或删除记录。分享版不包含这项功能。

运行下面的命令，可以生成最近 30 天的离线报告：

```powershell
fastsearch-mcp report --days 30
```

用浏览器打开命令输出的 HTML 文件，就能查看调用次数、耗时趋势、较慢的操作和具体参数。需要重新运行命令才能更新报告。默认记录位置是 `%LOCALAPPDATA%/fastsearch-mcp/usage.sqlite3`。

如果不需要记录，可以在客户端的 MCP 环境变量设置中加入 `FASTSEARCH_TELEMETRY=0`，然后重新连接。记录写入失败不会中断搜索。

开发版还可以抽取部分历史请求，用 PowerShell 执行类似操作，供你参考：

```powershell
fastsearch-mcp compare --count 5 --days 30
```

再次生成报告后，可以在页面底部查看对照。两边的文件状态、搜索范围和处理方式可能不同，这些数据不能直接代表 AI 完成整个任务能快多少。测试数据和说明见 [验证记录](benchmarks/verification.md)。

<details>
<summary>更多设置</summary>

通常不需要修改这些设置。有需要时，在客户端的 MCP 环境变量中填写。

| 设置 | 作用 |
| --- | --- |
| `FASTSEARCH_TIMEOUT` | 搜索等待时间，默认 30 秒；DLL 导出单独限制为 300 秒 |
| `FASTSEARCH_DEFAULT_ROOT` | 使用相对路径时，从哪个目录开始查找；工具调用仍建议填写完整路径 |
| `FASTSEARCH_DEFAULT_EXCLUDES` | 默认跳过的目录名称，用逗号分隔；设为空字符串可取消默认排除 |
| `FASTSEARCH_FD_PATH` / `FASTSEARCH_RG_PATH` | 手动指定 fd / ripgrep 的程序位置 |
| `FASTSEARCH_ILSPYCMD_PATH` | 手动指定 DLL 导出工具的位置 |
| `FASTSEARCH_NO_DOWNLOAD` | 设为 `1`，禁止自动下载 fd / ripgrep |
| `FASTSEARCH_GITHUB_MIRROR` / `HTTPS_PROXY` | 下载时使用的镜像地址或代理 |
| `FASTSEARCH_CACHE_DIR` | fd / ripgrep 自动下载后的保存目录 |
| `FASTSEARCH_DECOMPILE_DIR` | DLL 代码的保存目录 |
| `FASTSEARCH_TELEMETRY_DIR` | 开发版调用记录的保存目录 |

多个 AI 助手需要共用一个本机服务时，可以这样启动，再把客户端连接地址设为 `http://127.0.0.1:8765/mcp`：

```powershell
fastsearch-mcp --transport streamable-http --port 8765
```

只需要匹配文件列表时，AI 可以使用 `search_text(..., output="files")`；只读取少量行且不需要文件总行数时，可以使用 `read_lines(..., count_total=false)`。搜索返回内容默认最多 24000 个字符，可以通过 `max_output_chars` 调整。

</details>

<details>
<summary>开发、打包与更新</summary>

### 测试

在仓库根目录运行：

```powershell
uv run python scripts/bundle.py fetch
uv run --extra test pytest -q -p no:cacheprovider --basetemp="$env:TEMP/fs-test"
```

测试会检查实际搜索、中文和编码、结果限制、MCP 连接以及分享版生成等功能。推送到主分支或提交 PR 时，也会在 Windows 上自动运行测试。

### 生成分享包

```powershell
uv run python scripts/bundle.py searchonly
```

生成的文件放在 `dist/`。分享版从主源码自动生成，会去掉调用记录和报告功能。随包程序的版本、下载地址和校验值列在 [bundled-binaries.json](bundled-binaries.json)，下载时会检查文件是否与记录一致，并附带上游许可证。

### 发布新版本

同时更新 `pyproject.toml` 和 `src/fastsearch_mcp/__init__.py` 的版本号，测试通过后提交并推送到 `main`。GitHub 会自动测试、打包、安装自检，并创建对应版本的 Release，附上 ZIP 和校验文件。两处版本号不同会停止发布，已有的 Release 会跳过。

带 `aN`、`bN`、`rcN` 或 `devN` 后缀的版本会标为预发布版。也可以在 GitHub Actions 页面手动运行 release 流程。

### 更新本机安装

Windows 上，运行中的服务可能占用安装文件。先关闭使用 FastSearch 的客户端，确认下面的命令没有输出，再进行更新：

```powershell
Get-Process fastsearch-mcp -ErrorAction SilentlyContinue
```

在仓库根目录执行：

```powershell
uv run python scripts/bundle.py fetch
uv tool install --force .
fastsearch-mcp --doctor
uv run python tests/installed_check.py
```

如果重装因文件被占用而中断，导致安装目录缺少文件，可以先在仓库根目录执行下面的命令补回文件，再关闭相关客户端后重新安装：

```powershell
uv pip install --python "$env:APPDATA/uv/tools/fastsearch-mcp/Scripts/python.exe" .
```

</details>

## 许可证

本项目使用 [MIT 许可证](LICENSE)。随包的第三方程序保留各自的许可证。
