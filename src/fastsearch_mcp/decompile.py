"""Version-pinned decompile snapshots: one full ilspycmd export per DLL hash and decompiler version."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import search as S
from .binaries import EXE, IS_WINDOWS, cache_dir

try:
    from . import telemetry as T
except ImportError:  # the search-only package ships without usage records
    T = None

EXPORT_TIMEOUT = 300  # full export of a ~5 MB game assembly measured at 1.7 s (ilspycmd 11.2); one past call hung 3.2 h
PATH_ENV = "FASTSEARCH_ILSPYCMD_PATH"
BUNDLED = Path(__file__).parent / "bin" / "ilspycmd" / ("ilspycmd" + EXE)
_versions: dict[tuple[str, float], str] = {}


def snapshot_root() -> Path:
    # shortcut: old snapshots are never evicted (~5 MB each); add cleanup if the dir passes ~1 GB.
    return Path(os.environ.get("FASTSEARCH_DECOMPILE_DIR") or cache_dir().parent / "decompile")


def find_ilspycmd() -> str:
    """Explicit env var, then the copy bundled with the package, then PATH."""
    explicit = os.environ.get(PATH_ENV)
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        raise S.SearchError(f"{PATH_ENV}={explicit} does not exist", "ilspycmd_missing")
    if BUNDLED.is_file():
        return str(BUNDLED)
    found = shutil.which("ilspycmd")
    if found:
        return found
    raise S.SearchError("ilspycmd not found: no bundled copy and none on PATH. "
                        "Install: dotnet tool install -g ilspycmd", "ilspycmd_missing")


def decompiler_version(exe: str) -> str:
    """`ilspycmd --version`, cached per binary; part of the snapshot name because
    different decompiler versions render the same DLL differently."""
    key = (exe, os.path.getmtime(exe))
    if key not in _versions:
        kw = {"creationflags": 0x08000000} if IS_WINDOWS else {}
        try:
            out = subprocess.run([exe, "--version"], capture_output=True, text=True,
                                 timeout=60, **kw).stdout
        except (OSError, subprocess.TimeoutExpired) as e:
            raise S.SearchError(f"ilspycmd --version failed: {e}", "decompile_failed") from e
        m = re.search(r"ilspycmd:\s*([\w.]+)", out) or re.search(r"(\d+(?:\.\d+)+)", out)
        _versions[key] = m.group(1) if m else "unknown"
    return _versions[key]


def decompile(dll: str, type_name: str | None = None) -> str:
    path = S.normalize_path(dll)
    if not (os.path.isfile(path) and path.lower().endswith(".dll")):
        raise S.SearchError(f"Not a .dll file: {path}", "not_dll")
    exe = find_ilspycmd()
    version = decompiler_version(exe)

    with open(path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()[:12]
    snap = snapshot_root() / f"{Path(path).stem}-{digest}-ilspy{version}"
    cached = snap.is_dir()
    note = "cached"
    if not cached:
        snap.parent.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.mkdtemp(prefix=snap.name + ".", suffix=".tmp", dir=snap.parent)
        started = time.perf_counter()
        try:
            res = S.run_streaming([exe, "-p", "-o", tmp, path], lambda _: True, timeout=EXPORT_TIMEOUT)
            if res.timed_out:
                raise S.SearchError(f"ilspycmd timed out after {EXPORT_TIMEOUT}s on {path}", "decompile_timeout")
            if res.returncode != 0:
                raise S.SearchError(f"ilspycmd failed (exit {res.returncode}) on {path}{S._stderr_hint(res)}",
                                    "decompile_failed")
            try:
                os.replace(tmp, snap)
            except OSError:
                if not snap.is_dir():  # otherwise a concurrent call published the same snapshot first
                    raise
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        note = f"exported in {time.perf_counter() - started:.1f}s"

    files = sorted(snap.rglob("*.cs"))
    if T is not None:
        T.update(cache_hit=cached, snapshot=str(snap), result_count=len(files), result_unit="files")
    head = f"{path}\nsnapshot: {snap}  [sha256 {digest}, ilspycmd {version}, {note}, {len(files)} .cs files]"
    if not type_name:
        return head + f"\nSearch it with search_text(path=\"{snap}\") and read files with read_lines."

    name = type_name.rsplit(".", 1)[-1]
    hits = [f for f in files if f.stem == name]
    if len(hits) == 1:
        return head + "\n" + S.read_lines(str(hits[0]))
    if hits:
        return head + f"\n{len(hits)} files named {name}.cs:\n" + "\n".join(str(f) for f in hits)
    return (head + f"\nNo file named {name}.cs (nested or generic types live inside another file). "
            f"Try search_text(pattern=\"class {name}\\b\", path=\"{snap}\").")
