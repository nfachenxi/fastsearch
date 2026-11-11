"""Locate fd / rg executables, downloading them from GitHub Releases if missing.

Resolution order for each tool:
  1. Explicit env var  FASTSEARCH_FD_PATH / FASTSEARCH_RG_PATH
  2. Bundled copy       <package>/bin/<tool>/ (Windows share packages, see scripts/bundle.py)
  3. System PATH        (fd, fdfind[Debian/Ubuntu], rg)
  4. Local cache dir    (previously downloaded)
  5. Download from GitHub Releases into the cache dir (unless FASTSEARCH_NO_DOWNLOAD=1)

Env knobs:
  FASTSEARCH_CACHE_DIR       override cache directory
  FASTSEARCH_FD_VERSION      default 10.5.2
  FASTSEARCH_RG_VERSION      default 15.2.0
  FASTSEARCH_GITHUB_MIRROR   URL prefix for mirrors, e.g. "https://ghfast.top/"
  FASTSEARCH_NO_DOWNLOAD     "1" to disable auto download
  HTTPS_PROXY / HTTP_PROXY   honoured by urllib automatically
"""

from __future__ import annotations

import hashlib
import io
import os
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import threading
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

IS_WINDOWS = os.name == "nt"
EXE = ".exe" if IS_WINDOWS else ""

DEFAULT_FD_VERSION = "10.5.2"
DEFAULT_RG_VERSION = "15.2.0"


@dataclass(frozen=True)
class ToolSpec:
    name: str              # logical name: "fd" / "rg"
    exe: str               # executable base name
    path_candidates: tuple  # names to look up on PATH
    repo: str
    version_env: str
    default_version: str
    path_env: str

    def tag(self, version: str) -> str:
        return f"v{version}" if self.name == "fd" else version

    def archive_stem(self, version: str, target: str) -> str:
        if self.name == "fd":
            return f"fd-v{version}-{target}"
        return f"ripgrep-{version}-{target}"


FD = ToolSpec("fd", "fd", ("fd", "fdfind"), "sharkdp/fd",
              "FASTSEARCH_FD_VERSION", DEFAULT_FD_VERSION, "FASTSEARCH_FD_PATH")
RG = ToolSpec("rg", "rg", ("rg",), "BurntSushi/ripgrep",
              "FASTSEARCH_RG_VERSION", DEFAULT_RG_VERSION, "FASTSEARCH_RG_PATH")
TOOLS = {"fd": FD, "rg": RG}

_lock = threading.Lock()
_resolved: dict[str, str] = {}


class BinaryNotFound(RuntimeError):
    pass


def cache_dir() -> Path:
    env = os.environ.get("FASTSEARCH_CACHE_DIR")
    if env:
        return Path(env).expanduser()
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "fastsearch-mcp" / "bin"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "fastsearch-mcp" / "bin"
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "fastsearch-mcp" / "bin"


def _targets() -> list[str]:
    """Release target triples to try, best first."""
    m = platform.machine().lower()
    arm = m in ("arm64", "aarch64", "armv8", "armv8l")
    if IS_WINDOWS:
        # Windows on ARM can run x64 binaries via emulation, so keep it as fallback.
        return (["aarch64-pc-windows-msvc"] if arm else []) + ["x86_64-pc-windows-msvc"]
    if sys.platform == "darwin":
        return ["aarch64-apple-darwin", "x86_64-apple-darwin"] if arm else ["x86_64-apple-darwin"]
    if arm:
        return ["aarch64-unknown-linux-musl", "aarch64-unknown-linux-gnu"]
    return ["x86_64-unknown-linux-musl", "x86_64-unknown-linux-gnu"]


