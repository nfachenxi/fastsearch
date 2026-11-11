# 文件查找、文本搜索与读取

- fastsearch MCP 可用且能完成当前操作时，必须使用它浏览目录、查找文件、统计匹配、搜索文本和读取文本文件。对应工具为 tree、find_files、count_matches、search_text、read_lines。
- 需要 .NET DLL 源码时调用 fastsearch 的 decompile，在返回的快照目录中检索；不要直接运行 ilspycmd，也不要使用旧的反编译副本。
- 不得使用 PowerShell/cmd/bash、直接调用 rg/fd，或 Python/Node 文件 API 绕过上述操作。
- 空结果、截断、隐藏文件和忽略规则不是回退理由；先调整范围、结果上限、hidden、no_ignore 或编码。已知文件和行号时直接 read_lines，不必机械执行全部搜索步骤。
- 仅在工具缺失、连接失败、明确报错或不支持所需操作时，允许针对受影响的操作和路径回退；执行前简短说明具体原因，其他支持的操作继续使用 MCP。
- 构建、测试、Git、进程管理与文件编辑可使用相应终端或编辑工具。
- MCP 不限制工作区根目录；访问能力由服务进程的操作系统权限决定。
