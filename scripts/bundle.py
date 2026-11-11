"""Fetch pinned Windows x64 executables and build the search-only package.

    python scripts/bundle.py fetch [dir]       # default: repo root (dev install)
    python scripts/bundle.py searchonly [out]  # default: dist/Fastsearch-MCP-Share

fetch: downloads every entry in bundled-binaries.json (cached by hash under
%LOCALAPPDATA%/fastsearch-mcp/bundle-cache), verifies its SHA256 and writes the
executables plus their licenses to <dir>/src/fastsearch_mcp/bin/<tool>/. The bin/
folders are git-ignored; pyproject's hatch `artifacts` still ships them in the wheel.

searchonly: generates the search-only deploy package from this repo's single source:
the deploy/search-only templates, the search modules (no telemetry/report/compare, so
nothing is recorded), version "<x.y.z>+searchonly", the bundled binaries, and
<out>.zip with one top-level folder named like <out>.

Downloads honour HTTPS_PROXY. Never runs anything it downloads.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "bundled-binaries.json"
BIN = Path("src") / "fastsearch_mcp" / "bin"
DEPLOY = ROOT / "deploy" / "search-only"
SEARCH_ONLY_OUT = ROOT / "dist" / "Fastsearch-MCP-Share"
# Everything else in the package (telemetry, report, compare, assets) is dev-only.
SEARCH_ONLY_MODULES = ["__init__.py", "__main__.py", "binaries.py", "decompile.py", "search.py", "server.py"]
SEARCH_ONLY_DESCRIPTION = ("MCP server giving AI agents fast, gitignore-aware file & text search via fd and "
                           "ripgrep, plus version-pinned .NET decompile snapshots (Windows-friendly). "
                           "Search-only build: no usage records.")
SKIP = {".venv", "__pycache__", ".pytest_cache"}


def cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "fastsearch-mcp" / "bundle-cache"


def fetch_bytes(url: str, sha256: str) -> bytes:
    cached = cache_dir() / sha256
    if cached.is_file():
        data = cached.read_bytes()
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "fastsearch-mcp-bundle"})
        with urllib.request.urlopen(req, timeout=300) as r:  # noqa: S310 (https only)
            data = r.read()
    got = hashlib.sha256(data).hexdigest()
    if got != sha256:
        raise SystemExit(f"SHA256 mismatch for {url}\n  expected {sha256}\n  got      {got}")
    if not cached.is_file():
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    return data


def fetch(pkg: Path) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for entry in manifest:
        dest = pkg / BIN / entry["tool"]
        dest.mkdir(parents=True, exist_ok=True)
        for dl in entry["downloads"]:
            data = fetch_bytes(dl["url"], dl["sha256"])
            if "save_as" in dl:
                (dest / dl["save_as"]).write_bytes(data)
                continue
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for member, name in dl["extract"].items():
                    (dest / name).write_bytes(zf.read(member))
        print(f"{entry['tool']} {entry['version']} -> {dest}")
    # Ship the manifest next to the binaries so recipients can check provenance.
    (pkg / BIN / "BUNDLED-BINARIES.json").write_bytes(MANIFEST.read_bytes())


def _rewrite(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"{path}: expected text not found: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="")


def build_searchonly(out: Path, bundle: bool = True) -> None:
    out = out.resolve()
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(DEPLOY, out, ignore=shutil.ignore_patterns(*SKIP, "*.pyc"))
    pkg = out / "src" / "fastsearch_mcp"
    pkg.mkdir(parents=True)
    for name in SEARCH_ONLY_MODULES:
        shutil.copy2(ROOT / "src" / "fastsearch_mcp" / name, pkg / name)

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    pyproject = pyproject.replace(f'version = "{version}"', f'version = "{version}+searchonly"', 1)
    pyproject = re.sub(r"^description = .*$", lambda _: f"description = {json.dumps(SEARCH_ONLY_DESCRIPTION)}",
                       pyproject, count=1, flags=re.M)
    (out / "pyproject.toml").write_text(pyproject, encoding="utf-8", newline="")
    _rewrite(pkg / "__init__.py", f'"{version}"', f'"{version}+searchonly"')

    if bundle:  # tests build without binaries to stay offline
        fetch(out)
        build_zip(out)


def build_zip(release: Path) -> None:
    files = sorted(p for p in release.rglob("*")
                   if p.is_file() and not SKIP.intersection(p.relative_to(release).parts) and p.suffix != ".pyc")
    if not (release / BIN / "BUNDLED-BINARIES.json").is_file():
        raise SystemExit(f"{release / BIN} is missing; run: bundle.py fetch {release}")
    out = release.with_suffix(".zip")
    tmp = out.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, f"{release.name}/{path.relative_to(release).as_posix()}")
    os.replace(tmp, out)
    print(f"{out} ({len(files)} files, {out.stat().st_size / 1e6:.1f} MB)")


def main() -> None:
    if len(sys.argv) not in (2, 3) or sys.argv[1] not in ("fetch", "searchonly"):
        raise SystemExit(__doc__)
    if sys.argv[1] == "fetch":
        fetch(Path(sys.argv[2]) if len(sys.argv) == 3 else ROOT)
    else:
        build_searchonly(Path(sys.argv[2]) if len(sys.argv) == 3 else SEARCH_ONLY_OUT)


if __name__ == "__main__":
    main()
