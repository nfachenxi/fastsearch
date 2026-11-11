"""MCP server exposing fd / ripgrep powered search tools."""

from __future__ import annotations

import asyncio
import functools
import time
from typing import Annotated, Literal, Optional

try:
    from . import telemetry
except ImportError:  # the search-only build ships without usage records
    telemetry = None

from pydantic import Field
from mcp.types import CallToolResult, TextContent

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore

try:
    from mcp.types import ToolAnnotations
    READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    # Writes only its own cache and runs a local process.
    LOCAL_CACHE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
except Exception:  # pragma: no cover
    READ_ONLY = LOCAL_CACHE = None

from . import search as S
from . import decompile as D
from .binaries import BinaryNotFound

INSTRUCTIONS = """\
Fast, gitignore-aware file & text search backed by fd and ripgrep.
For directory browsing, file discovery, text search/counting and text-file reading,
you MUST use these tools when available and capable of the requested operation.
Do not bypass them with PowerShell/cmd/bash commands (including Get-Content,
Get-ChildItem, Select-String, rg, fd, cat, grep) or Python/Node filesystem APIs.
Fallback is allowed only when the tool is absent, disconnected, explicitly fails,
or cannot perform the requested operation. Briefly state the concrete reason first;
limit fallback to that operation/path, then return to MCP for supported operations.
Empty results, truncation and ignored/hidden files are not fallback reasons:
adjust scope, limits, hidden/no_ignore or encoding as appropriate.
Builds, tests, Git and process management may use the terminal.
All filesystem paths readable by the server process are accessible; there is no
workspace-root allowlist.

Choose the shortest route; do not mechanically call every tool.
Known file/range: read_lines (count_total=false avoids scanning to EOF).
Known filename: find_files. Known text: search_text; output=files lists paths only.
Common patterns: count_matches for distribution. Unfamiliar layout: tree.
.NET DLL source: decompile(dll, type) gives a snapshot pinned to the DLL's hash; search
inside it instead of re-decompiling or trusting older decompiled folders.

Notes: always pass absolute paths (Windows `C:\\x`, `C:/x`, Git-Bash `/c/x` all work).
.gitignore'd files and node_modules/.git/.venv etc. are skipped unless no_ignore=true.
Legacy Chinese Windows files may be GBK: pass encoding="gbk" to search them.
"""

mcp = _Server("fastsearch", instructions=INSTRUCTIONS)


def _tool(fn=None, *, read_only=True):
    """Register a tool and report operational failures as MCP errors."""
    if fn is None:
        return functools.partial(_tool, read_only=read_only)

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            if telemetry is None:
                return await asyncio.to_thread(fn, *args, **kwargs)
            return await asyncio.to_thread(telemetry.invoke, fn, args, kwargs, time.perf_counter())
        except (S.SearchError, BinaryNotFound) as e:
            code = getattr(e, "code", "binary_not_found")
            return CallToolResult(
                isError=True,
                content=[TextContent(type="text", text=f"ERROR [{code}]: {e}")],
            )

    # One short steering line per tool for clients that do not surface server
    # instructions; the fallback rules live only in INSTRUCTIONS.
    kw = {"structured_output": False, "description": (fn.__doc__ or "") +
          "\n\nMUST use fastsearch instead of shell/filesystem APIs; see server instructions for fallback rules."}
    if READ_ONLY is not None:
        kw["annotations"] = READ_ONLY if read_only else LOCAL_CACHE
    return mcp.tool(**kw)(wrapper)


StrList = Optional[list[str]]
PathArg = Annotated[str, Field(description="Absolute directory (or file) path to search in.")]
Hidden = Annotated[bool, Field(description="Include hidden files/dirs (dotfiles, Windows hidden attr).")]
NoIgnore = Annotated[bool, Field(description="Do NOT respect .gitignore/.ignore and default excludes (node_modules, .git, ...).")]
Relative = Annotated[bool, Field(description="Print paths relative to `path` (fewer tokens) instead of absolute.")]
CaseArg = Annotated[Optional[bool], Field(description="true=case-sensitive, false=ignore case, null=smart case (sensitive only if pattern has uppercase).")]


