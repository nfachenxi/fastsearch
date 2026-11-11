# Fastsearch MCP 纯搜索分享版

提供 tree、find_files、count_matches、search_text、read_lines 和 decompile 六个工具。没有使用记录、数据库、可视化面板或 PowerShell 对比功能。

## 获取

从 https://github.com/nfachenxi/fastsearch/releases 下载最新的 Fastsearch-MCP-Share.zip。本包由开发仓库的 `scripts/bundle.py searchonly` 自动生成，源码与开发版一致，只是不包含使用记录模块。

## 让 AI 帮你安装

完整解压后，把 [AI-INSTALL.md](AI-INSTALL.md) 拖给具备本地终端权限的 AI 助手，并提供解压路径和客户端名称。

## 安装与接入

Windows 需要 Python 3.10+ 和 uv。将文件夹放到固定位置，在 PowerShell 中执行：

    powershell -NoProfile -ExecutionPolicy Bypass -File ./01-install.ps1

安装脚本创建本目录 .venv 并输出 MCP command 路径。若所在组织的策略不允许 Bypass，使用组织批准的脚本运行方式。参考 config-examples，将 command 替换为实际路径。更新已有安装也需重新运行脚本并重连 MCP。

已打包 Windows x64 的 fd 10.5.2、ripgrep 15.2.0 和 ilspycmd 11.2.0（反编译器，自包含，无需 .NET），附上游许可证；安装后自动使用，无需单独下载。二进制来源和 SHA-256 见 src/fastsearch_mcp/bin/BUNDLED-BINARIES.json。Python、uv 和 Python 包依赖仍需准备。

## 使用

按问题直接选择工具：已知文件和行号直接 read_lines；文件名用 find_files；文本用 search_text；常见词先 count_matches 看分布；不熟悉目录时才 tree。传绝对路径，默认尊重 .gitignore。GBK 中文文本搜索可指定 encoding=gbk。

2026-11-10 更新：

- read_lines(count_total=false)：目标范围后只多读一行判断后续内容；默认 true 保留准确总行数。
- search_text(output="files")：每个匹配文件只返回一次；max_results 此时限制文件数。
- search_text(max_output_chars=24000)：限制包含标题、路径和上下文的结果字符数，可设 1024–1000000；达到预算会提示截断。上下文过多可能在展示匹配前耗尽预算，应缩小 context 或提高预算。
- Windows 路径 glob 使用 /，例如 **/fastsearch_mcp/server.py。显式跨行正则用 \r?\n 兼容 LF/CRLF。

2026-11-11 更新：

- search_text 的正则无法解析时（如 Awake|Start(|Init、humanObjects[），按 | 拆开逐段当字面量重搜一次，结果首行标注 NOTE: invalid regex; searched literally for: …。若本意是正则，按提示修正后重搜。count_matches 仍直接报错。

2026-11-11 新增 decompile（版本 0.3.0）：

- decompile(dll, type)：用随包的 ilspycmd 11.2（Native AOT，自包含，无需安装 .NET）把整个 .NET DLL 反编译成快照，目录名带 DLL 内容哈希和反编译器版本，同一版本只导出一次，之后直接命中缓存。传 type 时直接返回该类型源码；否则返回快照目录，再用 search_text / read_lines 检索。快照位于 %LOCALAPPDATA%/fastsearch-mcp/decompile，可用 FASTSEARCH_DECOMPILE_DIR 改位置；FASTSEARCH_ILSPYCMD_PATH 可指定其他 ilspycmd。
- 搜索中部分文件无法读取（rg 退出码 2）时，正文模式和 count_matches 也会在首行标注 WARNING: rg reported errors; results are partial。
- read_lines 行号不再补齐宽度（12<TAB>内容），约省 19% 输出 token。
- 工具描述中的回退规则只保留在服务器说明里，每个工具只留一句 MUST，减少每次请求的固定开销。

## 自检

    ./.venv/Scripts/python.exe check.py

自检使用临时文件，检查全部六个 MCP 工具、随包反编译器、必用规则、旧路径限制变量不再生效、错误标记和无使用日志。也可以用 ./.venv/Scripts/fastsearch-mcp.exe --doctor 检查 fd/rg。

## 工具规则与路径访问

已移除 FASTSEARCH_ALLOWED_ROOTS，不设置工作区路径白名单；可读取服务进程有系统权限访问的任意目录，旧变量不再生效。

受支持的目录浏览、文件查找、文本搜索、匹配统计和文本读取必须使用 MCP。仅在工具缺失、连接失败、明确报错或能力不支持时，说明具体原因后对受影响的操作和路径回退。空结果、截断和忽略规则不构成回退理由。每个工具的描述均包含一句必用规则；项目规则参考 [AGENTS.md](AGENTS.md)。这些文字规则不构成终端执行拦截。

操作失败返回 MCP isError=true 和错误分类，空结果属于正常成功。

## 分享边界

本包无个人使用数据，不是离线安装包，不捆绑 Python、uv 和 Python 第三方依赖。安装后不要分享 .venv，它不可跨机器复制；移动目录后重新安装并更新客户端路径。SDK 可能输出 stderr 诊断，二进制可能写入下载缓存，这些不属于使用日志采集。

安装后运行 check.py 验证当前环境。版本号带 +searchonly 后缀，例如 0.3.0+searchonly。
