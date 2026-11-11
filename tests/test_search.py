"""Functional tests: run against real fd / rg binaries.

    pip install -e .[test] && pytest -q
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys

import pytest

from fastsearch_mcp import search as S


@pytest.fixture()
def proj(tmp_path, monkeypatch):
    monkeypatch.delenv("FASTSEARCH_ALLOWED_ROOTS", raising=False)
    monkeypatch.delenv("FASTSEARCH_DEFAULT_ROOT", raising=False)
    r = tmp_path / "proj"
    (r / "src" / "pkg").mkdir(parents=True)
    (r / "node_modules" / "lib").mkdir(parents=True)
    (r / "build").mkdir()
    (r / ".hidden").mkdir()
    (r / "文档").mkdir()
    (r / ".gitignore").write_text("build/\n*.log\n")
    (r / "src" / "main.py").write_text(
        "import os\n\n\ndef hello_world():\n    return 'Hello'\n\n\nclass Foo:\n    pass\n"
    )
    (r / "src" / "pkg" / "util.py").write_text("def helper():\n    hello_world()\n    hello_world()\n")
    (r / "src" / "app.ts").write_bytes(b"export const x = 1;\r\nfunction hello_world() {}\r\n")
    (r / "src" / "min.js").write_text("var a=1;" * 200 + "hello_world();" + "var b=2;" * 200)
    (r / "node_modules" / "lib" / "index.js").write_text("hello_world()\n")
    (r / "build" / "out.py").write_text("hello_world()\n")
    (r / "debug.log").write_text("hello_world\n")
    (r / ".hidden" / "secret.py").write_text("hello_world\n")
    (r / "文档" / "说明.txt").write_bytes("第一行\n你好，世界\n第三行\n".encode("gbk"))
    (r / "文档" / "utf8.md").write_text("# 标题\n你好，世界\n", encoding="utf-8")
    (r / "big.txt").write_text("".join(f"line {i}\n" for i in range(1, 1001)))
    (r / "bin.dat").write_bytes(b"\x00\x01\x02hello_world\x00")
    return str(r)


# ---------------------------------------------------------------- paths

def test_normalize_missing_path():
    with pytest.raises(S.SearchError):
        S.normalize_path("/definitely/not/here/xyz")


def test_normalize_empty_requires_root(monkeypatch):
    monkeypatch.delenv("FASTSEARCH_DEFAULT_ROOT", raising=False)
    with pytest.raises(S.SearchError):
        S.normalize_path("")


def test_legacy_allowed_roots_does_not_restrict_access(proj, monkeypatch):
    monkeypatch.setenv("FASTSEARCH_ALLOWED_ROOTS", os.path.join(proj, "src"))
    assert S.normalize_path(os.path.join(proj, "src", "pkg"))
    assert S.normalize_path(proj) == os.path.normpath(proj)
    assert "hello_world" in S.read_lines(os.path.join(proj, "src", "main.py"))


def test_quoted_path(proj):
    assert S.normalize_path(f'"{proj}"') == os.path.normpath(proj)


# ---------------------------------------------------------------- find_files

def test_find_glob(proj):
    out = S.find_files(proj, "*.py")
    assert "main.py" in out and "util.py" in out
    assert "node_modules" not in out          # default exclude
    assert "out.py" not in out                # .gitignore (non-git dir!)
    assert "secret.py" not in out             # hidden


def test_find_hidden_and_no_ignore(proj):
    out = S.find_files(proj, "*.py", hidden=True, no_ignore=True)
    for name in ("secret.py", "out.py", "main.py"):
        assert name in out


def test_find_extensions_relative(proj):
    out = S.find_files(proj, extensions=["ts", ".js"], relative=True)
    assert "src/app.ts" in out and "src/min.js" in out


def test_find_directory_marker(proj):
    out = S.find_files(proj, "pkg", file_type="directory", relative=True)
    assert "src/pkg/" in out


def test_find_unicode(proj):
    out = S.find_files(proj, "*说明*")
    assert "说明.txt" in out


def test_find_truncation(proj):
    out = S.find_files(proj, max_results=2)
    assert "TRUNCATED" in out and out.startswith("2 result")


def test_find_full_path_glob(proj):
    out = S.find_files(proj, "**/pkg/*.py", full_path=True, relative=True)
    assert "src/pkg/util.py" in out and "main.py" not in out
    assert 'src/pkg/util.py' in S.find_files(proj, 'src/pkg/*.py', full_path=True, relative=True)
    direct = S.find_files(proj, 'src/*.py', full_path=True, relative=True)
    assert 'src/main.py' in direct and 'src/pkg/util.py' not in direct


# ---------------------------------------------------------------- search_text

def test_search_basic(proj):
    out = S.search_text("hello_world", proj, relative=True)
    assert "src/main.py" in out and "4: def hello_world():" in out
    assert "node_modules" not in out and "build/out.py" not in out and "debug.log" not in out
    assert "bin.dat" not in out


def test_search_context_and_separator(proj):
    out = S.search_text("def hello_world", os.path.join(proj, "src", "main.py"), context=1)
    assert "3- " in out and "4: def hello_world():" in out and "5-     return" in out


def test_search_crlf_dollar(proj):
    out = S.search_text(r"\{\}$", proj, include=["*.ts"])
    assert "app.ts" in out and "\r" not in out


def test_search_long_line_trimmed(proj):
    out = S.search_text("hello_world", proj, include=["*.js"], max_line_length=60)
    line = [l for l in out.splitlines() if "hello_world" in l][0]
    assert len(line) < 140 and "chars]" in line


def test_search_max_results(proj):
    out = S.search_text("hello_world", proj, max_results=1, context=2)
    assert "TRUNCATED" in out and out.startswith("1 match(es) in 1 file(s)")
    # exactly one file block, no orphan headers / dangling context
    blocks = [b for b in out.split("\n\n")[1:] if b.strip()]
    assert len(blocks) == 1 and blocks[0].count(": ") >= 1


def test_search_gbk(proj):
    assert "No matches" in S.search_text("你好", os.path.join(proj, "文档", "说明.txt"))
    out = S.search_text("你好", os.path.join(proj, "文档", "说明.txt"), encoding="gbk")
    assert "2: 你好，世界" in out


def test_search_literal(proj):
    # as a regex "()" is an empty group and would match every hello_world
    out = S.search_text("hello_world();", proj, literal=True, relative=True)
    assert "src/min.js" in out and "src/main.py" not in out and "util.py" not in out


def test_search_bad_regex_falls_back_to_literal(proj):
    out = S.search_text("hello_world(|def helper(", proj, relative=True)
    assert out.startswith("NOTE: invalid regex; searched literally for: hello_world( | def helper(")
    assert "src/pkg/util.py" in out and "1: def helper():" in out
    assert "No matches." in S.search_text("(unclosed", proj)


# Distinct patterns that failed with "regex parse error" in real usage records.
HISTORICAL_BAD_REGEX = [
    'Resources.|Addressables.|AddressableLoader|AssetReference|Instantiate(|Destroy(',
    'playMusic(|bgmList|bgm_list',
    'buy|Buy|unlock|Unlock|deer|Deer|gift|Gift|start(|onLoad',
    'Awake|Start(|Init|idle',
    'OnDestroy|OnDisable|SaveManualCakeState|RestoreManual|TryHandleActionUpBeforeGravity|Resources.|Addressables.|Instantiate(|Destroy(',
    'OnCdPlaced(|NotifyCdPlaced(|TryResumeWithExistingCd(',
    'm_snapLocalPosition:|m_spinPivot:|m_Name: gy_CD1|m_LocalPosition: {x: 0, y: -0.55',
    'Resources.|Addressable|AssetReference|AssetDatabase|Instantiate(|Destroy(',
    'ActionUp|TryHandleManualKitchenInteractions(',
    'fastsearch|D:/MCP|D:\\MCP',
    'chukou|setParent(.*guizi|case "box"|case \'box\'',
    'node_down|nodeDown|node_down(|zIndex',
    'ScanScene(|struct PersistentIDAssignReport|class PersistentIDAssignReport',
    'Awake|Start(|OnEnable|IsEgg|TryGetEgg|Cache|Init|human',
    'DirectResultNode|Find.*human|OnEnable|Awake|Start(|GetChild|Character',
    'humanObjects[',
    'Resources.|Addressables.|AddressableLoader|AssetDatabase|Instantiate(',
    'range_light_points*(|fire_fades*(',
    'm_EnabledMovement|EggHatched?.Invoke|RestoreCamera(',
    'lanzi_event(',
    'm_TargetToggleObject|m_CabinetParticle|Toggle(',
    'Resources.|Addressables.|AddressableLoader|AssetReference|Instantiate(',
    '^s*(static )?create_Smoke(',
    'BeginRipenFromClick|PlaySmoke(',
    'SetupLikeParticles(',
    'Resources.|Addressables.|Instantiate(|Destroy(',
]


def test_historical_bad_regex_replay(tmp_path):
    path = tmp_path / 'Sample.cs'
    path.write_text('void Start() { Instantiate(prefab); }\nvar p = D:\\MCP;\nm_LocalPosition: {x: 0, y: -0.55}\n')
    for pattern in HISTORICAL_BAD_REGEX:
        assert S.search_text(pattern, str(path)).startswith('NOTE: invalid regex'), pattern
    assert '1: void Start()' in S.search_text('Awake|Start(|Init|idle', str(path))
    assert '2: var p' in S.search_text('fastsearch|D:/MCP|D:\\MCP', str(path))
    assert '3: m_LocalPosition' in S.search_text(HISTORICAL_BAD_REGEX[6], str(path))


def test_search_multiline(proj):
    out = S.search_text(r"class Foo:\r?\n\s+pass", proj, multiline=True)
    assert "8: class Foo:" in out and "9:     pass" in out


@pytest.mark.parametrize('newline', [bytes([10]), bytes([13, 10])])
def test_multiline_line_endings(tmp_path, newline):
    path = tmp_path / 'text.txt'
    path.write_bytes(newline.join([b'class Foo:', b'    pass']))
    out = S.search_text('class Foo:' + chr(92) + 'r?' + chr(92) + 'n' + chr(92) + 's+pass', str(path), multiline=True)
    assert '1: class Foo:' in out and '2:     pass' in out


def test_search_files_mode(proj):
    out = S.search_text('hello_world', proj, output='files', include=['*.py'], relative=True)
    assert out.count('src/pkg/util.py') == 1
    assert 'src/main.py' in out and 'node_modules' not in out
    assert 'TRUNCATED' in S.search_text('hello_world', proj, output='files', max_results=1)
    assert '0 matching file(s)' in S.search_text('not-present-anywhere', proj, output='files')
    out = S.search_text('hello_world(|missing(', proj, output='files', include=['*.py'], relative=True)
    assert out.startswith('NOTE: invalid regex') and 'src/pkg/util.py' in out


@pytest.mark.parametrize('output', ['content', 'files'])
def test_search_output_budget(tmp_path, output):
    for i in range(30):
        (tmp_path / (str(i) + 'x' * 80 + '.txt')).write_text(('needle ' + 'x' * 200 + chr(10)) * 30)
    out = S.search_text('needle', str(tmp_path), output=output, context=10, max_output_chars=1024)
    assert len(out) <= 1024 and 'TRUNCATED' in out


def test_fast_read_stops_after_lookahead(proj, monkeypatch):
    import builtins
    real_open = builtins.open
    visited = []

    class TrackedFile:
        def __init__(self, file):
            self.file = file
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.file.close()
        def __iter__(self):
            for line in self.file:
                visited.append(line)
                yield line

    def tracked_open(*args, **kwargs):
        file = real_open(*args, **kwargs)
        return TrackedFile(file) if len(args) > 1 and args[1] == 'r' else file

    monkeypatch.setattr(builtins, 'open', tracked_open)
    out = S.read_lines(os.path.join(proj, 'big.txt'), 10, 12, count_total=False)
    assert len(visited) == 13
    assert 'has_more=true' in out and 'start=13' in out and 'of 1000' not in out


def test_fast_read_eof_and_encoding(proj):
    path = os.path.join(proj, 'big.txt')
    assert 'of 1000' in S.read_lines(path, 999, 1001, count_total=False)
    assert 'past end' in S.read_lines(path, 2000, count_total=False)
    assert '你好' in S.read_lines(os.path.join(proj, '文档', '说明.txt'), 2, 2, count_total=False)


# ---------------------------------------------------------------- count_matches

def test_count(proj):
    out = S.count_matches("hello_world", proj, relative=True)
    first = out.splitlines()[1]
    assert first.split()[0] == "2" and first.endswith("src/pkg/util.py")
    assert "node_modules" not in out


@pytest.mark.skipif(sys.platform != "win32", reason="exclusive file lock via CreateFileW")
def test_unreadable_file_marks_results_partial(tmp_path):
    import ctypes
    from ctypes import wintypes

    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text("needle\n")
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    # GENERIC_READ with no sharing: rg cannot open b.txt but still matches a.txt.
    handle = k32.CreateFileW(str(tmp_path / "b.txt"), 0x80000000, 0, None, 3, 0x80, None)
    try:
        for out in (S.search_text("needle", str(tmp_path)),
                    S.search_text("needle", str(tmp_path), output="files"),
                    S.count_matches("needle", str(tmp_path))):
            head = out.splitlines()[0]
            assert "1 file" in head or "1 matching file" in head
            assert S.RG_PARTIAL.strip() in head
    finally:
        k32.CloseHandle(handle)


# ---------------------------------------------------------------- read_lines

def test_read_range(proj):
    out = S.read_lines(os.path.join(proj, "big.txt"), 10, 12)
    assert "[lines 10-12 of 1000" in out and "line 11" in out and "line 13" not in out
    assert "\n10\tline 10\n" in out  # unpadded line numbers
    assert "start=13" in out


def test_read_gbk_autodetect(proj):
    out = S.read_lines(os.path.join(proj, "文档", "说明.txt"))
    assert "你好，世界" in out and "gb18030" in out


def test_read_binary_refused(proj):
    with pytest.raises(S.SearchError, match="binary"):
        S.read_lines(os.path.join(proj, "bin.dat"))


def test_read_past_end(proj):
    assert "past end" in S.read_lines(os.path.join(proj, "big.txt"), 5000)


# ---------------------------------------------------------------- tree

def test_tree(proj):
    out = S.tree(proj, max_depth=2)
    assert "src/" in out and "pkg/" in out and "文档/" in out
    assert "node_modules" not in out and "build" not in out
    assert out.strip().splitlines()[-1].startswith(tuple("0123456789"))


def test_tree_per_dir_limit(proj):
    out = S.tree(proj, max_depth=1, per_dir_limit=2)
    assert "more)" in out


# ---------------------------------------------------------------- MCP end-to-end

def test_mcp_stdio_roundtrip(proj):
    """Spawn the real server over stdio and call every tool through an MCP client."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def go():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "fastsearch_mcp"], env=dict(os.environ)
        )
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                definitions = (await s.list_tools()).tools
                assert all(t.description.count('MUST use') == 1 and len(t.description) < 1000 for t in definitions)
                tools = {t.name for t in definitions}
                assert tools == {"find_files", "search_text", "count_matches", "read_lines", "tree", "decompile"}
                res = await s.call_tool("search_text", {"pattern": "hello_world", "path": proj, "context": 1})
                text = res.content[0].text
                assert not res.model_dump(by_alias=True)["isError"]
                assert "main.py" in text
                files = await s.call_tool('search_text', {'pattern': 'hello_world', 'path': proj, 'output': 'files', 'max_output_chars': 1024})
                assert not files.model_dump(by_alias=True)['isError'] and 'matching file(s)' in files.content[0].text
                fast = await s.call_tool('read_lines', {'path': os.path.join(proj, 'big.txt'), 'start': 10, 'end': 12, 'count_total': False})
                assert not fast.model_dump(by_alias=True)['isError'] and 'has_more=true' in fast.content[0].text
                res = await s.call_tool("read_lines", {"path": os.path.join(proj, "nope.txt")})
                assert res.model_dump(by_alias=True)["isError"]
                assert "ERROR [path_missing]" in res.content[0].text
                import sqlite3
                import json
                from fastsearch_mcp.telemetry import db_path
                with sqlite3.connect(db_path()) as db:
                    records = [json.loads(row[0]) for row in db.execute('SELECT data FROM calls')]
                assert len(records) == 4
                assert records[0]['tool'] == 'search_text'
                assert records[3]['error_code'] == 'path_missing'
                return text

    print(asyncio.run(go()))
