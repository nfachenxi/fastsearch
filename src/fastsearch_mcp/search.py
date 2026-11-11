"""Core search logic: thin, safe wrappers around fd and rg.

Kept independent from the MCP layer so it can be unit-tested and reused.
"""

from __future__ import annotations

import base64
import fnmatch
import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Callable, Iterable

from .binaries import IS_WINDOWS, get_binary

try:
    from . import telemetry as T
except ImportError:  # the search-only build ships without usage records
    T = SimpleNamespace(update=lambda **_: None, limit=lambda _reason: None)

# --------------------------------------------------------------------------- config

DEFAULT_EXCLUDES = [
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
    ".pytest_cache", ".tox", ".idea", ".vs", ".gradle", ".next", ".nuxt",
]


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None:
        return list(default)
    return [x.strip() for x in raw.split(",") if x.strip()]


def default_excludes() -> list[str]:
    return _env_list("FASTSEARCH_DEFAULT_EXCLUDES", DEFAULT_EXCLUDES)


def default_timeout() -> float:
    try:
        return float(os.environ.get("FASTSEARCH_TIMEOUT", "30"))
    except ValueError:
        return 30.0


class SearchError(Exception):
    """User-facing error (bad path, bad regex, ...)."""

    def __init__(self, message, code="search_error"):
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------- paths

_MSYS_DRIVE = re.compile(r"^/(?:mnt/|cygdrive/)?([a-zA-Z])(?:/|$)")


def normalize_path(p: str | None) -> str:
    """Turn whatever the agent sends into an absolute native path.

    Handles quotes, ~, Git-Bash/MSYS (/c/Users), WSL (/mnt/c/...) and cygwin
    style paths on Windows, and FASTSEARCH_DEFAULT_ROOT for empty/relative paths.
    """
    p = (p or "").strip().strip('"').strip("'").strip()
    root = os.environ.get("FASTSEARCH_DEFAULT_ROOT", "").strip()
    if not p:
        if not root:
            raise SearchError(
                "`path` is required (absolute path recommended). "
                "Set FASTSEARCH_DEFAULT_ROOT to allow omitting it."
            )
        p = root
    p = os.path.expanduser(os.path.expandvars(p))
    if IS_WINDOWS:
        m = _MSYS_DRIVE.match(p)
        if m:
            p = m.group(1).upper() + ":\\" + p[m.end():]
        if re.fullmatch(r"[a-zA-Z]:", p):  # "C:" means cwd-of-drive on Windows; user means root
            p += "\\"
    if not os.path.isabs(p):
        p = os.path.join(root or os.getcwd(), p)
    p = os.path.normpath(os.path.abspath(p))
    T.update(normalized_path=p)
    if not os.path.exists(p):
        raise SearchError(f"Path does not exist: {p}", "path_missing")
    return p


def _clean_rel(s: str) -> str:
    if s.startswith("./") or s.startswith(".\\"):
        s = s[2:]
    return s


# --------------------------------------------------------------------------- process

@dataclass
class RunResult:
    returncode: int | None
    stderr: str
    timed_out: bool = False
    stopped_early: bool = False