@_tool
def find_files(
    path: PathArg,
    pattern: Annotated[str, Field(description="Glob (default) or regex matched against the file NAME, e.g. '*.py', 'test_*', '*config*'. Empty = list everything.")] = "",
    regex: Annotated[bool, Field(description="Treat pattern as a regex instead of a glob.")] = False,
    full_path: Annotated[bool, Field(description="Match pattern against the full relative path instead of the name, e.g. glob '**/src/**/*.ts'.")] = False,
    extensions: Annotated[StrList, Field(description="Filter by extensions, e.g. ['py','ts'].")] = None,
    file_type: Annotated[Optional[Literal["file", "directory", "symlink", "executable", "empty"]], Field(description="Restrict entry type.")] = None,
    max_depth: Annotated[Optional[int], Field(description="Max directory depth (1 = direct children).")] = None,
    exclude: Annotated[StrList, Field(description="Extra glob patterns to exclude, e.g. ['dist','*.min.js'].")] = None,
    changed_within: Annotated[Optional[str], Field(description="Only entries modified within this duration/date, e.g. '2d', '3h', '2026-01-01'.")] = None,
    min_size: Annotated[Optional[str], Field(description="Minimum size, e.g. '10k', '1m'.")] = None,
    max_size: Annotated[Optional[str], Field(description="Maximum size, e.g. '500k'.")] = None,
    case_sensitive: CaseArg = None,
    hidden: Hidden = False,
    no_ignore: NoIgnore = False,
    max_results: Annotated[int, Field(description="Max entries returned (1-10000).")] = 200,
    relative: Relative = False,
) -> str:
    """Find files/directories by name using fd (fast, respects .gitignore).

    Use instead of `dir /s`, `Get-ChildItem -Recurse` or `find`. Directories are shown with a
    trailing separator. Output is sorted; when truncated, narrow `path`/`pattern`.
    """
    return S.find_files(
        path, pattern, glob=not regex, full_path=full_path, extensions=extensions,
        file_type=file_type, max_depth=max_depth, hidden=hidden, no_ignore=no_ignore,
        exclude=exclude, case_sensitive=case_sensitive, changed_within=changed_within,
        min_size=min_size, max_size=max_size, max_results=max_results, relative=relative,
    )


@_tool
def search_text(
    pattern: Annotated[str, Field(description="Rust regex (like PCRE without lookaround/backrefs). Set literal=true to search a plain string with special chars.")],
    path: PathArg,
    literal: Annotated[bool, Field(description="Treat pattern as a fixed string, not a regex.")] = False,
    case_sensitive: CaseArg = None,
    word: Annotated[bool, Field(description="Only match whole words.")] = False,
    include: Annotated[StrList, Field(description="Only search files matching these globs, e.g. ['*.py','src/**'].")] = None,
    exclude: Annotated[StrList, Field(description="Skip files matching these globs, e.g. ['*.min.js','tests/**'].")] = None,
    file_types: Annotated[StrList, Field(description="ripgrep file types, e.g. ['py'], ['ts','js'], ['cpp'], ['cs'].")] = None,
    context: Annotated[int, Field(description="Lines of context before AND after each match (0-50).")] = 0,
    before: Annotated[Optional[int], Field(description="Lines of context before (overrides `context`).")] = None,
    after: Annotated[Optional[int], Field(description="Lines of context after (overrides `context`).")] = None,
    max_results: Annotated[int, Field(description="Maximum match events in content mode, or matching files in files mode (1-5000).")] = 100,
    max_per_file: Annotated[Optional[int], Field(description="Max matching lines per file.")] = None,
    multiline: Annotated[bool, Field(description="Allow pattern to span lines ('.' also matches newline).")] = False,
    encoding: Annotated[Optional[str], Field(description="Force text encoding, e.g. 'gbk', 'utf-16le', 'shift_jis'. Default: auto (UTF-8/UTF-16 BOM).")] = None,
    max_line_length: Annotated[int, Field(description="Trim long lines (minified files) to this many chars around the match.")] = 300,
    hidden: Hidden = False,
    no_ignore: NoIgnore = False,
    relative: Relative = False,
    output: Annotated[Literal["content", "files"], Field(description="content returns matching lines; files returns each matching path once, without counting all occurrences.")] = "content",
    max_output_chars: Annotated[int, Field(ge=1024, le=1000000, description="Total output character budget, including headings and context (1024-1000000).")] = 24000,
) -> str:
    """Search file contents with ripgrep and return matching lines grouped by file.

    Use instead of findstr / Select-String / grep. Format: `<line>: text` for matches,
    `<line>- text` for context, `--` between non-adjacent blocks.
    Tip: run count_matches first when the pattern may be very common.
    """
    return S.search_text(
        pattern, path, literal=literal, case_sensitive=case_sensitive, word=word,
        include=include, exclude=exclude, file_types=file_types, context=context,
        before=before, after=after, max_results=max_results, max_per_file=max_per_file,
        hidden=hidden, no_ignore=no_ignore, multiline=multiline, encoding=encoding,
        max_line_length=max_line_length, relative=relative,
        output=output, max_output_chars=max_output_chars,
    )


