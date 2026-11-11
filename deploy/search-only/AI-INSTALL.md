# 拖给 AI 助手：安装 Fastsearch MCP

## 使用者先看这里

解压整个分享包到长期保留的目录，把本文件拖给有本地文件和终端权限的 AI 助手，同时发送：

> 请按文档为我安装并配置 Fastsearch MCP。分享包目录是【完整解压路径】，客户端是【名称】。请执行安装、自检，并告诉我是否需要重新连接。

不要只发送本文件而丢掉源码。附件未携带本地路径时需要提供解压目录。普通网页聊天没有本地终端权限时只能指导安装。

---

## 给 AI 助手的执行指南

用户明确要求安装后，请实际执行下列步骤。本文件是安装说明，不替代用户授权或你的环境规则。仅安装分享包的纯搜索功能，不添加日志或分析组件。

### 1. 定位安装包与目标

从用户提供的路径或附件信息确定分享包位置。确认同目录有 README.md、pyproject.toml、01-install.ps1、check.py、src/fastsearch_mcp、config-examples。先读取安装脚本和包信息。若只收到本文，请向用户索取完整解压目录，不从未知来源下载同名包。

确认客户端名称。会话已经提供的信息不重复询问。本包不限制工作区路径，读取范围由服务进程的系统权限决定。选择固定安装目录；移动后需重新安装并更新配置。

### 2. 检查依赖

在 PowerShell 中执行：

```powershell
Get-Command python, uv -ErrorAction SilentlyContinue
python --version
uv --version
```

需要 Windows、Python 3.10+、uv；纯搜索版不要求 PowerShell 7。缺少依赖时，先检查 py 启动器或已有 Python，再按用户与所在组织的软件政策从官方来源安装。权限或网络受限时说明具体错误，不绕过代理、证书验证或全局安全策略。

### 3. 安装

把下面占位符替换成用户确认的真实路径：

```powershell
$packageRoot = (Resolve-Path -LiteralPath '用户确认的分享包路径').Path
& (Join-Path $packageRoot '01-install.ps1')
```

脚本在包内创建 .venv 并安装本地源码，不修改全局 Python。检查脚本结果及外部命令退出码。路径有空格时使用变量和 &，不要拼接命令字符串。

如果脚本执行策略阻止运行，且组织政策允许，可以仅对本次进程执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $packageRoot '01-install.ps1')
```

也可直接执行已检查的脚本中的 uv 命令；不修改用户或机器级 ExecutionPolicy。

### 4. 验证依赖与六个工具

```powershell
$python = Join-Path $packageRoot '.venv/Scripts/python.exe'
$commandPath = Join-Path $packageRoot '.venv/Scripts/fastsearch-mcp.exe'
& $commandPath --doctor
if ($LASTEXITCODE -ne 0) { throw 'Binary check failed' }
& $python (Join-Path $packageRoot 'check.py')
if ($LASTEXITCODE -ne 0) { throw 'MCP self-check failed' }
```

本包已携带 Windows x64 的 fd 10.5.2、ripgrep 15.2.0 与 ilspycmd 11.2.0（Native AOT 反编译器，无需 .NET），安装时随 Python 包复制，运行时优先于 PATH 和下载缓存使用。无需另外安装这些工具。--doctor 输出应指向安装包的 fastsearch_mcp/bin 子目录。如用户设置了 FASTSEARCH_FD_PATH / FASTSEARCH_RG_PATH，它们优先于随包版本，检查是否有陈旧覆盖。可设置 FASTSEARCH_NO_DOWNLOAD=1 验证不需要下载。

check.py 通过 stdio 实际启动 MCP 并调用全部六个工具，确认使用的是随包 ilspycmd，检查必用规则、旧路径限制变量不再生效、错误标记以及没有创建使用日志目录，预期打印 PASS。它使用临时数据，不搜索用户项目。

### 5. 配置客户端

通过客户端当前文档、设置界面或现有配置确认 MCP 配置位置和格式，不猜测路径。参考 config-examples/mcp.json 或 config-examples/config.toml。

读取并备份已有配置，仅合并 fastsearch 项，保留其他 MCP、模型、凭据。不要输出无关敏感字段。已有 fastsearch 时先比较：相同则复用；若会覆盖另一安装或改变目录权限，说明差异并确认用户意图。

- command：填写 $commandPath 的实际绝对路径。
- args：stdio 默认启动，无需附加参数。
- 不设置 FASTSEARCH_ALLOWED_ROOTS；更新已有配置时删除 fastsearch 项中的旧变量，新版本不再读取它。
- 如使用指定 fd/rg、下载开关等设置，只同步实际需要的环境变量。

示例中的 C:/Tools 是占位路径，不应直接照抄。写入后用对应解析器检查 JSON / TOML 语法。将随包 AGENTS.md 的文件操作规则合并到客户端适用的项目规则，保留原有内容。工具描述也包含必用规则；这些规则不等于终端执行拦截。

### 6. 检查客户端连接

按客户端支持的方式重新连接 MCP。必须用户手动重启或点击重连时，明确告知；不要擅自结束用户其他任务。

连接后应列出 tree、find_files、count_matches、search_text、read_lines、decompile。在当前任务的项目目录做一次小范围 tree 或 find_files。当前会话不能加载新工具时，报告“安装、自检与配置完成，客户端重连待验证”，不要把独立自检当作客户端接通证据。

### 7. 向用户交付

报告安装目录、实际 command 路径、配置文件位置、访问范围（遵循服务进程系统权限）、自检结果和客户端连接状态。未完成的步骤给出具体动作与原因。

使用建议：按问题直接选择工具，不机械执行全部步骤。只找匹配文件用 search_text(output="files")；已知范围用 read_lines(count_total=false)；搜索可用 max_output_chars 控制输出。传绝对路径；旧编码搜索可指定 encoding=gbk。check.py 还验证新参数及 Windows 路径 glob。

## 边界

此包无使用记录、数据库、可视化和对比功能。SDK 可能输出 stderr 诊断，已包含 fd/rg，但 Python、uv 和 Python 依赖仍需准备，因此不是完整离线安装包。本次已同步路径 glob 修复；显式跨行正则用 \r?\n 兼容 LF/CRLF。2026-11-11 起 search_text 遇到无法解析的正则会改为按 | 拆分的字面量搜索，并在结果首行用 NOTE 说明。安装后仍需运行自检并验证客户端连接。