def run_streaming(
    args: list[str],
    on_record: Callable[[bytes], bool],
    *,
    cwd: str | None = None,
    sep: bytes = b"\n",
    timeout: float | None = None,
) -> RunResult:
    """Run a command, feeding each `sep`-delimited record to on_record.

    on_record returns False to stop early (process is killed). Blocking: call it
    from a worker thread. Uses plain threads instead of asyncio subprocesses so it
    works under any event loop on Windows.
    """
    started = time.perf_counter()
    T.update(engine=os.path.basename(args[0]))
    timeout = default_timeout() if timeout is None else timeout
    kwargs = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW: no console flashes
    try:
        proc = subprocess.Popen(
            args, cwd=cwd, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs,
        )
    except OSError as e:
        raise SearchError(f"Failed to start {args[0]}: {e}") from e

    err_buf = bytearray()

    def drain_stderr():
        assert proc.stderr is not None
        for chunk in iter(lambda: proc.stderr.read(8192), b""):
            if len(err_buf) < 8192:
                err_buf.extend(chunk[: 8192 - len(err_buf)])

    t_err = threading.Thread(target=drain_stderr, daemon=True)
    t_err.start()

    state = {"timed_out": False}

    def on_timeout():
        state["timed_out"] = True
        _kill(proc)

    timer = threading.Timer(timeout, on_timeout)
    timer.daemon = True
    timer.start()

    stopped = False
    buf = b""
    assert proc.stdout is not None
    try:
        while True:
            chunk = proc.stdout.read1(65536)
            if not chunk:
                break
            buf += chunk
            *records, buf = buf.split(sep)
            for rec in records:
                if not on_record(rec):
                    stopped = True
                    break
            if stopped:
                break
        if not stopped and buf:
            if not on_record(buf):
                stopped = True
    finally:
        timer.cancel()
        if stopped:
            _kill(proc)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _kill(proc)
            proc.wait()
        t_err.join(timeout=2)

    T.update(engine_duration_ms=(time.perf_counter() - started) * 1000,
             returncode=proc.returncode, timed_out=state["timed_out"],
             stopped_early=stopped, scan_incomplete=state["timed_out"] or stopped)
    if proc.returncode not in (0, 1, None) and not stopped and not state["timed_out"]:
        T.update(status="warning", scan_incomplete=True, warning=err_buf.decode("utf-8", "replace")[:2000])
    return RunResult(
        returncode=proc.returncode,
        stderr=err_buf.decode("utf-8", "replace").strip(),
        timed_out=state["timed_out"],
        stopped_early=stopped,
    )


def _kill(proc: subprocess.Popen) -> None:
    try:
        proc.kill()
    except OSError:
        pass


RG_PARTIAL = " (WARNING: rg reported errors; results are partial)"


def _stderr_hint(res: RunResult) -> str:
    if not res.stderr:
        return ""
    lines = res.stderr.splitlines()
    head = "\n".join(lines[:8])
    more = f"\n... ({len(lines) - 8} more stderr lines)" if len(lines) > 8 else ""
    return f"\n[stderr]\n{head}{more}"


# --------------------------------------------------------------------------- find_files (fd)

def find_files(
    path: str,
    pattern: str = "",
    *,
    glob: bool = True,
    full_path: bool = False,
    extensions: Iterable[str] | None = None,
    file_type: str | None = None,
    max_depth: int | None = None,
    hidden: bool = False,
    no_ignore: bool = False,
    exclude: Iterable[str] | None = None,
    case_sensitive: bool | None = None,
    changed_within: str | None = None,
    min_size: str | None = None,
    max_size: str | None = None,
    max_results: int = 200,
    relative: bool = False,
) -> str:
    root = normalize_path(path)
    if not os.path.isdir(root):
        raise SearchError(f"find_files needs a directory, got a file: {root}")
    max_results = max(1, min(int(max_results), 10000))

    args = [get_binary("fd"), "--color", "never", "--print0", "--no-require-git",
            "--base-directory", root, "--max-results", str(max_results + 1)]
    if glob and full_path and IS_WINDOWS and '/' in pattern:
        # fd's Windows full-path glob does not treat '/' as a separator.
        parts = pattern.split('/')
        translated = []
        separator = '[' + re.escape('/' + chr(92)) + ']'
        component = '[^' + re.escape('/' + chr(92)) + ']'
        for i, part in enumerate(parts):
            if part == '**':
                translated.append('(?:' + component + '+' + separator + ')*' if i < len(parts) - 1 else '.*')
            else:
                translated.append(fnmatch.translate(part)[4:-3].replace('(?>', '(?:').replace('.*', component + '*'))
                if i < len(parts) - 1:
                    translated.append(separator)
        pattern = '(?:^|' + separator + ')' + ''.join(translated) + '$'
        glob = False
    if glob:
        args.append("--glob")
    if full_path:
        args.append("--full-path")
    if case_sensitive is True:
        args.append("--case-sensitive")
    elif case_sensitive is False:
        args.append("--ignore-case")
    for ext in extensions or []:
        ext = ext.strip().lstrip("*").lstrip(".")
        if ext:
            args += ["--extension", ext]
    if file_type:
        ft = {"file": "f", "f": "f", "dir": "d", "directory": "d", "d": "d",
              "symlink": "l", "l": "l", "executable": "x", "x": "x", "empty": "e", "e": "e"}.get(file_type.lower())
        if not ft:
            raise SearchError("file_type must be one of: file, directory, symlink, executable, empty")
        args += ["--type", ft]
    if max_depth is not None:
        args += ["--max-depth", str(int(max_depth))]
    if hidden:
        args.append("--hidden")
    if no_ignore:
        args.append("--no-ignore")
    else:
        for ex in default_excludes():
            args += ["--exclude", ex]
    for ex in exclude or []:
        args += ["--exclude", ex]
    if changed_within:
        args += ["--changed-within", changed_within]
    if min_size:
        args += ["--size", "+" + min_size.lstrip("+")]
    if max_size:
        args += ["--size", "-" + max_size.lstrip("-")]
    args.append("--")
    if pattern:
        args.append(pattern)

    out: list[str] = []

    def on_rec(rec: bytes) -> bool:
        if rec:
            out.append(_clean_rel(rec.decode("utf-8", "replace")))
        return len(out) <= max_results

    res = run_streaming(args, on_rec, sep=b"\0")
    if res.returncode not in (0, None) and not out and not res.stopped_early and not res.timed_out:
        raise SearchError(f"fd failed (exit {res.returncode}).{_stderr_hint(res)}")

    truncated = len(out) > max_results
    T.update(result_count=min(len(out), max_results), result_unit="entries")
    if truncated:
        T.limit("max_results")
    out = sorted(out[:max_results], key=lambda s: s.lower())

    lines = []
    for rel in out:
        rel = rel.rstrip("/\\")
        abs_p = os.path.normpath(os.path.join(root, rel))
        shown = rel.replace("\\", "/") if relative else abs_p
        if os.path.isdir(abs_p):
            shown += "/" if relative else os.sep
        lines.append(shown)

    head = f"{len(lines)} result(s) under {root}"
    if truncated:
        head += f" (TRUNCATED at max_results={max_results}; refine pattern/path or raise max_results)"
    if res.timed_out:
        head += " (TIMED OUT; results are partial)"
    if not lines:
        return head + "\nNo matches." + _stderr_hint(res)
    return head + "\n" + "\n".join(lines)


