# fastsearch-mcp

基于 [fd](https://github.com/sharkdp/fd) 和 [ripgrep](https://github.com/BurntSushi/ripgrep) 的 MCP 服务器，给任意 Agent（Claude Desktop / Claude Code / Cursor / Cline / Codex / Continue 等）提供快速、可靠、默认尊重 `.gitignore` 的文件查找与文本搜索。重点针对 Windows 上 Agent 常见的几类问题：

| Agent 在 Windows 上的典型问题 | 本项目的处理 |
| --- | --- |
| `Get-ChildItem -Recurse` / `dir /s` / `findstr` 很慢，钻进 `node_modules`、`.git` | fd/rg 并行遍历，默认尊重 `.gitignore`（非 git 目录也生效），并内置常见排除目录 |
| 输出动辄几万行，撑爆上下文 | 所有工具都有结果上限、长行裁剪（压缩过的 js 文件也不会刷屏），截断时明确提示下一步怎么缩小范围 |
| 路径格式混乱：`C:\x`、`C:/x`、`/c/x`、`/mnt/c/x` | 统一规范化为 Windows 原生绝对路径 |
| GBK 老文件搜不到中文 / 读出来是乱码 | `search_text` 支持 `encoding="gbk"`；`read_lines` 自动识别 UTF-8 / UTF-16 BOM / GB18030 |
| CRLF 导致正则 `$` 匹配失败 | rg 默认启用 `--crlf` |
| PowerShell 引号、转义把正则搞坏 | 参数直接传给进程，不经过 shell |
| 子进程弹黑框、卡死 | `CREATE_NO_WINDOW` 启动 + 超时强杀（默认 30 秒） |
| 本机没装 fd / rg | 分享包随带 Windows x64 fd/rg；开发安装先查 PATH，找不到就自动从 GitHub Release 下载到缓存目录（支持镜像和代理） |
| 反编译 DLL 的副本不知道对应哪个版本，反复重新反编译 | `decompile` 按 DLL 内容哈希和反编译器版本各导出一次快照，之后直接命中缓存 |

## 两种版本

| 版本 | 内容 | 获取方式 |
| --- | --- | --- |
| 开发版（本仓库） | 六个工具，加上本机使用记录、离线报告 `report`、PowerShell 对照 `compare` | `git clone` 后本地安装，见下文“安装” |
| 纯搜索部署版 `Fastsearch-MCP-Share` | 同样六个工具，不含使用记录模块，什么都不记录；附 Windows x64 fd/rg/ilspycmd、安装脚本、AI 安装说明和自检 | [GitHub Releases](https://github.com/nfachenxi/fastsearch/releases) 下载 zip |

两者共用 `src/fastsearch_mcp` 同一份源码。部署版由 `scripts/bundle.py searchonly` 从本仓库生成：复制 `deploy/search-only/` 的模板和搜索模块，去掉 `telemetry.py`、`report.py`、`compare.py` 和报告页面，版本号加 `+searchonly`。源码在缺少 `telemetry` 模块时自动不记录，所以两版不会再出现手工同步的差异。

## 提供的工具

| 工具 | 作用 | 替代的命令 |
| --- | --- | --- |
| `tree` | 精简目录树（按深度展开，大目录自动折叠为 `… (+N more)`） | `tree`, `ls -R` |
| `find_files` | 按文件名 glob/正则、扩展名、类型、修改时间、大小查找 | `dir /s`, `Get-ChildItem`, `find` |
| `count_matches` | 统计每个文件里的匹配数，按数量降序排列；先看分布再决定看哪里 | `rg -c` |
| `search_text` | 搜索文件内容，按文件分组，可带上下文行 | `findstr`, `Select-String`, `grep` |
| `read_lines` | 读取文件的指定行范围，带行号，自动识别编码 | `type`, `Get-Content`, `sed -n` |
| `decompile` | 把 .NET DLL 整体反编译成快照（随包 ilspycmd 11.2，Native AOT，无需 .NET）；传 `type` 直接返回该类型源码 | `ilspycmd -p -o ...` |

除 `decompile` 外的工具都标注为只读（`readOnlyHint`），不会修改被搜索文件；`decompile` 只写自己的快照目录 `%LOCALAPPDATA%/fastsearch-mcp/decompile`。默认会在本地应用数据目录记录调用元数据。

## 使用记录与离线分析面板

每次进入工具执行入口的调用默认写入 `%LOCALAPPDATA%/fastsearch-mcp/usage.sqlite3`。记录时间、工具、路径、查询参数、版本、耗时、输出大小、错误与结果限制，不保存返回源码正文。查询词和错误摘要为明文，数据只保存在本机，不自动删除。

```powershell
fastsearch-mcp report --days 30
fastsearch-mcp report --days 7 --output ./reports/fastsearch.html
```

打开命令输出的 HTML 路径即可离线查看。支持上海日期、工具、路径和状态筛选，P50/P95、每日趋势、工具分布、慢调用排序以及逐条参数详情。每页显示 12 条，但统计包含整个筛选结果。重新执行命令才能更新快照。

环境变量：`FASTSEARCH_TELEMETRY=0` 关闭记录；`FASTSEARCH_TELEMETRY_DIR` 指定存储目录。测试使用临时目录，不混入日常记录。写入失败不会中断搜索，诊断发送到 stderr。多进程竞争时最多等待数据库锁 0.5 秒；失败的记录可能缺失。

统计口径：耗时包含服务内线程等待，不包含数据库写入、客户端网络或模型思考；P50/P95 使用 nearest-rank，空数据展示 0。错误、超时、扫描不完整、展示受限分别记录，可以重叠。`search_text` 计匹配事件，`count_matches` 计匹配次数，其他工具计条目或行，不能跨工具相加。无结果不等于错误，按范围读文件不算截断。SDK 在包装器前拒绝的参数、连接失败与进程强制退出不保证有记录。

安装后需要重新加载客户端 MCP 连接，新启动的服务才会启用记录。纯搜索部署版不含此功能，`report` / `compare` 会提示不可用。

性能验证：`uv run python benchmarks/usage_benchmark.py --output benchmarks/results.json`。脚本使用 300 个 UTF-8 文件、每个 31 行，交替测量开关记录的 30 轮稳定调用，同时与 Python pathlib 搜索核对结果。它不代表 PowerShell、真实大型项目或任务总耗时的提升；原始样本会保留。

Agent 按当前问题直接选择工具，无需机械执行整条调用链：已知文件和行号直接 `read_lines`；已知文件名用 `find_files`；已知文本用 `search_text`；常见词需要分布时用 `count_matches`；不熟悉目录时再用 `tree`。

### 减少扫描和输出

- `read_lines(..., count_total=false)`：读取目标范围后只多取一行判断是否还有内容，返回 `has_more=true` 和下一次起始行，不为统计总行数扫描到末尾。默认 `count_total=true` 保留原有准确总行数输出；读取靠近文件末尾的范围仍需跳过前面的行。
- `search_text(..., output="files")`：只返回包含匹配的文件路径，每个文件在首次匹配后停止，不统计全部出现次数。`max_results` 在此模式下限制文件数，默认 `output="content"` 保留正文模式。上下文及 `max_per_file` 仅用于正文模式。
- `search_text(..., max_output_chars=24000)`：限制整个成功结果的字符数，包括路径、标题和上下文；允许 1024–1000000。达到预算时提前停止收集，提示 `TRUNCATED`，应缩小范围或提高预算。字符数不是 token 数；操作错误仍通过 `isError=true` 返回诊断。
- Windows 的 `full_path=true` 路径 glob 使用 `/`，例如 `**/pkg/*.py`；`*` 不跨目录，`**` 匹配多层目录。
- 多行正则若需兼容 LF 和 CRLF，使用 `\r?\n`，例如 `class Foo:\r?\n\s+pass`。
- `search_text` 的正则无法解析时（如 `Awake|Start(|Init`、`humanObjects[`），按 `|` 拆开逐段当字面量重搜一次，结果首行标注 `NOTE: invalid regex; searched literally for: …`，使用记录标记 `regex_fallback=true`、状态为警告。`count_matches` 仍直接报错。

例：`search_text(path="C:/proj/src", pattern="PlayerController", literal=true, output="files", relative=true)`；定位文件后直接按范围读取。

输出示例（`search_text`，`context=1`，`relative=true`）：

```
3 match(es) in 2 file(s) under C:\proj\src (TRUNCATED at max_results=3; use count_matches ...)

app/main.py
  9-
  10: def main(argv: list[str] | None = None) -> None:
  11-     ap = argparse.ArgumentParser(...)

app/search.py
  26-
  27: def _env_list(name: str, default: list[str]) -> list[str]:
  28-     raw = os.environ.get(name)
```

输出用的是精简文本，不是 JSON，这样对 LLM 更省 token，也更容易读懂（`行号:` 是匹配行，`行号-` 是上下文行，`--` 表示中间跳过了一段）。

## 安装

需要 Python ≥ 3.10 和 [uv](https://docs.astral.sh/uv/)（Windows：`winget install astral-sh.uv`）。

**纯搜索部署版**：从 [Releases](https://github.com/nfachenxi/fastsearch/releases) 下载 `Fastsearch-MCP-Share.zip`，解压到固定位置，按包内 README.md 运行 `01-install.ps1`，或把包内 AI-INSTALL.md 交给有终端权限的 AI 助手执行。

**开发版**（全局安装，Codex / Claude Code 等客户端直接启动 `fastsearch-mcp`）：

```powershell
git clone git@github.com:nfachenxi/fastsearch.git C:\tools\fastsearch
cd C:\tools\fastsearch
uv run python scripts/bundle.py fetch      # 把固定版本的 fd/rg/ilspycmd 放进 src/fastsearch_mcp/bin/
uv tool install --force .
fastsearch-mcp --doctor                    # 查看最终会用哪个 fd/rg
```

也可以不克隆直接安装：`uv tool install git+https://github.com/nfachenxi/fastsearch@v0.3.0`。这种方式没有随包二进制：fd/rg 先查 PATH，找不到时自动从 GitHub Release 下载到缓存目录；ilspycmd 不会自动下载，需自行安装（`dotnet tool install -g ilspycmd`）或设置 `FASTSEARCH_ILSPYCMD_PATH`，否则 `decompile` 不可用。

PATH 上版本过旧的 fd/rg 会被跳过（fd < 8.7 / rg < 11）。

## 接入各个客户端

下面以全局安装得到的 `fastsearch-mcp` 命令为例；部署版的 `command` 填安装脚本输出的 `.venv\Scripts\fastsearch-mcp.exe` 绝对路径。

**Claude Desktop**：编辑 `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "fastsearch": {
      "command": "fastsearch-mcp"
    }
  }
}
```

**Claude Code**

```powershell
claude mcp add fastsearch -s user -- fastsearch-mcp
```

**Cursor**（`~/.cursor/mcp.json`）/ **Cline** / **Windsurf** / **Continue**：配置格式和 Claude Desktop 相同（`mcpServers` → `command` / `args` / `env`）。

**OpenAI Codex CLI**（`~/.codex/config.toml`）

```toml
[mcp_servers.fastsearch]
command = "fastsearch-mcp"
```

**HTTP 方式**（给不支持 stdio 的客户端，或者多个 Agent 共用一个服务）：

```powershell
fastsearch-mcp --transport streamable-http --port 8765   # http://127.0.0.1:8765/mcp
```

如果在 Windows 上启动时提示找不到 `fastsearch-mcp`，把 `command` 改成它的完整路径，一般是 `C:\\Users\\<你>\\.local\\bin\\fastsearch-mcp.exe`。

## 环境变量

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `FASTSEARCH_DEFAULT_ROOT` | 工具不传 `path`、或传相对路径时使用的根目录 | 无（这时必须传绝对路径） |
| `FASTSEARCH_TIMEOUT` | 单次调用超时秒数，超时返回已拿到的部分结果 | `30` |
| `FASTSEARCH_DEFAULT_EXCLUDES` | 逗号分隔的默认排除目录，设为空字符串表示不排除 | `.git,node_modules,__pycache__,.venv,venv,.mypy_cache,.pytest_cache,.tox,.idea,.vs,.gradle,.next,.nuxt` |
| `FASTSEARCH_FD_PATH` / `FASTSEARCH_RG_PATH` | 指定 fd/rg 可执行文件路径 | 自动查找 |
| `FASTSEARCH_FD_VERSION` / `FASTSEARCH_RG_VERSION` | 自动下载时用的版本 | `10.5.2` / `15.2.0` |
| `FASTSEARCH_GITHUB_MIRROR` | GitHub 下载镜像前缀，例如 `https://ghfast.top/` | 无 |
| `HTTPS_PROXY` | 下载 fd/rg 时使用的代理 | 无 |
| `FASTSEARCH_NO_DOWNLOAD` | 设为 `1` 时禁止自动下载（适合离线或内网环境） | 无 |
| `FASTSEARCH_CACHE_DIR` | 下载缓存目录 | `%LOCALAPPDATA%\fastsearch-mcp\bin` |
| `FASTSEARCH_ILSPYCMD_PATH` | 指定 ilspycmd 可执行文件，优先于随包版本和 PATH | 随包 → PATH |
| `FASTSEARCH_DECOMPILE_DIR` | 反编译快照目录（旧快照不自动清理，每个约 5 MB） | `%LOCALAPPDATA%\fastsearch-mcp\decompile` |

## 让 Agent 优先用这些工具

服务器 instructions 和工具描述要求受支持的文件操作使用 MCP。客户端仍需在 `CLAUDE.md` / `AGENTS.md` / `.cursorrules` 中明确规则；这些文字规则不等于终端执行拦截。可使用本仓库 [AGENTS.md](AGENTS.md) 或下列规则：

```markdown
## 搜索规范
- 浏览目录、查找文件、统计匹配、搜索文本和读取文本文件，必须使用能完成该操作的 fastsearch MCP 工具。
- 不得用 PowerShell/cmd/bash、直接调用 rg/fd 或 Python/Node 文件 API 绕过 MCP。
- 空结果、截断、隐藏或被忽略的文件不是回退理由，先调整范围、限制、hidden/no_ignore 或编码。
- 仅在工具缺失、连接失败、明确报错或能力不支持时，说明原因后对受影响的操作和路径回退，其他支持的操作继续使用 MCP。
- 已知文件和行号时直接 read_lines；常见词先 count_matches 查看分布，无需机械执行所有步骤。
- 构建、测试、Git、进程管理和文件编辑可使用终端或编辑工具。
- 一律传绝对路径。中文老项目搜不到中文时，加上 encoding="gbk"。
```

## 开发与测试

```powershell
uv run python scripts/bundle.py fetch
uv run --extra test pytest -q -p no:cacheprovider --basetemp="$env:TEMP/fs-test"
```

临时目录放在仓库外，避免在工作区留下测试文件夹。测试会调用真实的 fd/rg 二进制，覆盖这些场景：gitignore（包括非 git 目录）、默认排除目录、隐藏文件、中文文件名、GBK 编码、CRLF、超长行裁剪、截断提示、多行匹配、二进制文件、旧路径限制变量不再生效、一次完整的 MCP stdio 往返调用，以及纯搜索部署版的生成与自检。已验证兼容 mcp SDK 1.x 和 2.x、ripgrep 13 和 15。每次推送到 GitHub 会在 Windows 上自动运行同样的测试（`.github/workflows/ci.yml`）。

### 发布流程

1. 改 `pyproject.toml` 和 `src/fastsearch_mcp/__init__.py` 里的版本号，测试通过后提交。
2. 本地生成并自检部署版（可选，CI 也会做）：

   ```powershell
   uv run python scripts/bundle.py searchonly        # 生成 dist/Fastsearch-MCP-Share 和 .zip
   ```

3. 打标签并推送：`git tag v0.3.1; git push origin main v0.3.1`。`.github/workflows/release.yml` 会在 Windows 上测试、生成部署版、运行包内 check.py，然后把 zip 附到同名 GitHub Release。
4. 按下一节更新本机全局安装。

### 更新本机全局安装

运行中的服务会锁住安装目录，导致重装中途失败（os error 32）。先关闭所有启动 fastsearch 的客户端（Codex、Claude Code 等），确认 `Get-Process fastsearch-mcp -ErrorAction SilentlyContinue` 无输出，再在仓库根目录执行：

```powershell
uv run python scripts/bundle.py fetch
uv tool install --force .
fastsearch-mcp --doctor
uv run python tests/installed_check.py    # 六个工具可用，五次读取写入临时使用记录后自动删除
```

如果重装失败后 `%APPDATA%\uv\tools\fastsearch-mcp\Lib\site-packages\fastsearch_mcp` 只剩 `__pycache__`，安装已被删除一半，新启动的客户端会失败。不要直接重试，先只写入、不删除地补回文件，再关闭客户端后重装：

```powershell
uv pip install --python "$env:APPDATA\uv\tools\fastsearch-mcp\Scripts\python.exe" .
```

## 已知限制

- `search_text` 的 `encoding` 每次只能指定一种编码。如果一个仓库里 UTF-8 和 GBK 文件混在一起，需要分两次搜索。
- 不设工作区路径白名单，所有操作遵循服务进程的操作系统访问权限。`FASTSEARCH_ALLOWED_ROOTS` 已移除，旧配置即使保留也不再生效。
- 操作失败返回 MCP `isError=true` 和带错误分类的文本；空结果属于正常成功，截断与超时的部分结果仍需查看输出提示。
- 正则使用 Rust regex 语法，不支持环视（lookaround）和反向引用。`search_text` 遇到无法解析的正则会改为字面量搜索并在首行说明，若本意是正则（如 `range_light_points*(`），按提示修正后重搜。


## 随机历史请求的 PowerShell 对照

运行 `fastsearch-mcp compare --count 5 --days 30`，从最近使用记录中随机、不放回抽取最多 5 条可转换请求，每条执行一次 PowerShell 7。可用 `--seed 42` 复现抽样（前提是候选记录未改变），用 `--timeout 30` 设置每条执行上限。

数据独立保存到日志目录的 `comparisons/时间-批次.json`，不会写回日常调用表。再运行 report 命令，页面底部按批次展示抽样对照；上方筛选不会改变独立批次内容。每批保留原记录 ID、参数、历史耗时、PowerShell 操作耗时与进程总耗时、结果数量、脚本、随机种子和跳过原因。

第一版支持 read_lines、简单 find_files、无上下文的字面量 search_text；复杂参数、正则及失败历史记录会跳过，样本不足时使用全部候选记录。PowerShell 使用 Get-Content、Get-ChildItem、Select-String。参数通过 JSON 环境变量传递，不拼接为可执行脚本。

这属于历史请求的常用命令对照，不保证两边工作量等价：文件、缓存、忽略目录、编码、二进制跳过和输出格式可能不同。历史未保存结果正文，所以数量相同也不能证明内容一致。页面不根据这些样本宣称总体提速。未使用历史原命令，而是生成对应 PowerShell 命令。

## 随包二进制

部署版和开发安装需要的 Windows x64 可执行文件（fd、rg、ilspycmd）及上游许可证由 [bundled-binaries.json](bundled-binaries.json) 固定版本、下载地址和 SHA-256，通过脚本下载校验后写入 `src/fastsearch_mcp/bin/`。该目录被 git 忽略，pyproject 的 hatch `artifacts` 保证它仍进入 wheel。运行时查找顺序：环境变量 → 随包 `bin/` → PATH →（fd/rg）下载缓存。

```powershell
uv run python scripts/bundle.py fetch              # 放进本仓库，开发安装与全局安装使用
uv run python scripts/bundle.py searchonly         # 生成部署版时自动放进 dist/Fastsearch-MCP-Share
```

下载按哈希缓存在 `%LOCALAPPDATA%/fastsearch-mcp/bundle-cache`，支持 HTTPS_PROXY。ilspycmd 版本是快照目录名的一部分，升级后会重新导出。
