"""The search-only deploy package is generated from this repo's single source."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bundle", ROOT / "scripts" / "bundle.py")
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


def test_searchonly_build_has_no_usage_records(tmp_path):
    out = tmp_path / "Fastsearch-MCP-Share"
    bundle.build_searchonly(out, bundle=False)

    pkg = out / "src" / "fastsearch_mcp"
    assert sorted(p.name for p in pkg.iterdir()) == sorted(bundle.SEARCH_ONLY_MODULES)
    for name in ("README.md", "AI-INSTALL.md", "AGENTS.md", "01-install.ps1", "check.py", "pyproject.toml"):
        assert (out / name).is_file(), name
    assert 'version = "' in (out / "pyproject.toml").read_text(encoding="utf-8")
    assert '+searchonly"' in (out / "pyproject.toml").read_text(encoding="utf-8")
    assert '+searchonly"' in (pkg / "__init__.py").read_text(encoding="utf-8")
    # Modules are copied unchanged, so the two builds cannot drift apart.
    for name in ("search.py", "server.py", "decompile.py", "binaries.py", "__main__.py"):
        assert (pkg / name).read_bytes() == (ROOT / "src" / "fastsearch_mcp" / name).read_bytes(), name

    sample = tmp_path / "sample.txt"
    sample.write_text("needle\n", encoding="utf-8")
    log = tmp_path / "log"
    env = dict(os.environ, PYTHONPATH=str(out / "src"), FASTSEARCH_TELEMETRY_DIR=str(log))
    code = ("import fastsearch_mcp, fastsearch_mcp.server as s, fastsearch_mcp.search as S;"
            "assert s.telemetry is None, s.telemetry;"
            f"print(fastsearch_mcp.__version__, S.read_lines({str(sample)!r}, 1))")
    run = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert "+searchonly" in run.stdout and "needle" in run.stdout
    assert not log.exists()

    report = subprocess.run([sys.executable, "-m", "fastsearch_mcp", "report"], env=env, capture_output=True, text=True)
    assert report.returncode != 0 and "search-only" in report.stderr