def _http_get(url: str, timeout: float = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "fastsearch-mcp"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (https only)
        return r.read()


def _extract(archive: bytes, is_zip: bool, exe_name: str, dest: Path) -> None:
    wanted = exe_name + EXE
    if is_zip:
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            for n in zf.namelist():
                if n.rsplit("/", 1)[-1] == wanted:
                    data = zf.read(n)
                    break
            else:
                raise BinaryNotFound(f"{wanted} not found inside archive")
    else:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
            for mbr in tf.getmembers():
                if mbr.isfile() and mbr.name.rsplit("/", 1)[-1] == wanted:
                    f = tf.extractfile(mbr)
                    assert f is not None
                    data = f.read()
                    break
            else:
                raise BinaryNotFound(f"{wanted} not found inside archive")
    dest.parent.mkdir(parents=True, exist_ok=True)
    # atomic-ish write so a half-written exe is never picked up
    fd_, tmp = tempfile.mkstemp(dir=dest.parent, prefix=f".{exe_name}-")
    with os.fdopen(fd_, "wb") as fh:
        fh.write(data)
    os.chmod(tmp, os.stat(tmp).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.replace(tmp, dest)


def download(spec: ToolSpec, log=lambda *_: None) -> Path:
    version = os.environ.get(spec.version_env, spec.default_version).lstrip("v")
    mirror = os.environ.get("FASTSEARCH_GITHUB_MIRROR", "").strip()
    dest_dir = cache_dir() / f"{spec.name}-{version}"
    dest = dest_dir / (spec.exe + EXE)
    errors = []
    for target in _targets():
        ext = ".zip" if "windows" in target else ".tar.gz"
        stem = spec.archive_stem(version, target)
        url = f"https://github.com/{spec.repo}/releases/download/{spec.tag(version)}/{stem}{ext}"
        if mirror:
            url = mirror.rstrip("/") + "/" + url
        try:
            log(f"[fastsearch-mcp] downloading {url}")
            blob = _http_get(url)
            # ripgrep publishes .sha256 files; verify when available.
            try:
                expected = _http_get(url + ".sha256", timeout=20).decode().split()[0].lower()
                actual = hashlib.sha256(blob).hexdigest()
                if expected != actual:
                    raise BinaryNotFound(f"sha256 mismatch for {url}")
            except BinaryNotFound:
                raise
            except Exception:
                pass  # no checksum published (fd) or not reachable
            _extract(blob, ext == ".zip", spec.exe, dest)
            log(f"[fastsearch-mcp] installed {dest}")
            return dest
        except Exception as e:  # try next target
            errors.append(f"{url}: {e}")
    raise BinaryNotFound(
        f"Could not download {spec.name}. Tried:\n  " + "\n  ".join(errors)
        + "\nInstall it manually (e.g. `scoop install fd ripgrep` / `winget install sharkdp.fd BurntSushi.ripgrep.MSVC`)"
        " or set FASTSEARCH_GITHUB_MIRROR / HTTPS_PROXY."
    )


# Oldest versions supporting every flag we use (--no-require-git etc.).
MIN_VERSION = {"fd": (8, 7, 0), "rg": (11, 0, 0)}


def _version_ok(path: str, spec: ToolSpec) -> bool:
    """Skip outdated binaries on PATH (e.g. apt's old fdfind) so we download a good one."""
    import re
    import subprocess
    try:
        kw = {"creationflags": 0x08000000} if IS_WINDOWS else {}
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10, **kw).stdout
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", out)
        return bool(m) and tuple(map(int, m.groups())) >= MIN_VERSION[spec.name]
    except Exception:
        return False


def find_existing(spec: ToolSpec) -> str | None:
    explicit = os.environ.get(spec.path_env)
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_file():
            return str(p)
        raise BinaryNotFound(f"{spec.path_env}={explicit} does not exist")
    bundled = Path(__file__).parent / "bin" / spec.name / (spec.exe + EXE)
    if IS_WINDOWS and bundled.is_file():  # shipped with share packages (scripts/bundle.py)
        return str(bundled)
    for cand in spec.path_candidates:
        found = shutil.which(cand)
        if found and _version_ok(found, spec):
            return found
    version = os.environ.get(spec.version_env, spec.default_version).lstrip("v")
    cached = cache_dir() / f"{spec.name}-{version}" / (spec.exe + EXE)
    if cached.is_file():
        return str(cached)
    return None


def get_binary(name: str, log=lambda *_: None) -> str:
    """Return the path to fd/rg, downloading on first use if necessary."""
    if name in _resolved:
        return _resolved[name]
    spec = TOOLS[name]
    with _lock:
        if name in _resolved:
            return _resolved[name]
        path = find_existing(spec)
        if path is None:
            if os.environ.get("FASTSEARCH_NO_DOWNLOAD") == "1":
                raise BinaryNotFound(
                    f"{spec.name} not found on PATH and auto-download is disabled (FASTSEARCH_NO_DOWNLOAD=1)."
                )
            path = str(download(spec, log=log))
        _resolved[name] = path
        return path