# --------------------------------------------------------------------------- rg helpers

def _rg_text(obj: dict | None) -> str:
    if not obj:
        return ""
    if "text" in obj:
        return obj["text"]
    raw = base64.b64decode(obj.get("bytes", ""))
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _rg_common_args(
    *,
    literal: bool,
    case_sensitive: bool | None,
    word: bool,
    include: Iterable[str] | None,
    exclude: Iterable[str] | None,
    file_types: Iterable[str] | None,
    hidden: bool,
    no_ignore: bool,
    encoding: str | None,
    multiline: bool = False,
    max_filesize: str | None = None,
) -> list[str]:
    args = ["--no-config", "--color", "never", "--no-require-git", "--crlf"]
    if literal:
        args.append("--fixed-strings")
    if case_sensitive is True:
        args.append("--case-sensitive")
    elif case_sensitive is False:
        args.append("--ignore-case")
    else:
        args.append("--smart-case")
    if word:
        args.append("--word-regexp")
    if multiline:
        args += ["--multiline", "--multiline-dotall"]
    for g in include or []:
        args += ["--glob", g]
    for g in exclude or []:
        args += ["--glob", "!" + g.lstrip("!")]
    for t in file_types or []:
        args += ["--type", t]
    if hidden:
        args.append("--hidden")
    if no_ignore:
        args.append("--no-ignore")
    else:
        for ex in default_excludes():
            args += ["--glob", f"!**/{ex}/**", "--glob", f"!{ex}"]
    if encoding:
        args += ["--encoding", encoding]
    if max_filesize:
        args += ["--max-filesize", max_filesize]
    return args


def _search_target(path: str) -> tuple[str, str, str]:
    """Return (root_dir_for_relative, cwd, rg_path_arg)."""
    p = normalize_path(path)
    if os.path.isdir(p):
        return p, p, p
    parent = os.path.dirname(p)
    return parent, parent, p


def _display_path(p: str, root: str, relative: bool) -> str:
    if not relative:
        return os.path.normpath(p)
    try:
        return os.path.relpath(p, root).replace("\\", "/")
    except ValueError:
        return p