@_tool
def count_matches(
    pattern: Annotated[str, Field(description="Rust regex, or plain string with literal=true.")],
    path: PathArg,
    literal: Annotated[bool, Field(description="Treat pattern as a fixed string.")] = False,
    case_sensitive: CaseArg = None,
    word: Annotated[bool, Field(description="Only match whole words.")] = False,
    include: Annotated[StrList, Field(description="Only files matching these globs.")] = None,
    exclude: Annotated[StrList, Field(description="Skip files matching these globs.")] = None,
    file_types: Annotated[StrList, Field(description="ripgrep file types, e.g. ['py'].")] = None,
    encoding: Annotated[Optional[str], Field(description="Force encoding, e.g. 'gbk'.")] = None,
    max_files: Annotated[int, Field(description="How many files to list (sorted by count desc).")] = 50,
    hidden: Hidden = False,
    no_ignore: NoIgnore = False,
    relative: Relative = False,
) -> str:
    """Count matches per file (ripgrep), sorted by count. Cheap overview of where a
    symbol/string is used; also answers "which files contain X"."""
    return S.count_matches(
        pattern, path, literal=literal, case_sensitive=case_sensitive, word=word,
        include=include, exclude=exclude, file_types=file_types, hidden=hidden,
        no_ignore=no_ignore, encoding=encoding, max_files=max_files, relative=relative,
    )


@_tool
def read_lines(
    path: Annotated[str, Field(description="Absolute path of the file to read.")],
    start: Annotated[int, Field(description="First line to return (1-based).")] = 1,
    end: Annotated[Optional[int], Field(description="Last line to return (inclusive). Default: start + max_lines - 1.")] = None,
    max_lines: Annotated[int, Field(description="Upper bound on returned lines (1-2000).")] = 200,
    encoding: Annotated[Optional[str], Field(description="Force encoding. Default auto-detects BOM / UTF-8 / GB18030.")] = None,
    count_total: Annotated[bool, Field(description="Count all lines (compatible default). Set false to stop after the requested range plus one lookahead line.")] = True,
) -> str:
    """Read a line range of a text file with line numbers. Auto-detects UTF-8 / UTF-16 /
    GBK so Chinese Windows files are not garbled. Use after search_text to see more context."""
    return S.read_lines(path, start, end, max_lines=max_lines, encoding=encoding, count_total=count_total)


@_tool
def tree(
    path: PathArg,
    max_depth: Annotated[int, Field(description="Depth to descend (1-12).")] = 3,
    dirs_only: Annotated[bool, Field(description="Only show directories.")] = False,
    exclude: Annotated[StrList, Field(description="Extra globs to exclude.")] = None,
    max_entries: Annotated[int, Field(description="Max lines of output.")] = 400,
    per_dir_limit: Annotated[int, Field(description="Max children listed per directory before collapsing to '… (+N more)'.")] = 40,
    hidden: Hidden = False,
    no_ignore: NoIgnore = False,
) -> str:
    """Compact directory tree (gitignore-aware, skips node_modules/.git/...). Use first to
    understand an unfamiliar project's structure."""
    return S.tree(
        path, max_depth=max_depth, hidden=hidden, no_ignore=no_ignore, dirs_only=dirs_only,
        exclude=exclude, max_entries=max_entries, per_dir_limit=per_dir_limit,
    )


@_tool(read_only=False)
def decompile(
    dll: Annotated[str, Field(description="Absolute path of a .NET assembly (.dll).")],
    type: Annotated[Optional[str], Field(description="Type name, e.g. 'PlayerController'. Returns its source; omit to get only the snapshot directory.")] = None,
) -> str:
    """Decompile a .NET DLL with ilspycmd into a snapshot pinned to the DLL's SHA256
    and the decompiler version (a bundled ilspycmd is used when present).

    The whole assembly is exported once per DLL version and cached; later calls are instant.
    Use instead of running ilspycmd or reading older decompiled folders (e.g. .tmp_ilspy,
    TempDecompile), which may not match the current DLL. Search the returned snapshot with
    search_text / read_lines.
    """
    return D.decompile(dll, type)