def _truncate_line(text: str, start_char: int | None, width: int) -> str:
    if width <= 0 or len(text) <= width:
        return text
    T.limit("long_line")
    if start_char is None:
        return text[:width] + f" …[+{len(text) - width} chars]"
    left = max(0, start_char - width // 3)
    right = min(len(text), left + width)
    left = max(0, right - width)
    pre = f"[…{left} chars] " if left else ""
    post = f" […{len(text) - right} chars]" if right < len(text) else ""
    return pre + text[left:right] + post


def _literal_fallback(args: list[str], res: RunResult, literal: bool) -> str:
    """On an rg regex parse error, swap the pattern (args[-3]) for its literal `|` parts.

    Agents often write `Start(|Init` meaning literal names. Returns a NOTE line, or "" if not applicable.
    """
    if literal or res.returncode != 2 or "regex parse error" not in res.stderr:
        return ""
    alts = [a for a in args[-3].split("|") if a] or [args[-3]]
    args[-3] = "|".join(map(re.escape, alts))
    T.update(regex_fallback=True)
    return "NOTE: invalid regex; searched literally for: " + " | ".join(alts) + chr(10)


# --------------------------------------------------------------------------- search_text (rg --json)

@dataclass
class _FileHits:
    path: str
    lines: dict[int, tuple[str, bool]] = field(default_factory=dict)  # line -> (text, is_match)
    n_matches: int = 0


def search_text(
    pattern: str,
    path: str,
    *,
    literal: bool = False,
    case_sensitive: bool | None = None,
    word: bool = False,
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
    file_types: Iterable[str] | None = None,
    context: int = 0,
    before: int | None = None,
    after: int | None = None,
    max_results: int = 100,
    max_per_file: int | None = None,
    hidden: bool = False,
    no_ignore: bool = False,
    multiline: bool = False,
    encoding: str | None = None,
    max_line_length: int = 300,
    max_filesize: str | None = "20M",
    relative: bool = False,
    output: str = "content",
    max_output_chars: int = 24000,
) -> str:
    if not pattern:
        raise SearchError("pattern must not be empty")
    if output not in ("content", "files"):
        raise SearchError("output must be content or files")
    if not 1024 <= max_output_chars <= 1000000:
        raise SearchError("max_output_chars must be between 1024 and 1000000")

    def bounded(text):
        if len(text) <= max_output_chars:
            return text
        T.limit("max_output_chars")
        notice = chr(10) + "(TRUNCATED: max_output_chars; narrow scope or raise the budget)"
        return text[:max_output_chars - len(notice)] + notice

    root, cwd, target = _search_target(path)
    max_results = max(1, min(int(max_results), 5000))
    b = context if before is None else before
    a = context if after is None else after
    b, a = max(0, min(int(b), 50)), max(0, min(int(a), 50))

    args = [get_binary("rg"), "--json"]
    args += _rg_common_args(
        literal=literal, case_sensitive=case_sensitive, word=word, include=include,
        exclude=exclude, file_types=file_types, hidden=hidden, no_ignore=no_ignore,
        encoding=encoding, multiline=multiline, max_filesize=max_filesize,
    )
    if output == "files":
        args.remove("--json")
        args += ["--files-with-matches", "--null", "--regexp", pattern, "--", target]
        paths = []
        used = 0
        limited = None

        def on_path(rec):
            nonlocal used, limited
            if not rec:
                return True
            shown = _display_path(rec.decode("utf-8", "replace"), root, relative)
            if len(paths) >= max_results:
                limited = "max_results"
                return False
            if used + len(shown) + 1 > max_output_chars - 512:
                limited = "max_output_chars"
                return False
            paths.append(shown)
            used += len(shown) + 1
            return True

        res = run_streaming(args, on_path, cwd=cwd, sep=bytes([0]))
        note = "" if paths else _literal_fallback(args, res, literal)
        if note:
            res = run_streaming(args, on_path, cwd=cwd, sep=bytes([0]))
        if res.returncode == 2 and not paths and not res.stopped_early:
            raise SearchError(f"rg error.{_stderr_hint(res)}")
        T.update(result_count=len(paths), result_unit="files", matched_files=len(paths))
        if limited:
            T.limit(limited)
        head = f"{note}{len(paths)} matching file(s)"
        if limited:
            head += f" (TRUNCATED: {limited}; narrow path/include or raise the limit)"
        if res.timed_out:
            head += " (TIMED OUT; results are partial)"
        if res.returncode == 2:
            head += RG_PARTIAL
        return bounded(head + chr(10) + (chr(10).join(paths) if paths else "No paths returned."))
    if b:
        args += ["--before-context", str(b)]
    if a:
        args += ["--after-context", str(a)]
    if max_per_file:
        args += ["--max-count", str(int(max_per_file))]
    args += ["--regexp", pattern, "--", target]

    files: dict[str, _FileHits] = {}
    order: list[str] = []
    total = {"matches": 0, "truncated": False}
    used_chars = 0
    budget_limited = False
    body_budget = max(0, max_output_chars - len(target) - 512)

    def on_rec(rec: bytes) -> bool:
        nonlocal used_chars, budget_limited
        if not rec:
            return True
        try:
            ev = json.loads(rec)
        except ValueError:
            return True
        kind = ev.get("type")
        if kind not in ("match", "context"):
            return True
        d = ev["data"]
        is_match = kind == "match"
        if is_match and total["matches"] >= max_results:
            total["truncated"] = True
            return False
        p = _rg_text(d.get("path"))
        fh = files.get(p)
        if fh is None:
            used_chars += len(_display_path(p, root, relative)) + 2
            fh = files[p] = _FileHits(p)
            order.append(p)
        text = _rg_text(d.get("lines"))
        ln = d.get("line_number") or 0
        start_char = None
        subs = d.get("submatches") or []
        if subs and "text" in (d.get("lines") or {}):
            start_char = len(text.encode("utf-8")[: subs[0]["start"]].decode("utf-8", "ignore"))
        for i, piece in enumerate(text.splitlines() or [""]):
            piece = piece.rstrip("\r")
            sc = start_char if i == 0 else None
            prev = fh.lines.get(ln + i)
            if prev and prev[1]:
                continue  # never downgrade a match line to context
            rendered = _truncate_line(piece, sc, max_line_length)
            cost = len(rendered) + len(str(ln + i)) + 10
            if used_chars + cost > body_budget:
                budget_limited = True
                return False
            fh.lines[ln + i] = (rendered, is_match)
            used_chars += cost
        if is_match:
            total["matches"] += 1
            fh.n_matches += 1
        return True

    res = run_streaming(args, on_rec, cwd=cwd)
    note = "" if files else _literal_fallback(args, res, literal)
    if note:
        res = run_streaming(args, on_rec, cwd=cwd)
    if res.returncode == 2 and not files and not res.stopped_early:
        raise SearchError(f"rg error.{_stderr_hint(res)}")

    n_files = sum(1 for p in order if files[p].n_matches)
    T.update(result_count=total["matches"], result_unit="match_events", matched_files=n_files)
    if total["truncated"]:
        T.limit("max_results")
    if max_per_file:
        T.update(per_file_limit=max_per_file)
        T.limit("max_per_file")
    head = f"{note}{total['matches']} match(es) in {n_files} file(s) under {target}"
    if total["truncated"]:
        head += (f" (TRUNCATED at max_results={max_results}; use count_matches to see the "
                 "distribution, then narrow path/include)")
    if res.timed_out:
        head += " (TIMED OUT; results are partial)"
    if budget_limited:
        T.limit("max_output_chars")
        head += " (TRUNCATED: max_output_chars; narrow path/include/context or raise the budget)"
    if max_per_file:
        head += f" (per-file cap={max_per_file}; additional matches may be omitted)"
    if res.returncode == 2 and n_files:
        # rg exits 2 when some files could not be read even though others matched;
        # say so up front, because the stderr tail below may be cut by the budget.
        head += RG_PARTIAL
    if not n_files:
        message = "No matches returned." if budget_limited or res.timed_out else "No matches."
        return bounded(head + chr(10) + message + (_stderr_hint(res) if res.returncode == 2 else ""))

    out = [head]
    for p in order:
        fh = files[p]
        if not fh.n_matches:
            continue  # only before-context of a match that was cut off
        match_lns = [ln for ln, (_, m) in fh.lines.items() if m]
        out.append("")
        out.append(_display_path(p, root, relative))
        prev_ln = None
        for ln in sorted(fh.lines):
            text, is_match = fh.lines[ln]
            # drop dangling context that belonged to a match cut by max_results
            if not is_match and not any(m - b <= ln <= m + a for m in match_lns):
                continue
            if prev_ln is not None and ln > prev_ln + 1:
                out.append("  --")
            out.append(f"  {ln}{':' if is_match else '-'} {text}")
            prev_ln = ln
    if res.returncode == 2 and res.stderr:
        out.append(_stderr_hint(res))
    return bounded(chr(10).join(out))


# --------------------------------------------------------------------------- count_matches

def count_matches(
    pattern: str,
    path: str,
    *,
    literal: bool = False,
    case_sensitive: bool | None = None,
    word: bool = False,
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
    file_types: Iterable[str] | None = None,
    hidden: bool = False,
    no_ignore: bool = False,
    encoding: str | None = None,
    max_files: int = 50,
    relative: bool = False,
) -> str:
    if not pattern:
        raise SearchError("pattern must not be empty")
    root, cwd, target = _search_target(path)
    args = [get_binary("rg"), "--count-matches", "--with-filename", "--null"]
    args += _rg_common_args(
        literal=literal, case_sensitive=case_sensitive, word=word, include=include,
        exclude=exclude, file_types=file_types, hidden=hidden, no_ignore=no_ignore,
        encoding=encoding,
    )
    args += ["--regexp", pattern, "--", target]

    counts: list[tuple[str, int]] = []

    def on_rec(rec: bytes) -> bool:
        rec = rec.rstrip(b"\r")
        if b"\0" in rec:
            p, _, n = rec.rpartition(b"\0")
            try:
                counts.append((p.decode("utf-8", "replace"), int(n)))
            except ValueError:
                pass
        return True

    res = run_streaming(args, on_rec, cwd=cwd)
    if res.returncode == 2 and not counts:
        raise SearchError(f"rg error.{_stderr_hint(res)}")

    counts.sort(key=lambda x: (-x[1], x[0].lower()))
    total = sum(n for _, n in counts)
    T.update(result_count=total, result_unit="occurrences", matched_files=len(counts))
    max_files = max(1, int(max_files))
    head = f"{total} match(es) in {len(counts)} file(s) under {target}"
    if res.timed_out:
        head += " (TIMED OUT; counts are partial)"
    if res.returncode == 2:
        head += RG_PARTIAL + _stderr_hint(res)
    if not counts:
        return head + "\nNo matches."
    out = [head]
    width = len(str(counts[0][1]))
    for p, n in counts[:max_files]:
        out.append(f"{n:>{width}}  {_display_path(p, root, relative)}")
    if len(counts) > max_files:
        T.limit("max_files")
        out.append(f"... and {len(counts) - max_files} more file(s) "
                   f"({sum(n for _, n in counts[max_files:])} matches)")
    return "\n".join(out)


# --------------------------------------------------------------------------- read_lines

_BOMS = [
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
]


def detect_encoding(sample: bytes) -> str:
    for bom, enc in _BOMS:
        if sample.startswith(bom):
            return enc
    if b"\0" in sample[:8192]:
        return "binary"
    import codecs
    try:
        codecs.getincrementaldecoder("utf-8")().decode(sample, final=False)
        return "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        codecs.getincrementaldecoder("gb18030")().decode(sample, final=False)
        return "gb18030"
    except UnicodeDecodeError:
        return "latin-1"


def read_lines(
    path: str,
    start: int = 1,
    end: int | None = None,
    *,
    max_lines: int = 200,
    encoding: str | None = None,
    max_line_length: int = 2000,
    count_total: bool = True,
) -> str:
    p = normalize_path(path)
    if os.path.isdir(p):
        raise SearchError(f"{p} is a directory; use tree or find_files")
    max_lines = max(1, min(int(max_lines), 2000))
    start = max(1, int(start))
    if end is None or int(end) < start:
        end = start + max_lines - 1
    end = min(int(end), start + max_lines - 1)

    with open(p, "rb") as fh:
        sample = fh.read(65536)
    enc = encoding or detect_encoding(sample)
    T.update(engine="python", effective_encoding=enc, file_bytes=os.path.getsize(p))
    if enc == "binary":
        raise SearchError(f"{p} looks like a binary file (NUL bytes found); pass encoding= to force.")

    out = []
    total = 0
    has_more = False
    with open(p, "r", encoding=enc, errors="replace", newline=None) as fh:
        for total, line in enumerate(fh, 1):
            if not count_total and total > end:
                has_more = True
                break
            if start <= total <= end:
                line = line.rstrip("\r\n")
                if len(line) > max_line_length:
                    T.limit("long_line")
                    line = line[:max_line_length] + f" …[+{len(line) - max_line_length} chars]"
                # Unpadded "N<tab>": padding to a fixed width cost ~2 tokens per line
                # (o200k); the tab still merges with code indentation.
                out.append(f"{total}\t{line}")
    T.update(result_count=len(out), result_unit="lines", total_lines=None if has_more else total,
             has_more=has_more or total > end,
             read_past_end=start > total and total > 0)
    if total == 0:
        return f"{p} (empty file)"
    if start > total:
        return f"{p}: start={start} is past end of file ({total} lines)"
    shown_end = min(end, total)
    if has_more:
        return (f"{p}  [lines {start}-{shown_end}, encoding={enc}, has_more=true]\n"
                + "\n".join(out) + f"\n... (call again with start={shown_end + 1})")
    head = f"{p}  [lines {start}-{shown_end} of {total}, encoding={enc}]"
    tail = ""
    if shown_end < total:
        tail = f"\n... ({total - shown_end} more lines; call again with start={shown_end + 1})"
    return head + "\n" + "\n".join(out) + tail


# --------------------------------------------------------------------------- tree

def tree(
    path: str,
    *,
    max_depth: int = 3,
    hidden: bool = False,
    no_ignore: bool = False,
    dirs_only: bool = False,
    exclude: Iterable[str] | None = None,
    max_entries: int = 400,
    per_dir_limit: int = 40,
) -> str:
    root = normalize_path(path)
    if not os.path.isdir(root):
        raise SearchError(f"tree needs a directory, got a file: {root}")
    max_depth = max(1, min(int(max_depth), 12))
    hard_cap = 50000

    args = [get_binary("fd"), "--color", "never", "--print0", "--no-require-git",
            "--base-directory", root, "--max-depth", str(max_depth)]
    if dirs_only:
        args += ["--type", "d"]
    if hidden:
        args.append("--hidden")
    if no_ignore:
        args.append("--no-ignore")
    else:
        for ex in default_excludes():
            args += ["--exclude", ex]
    for ex in exclude or []:
        args += ["--exclude", ex]

    entries: list[str] = []

    def on_rec(rec: bytes) -> bool:
        if rec:
            entries.append(_clean_rel(rec.decode("utf-8", "replace")).replace("\\", "/").rstrip("/"))
        return len(entries) < hard_cap

    res = run_streaming(args, on_rec, sep=b"\0")
    if res.returncode not in (0, None) and not entries and not res.stopped_early and not res.timed_out:
        raise SearchError(f"fd failed (exit {res.returncode}).{_stderr_hint(res)}")

    # Build nested dict: name -> child dict (None for files)
    node_root: dict = {}
    is_dir: dict[str, bool] = {}
    for rel in entries:
        is_dir[rel] = os.path.isdir(os.path.join(root, rel))
    for rel in sorted(entries):
        parts = rel.split("/")
        cur = node_root
        for i, part in enumerate(parts):
            sub = "/".join(parts[: i + 1])
            if is_dir.get(sub, i < len(parts) - 1):
                cur = cur.setdefault(part, {})
            else:
                cur.setdefault(part, None)

    lines = [root.rstrip("\\/") + os.sep]
    stats = {"dirs": 0, "files": 0, "cut": False}

    def walk(node: dict, prefix: str):
        items = sorted(node.items(), key=lambda kv: (kv[1] is None, kv[0].lower()))
        hidden_n = max(0, len(items) - per_dir_limit)
        items = items[:per_dir_limit]
        for i, (name, child) in enumerate(items):
            if len(lines) > max_entries:
                stats["cut"] = True
                return
            last = i == len(items) - 1 and not hidden_n
            branch = "└── " if last else "├── "
            if child is None:
                stats["files"] += 1
                lines.append(prefix + branch + name)
            else:
                stats["dirs"] += 1
                lines.append(prefix + branch + name + "/")
                walk(child, prefix + ("    " if last else "│   "))
        if hidden_n and len(lines) <= max_entries:
            T.limit("directory_fold")
            lines.append(prefix + f"└── … (+{hidden_n} more)")

    walk(node_root, "")
    foot = f"\n{stats['dirs']} dir(s), {stats['files']} file(s) shown (max_depth={max_depth})"
    T.update(result_count=stats["dirs"] + stats["files"], result_unit="entries")
    if stats["cut"]:
        T.limit("max_entries")
        foot += f"; output cut at max_entries={max_entries} — use a subdirectory or lower max_depth"
    if len(entries) >= hard_cap or res.timed_out:
        foot += "; directory listing was partial (too large or timed out)"
    return "\n".join(lines) + foot
