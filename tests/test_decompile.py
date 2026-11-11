"""decompile: snapshot per DLL hash + decompiler version, cache hits, failure cleanup,
bundled-decompiler resolution. Uses a fake ilspycmd except for the real smoke test."""
import glob
import os
import sys
import time

import pytest

from fastsearch_mcp import decompile as D, search as S

FAKE = r'''
import os, sys, time
args = sys.argv[1:]
out, dll = args[args.index("-o") + 1], args[-1]
with open(os.environ["FAKE_ILSPY_LOG"], "a") as fh:
    fh.write(dll + "\n")
mode = os.environ.get("FAKE_ILSPY_MODE", "")
if mode == "fail":
    open(os.path.join(out, "partial.cs"), "w").close()
    sys.exit(3)
os.makedirs(os.path.join(out, "Ns"))
os.makedirs(os.path.join(out, "Sub"))
files = {"PlayerController.cs": "public class PlayerController\n{\n}\n", "Ns/Other.cs": "class Other {}\n",
         "Dup.cs": "class Dup {}\n", "Sub/Dup.cs": "class Dup {}\n"}
for name, text in files.items():
    with open(os.path.join(out, name), "w") as fh:
        fh.write(text)
'''


def write_fake(bin_dir, version="1.0.0.0"):
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "fake_ilspy.py"
    script.write_text(FAKE)
    # --version answers before anything else; "hang" spins inside cmd.exe itself so the
    # stub stays one process, like the real ilspycmd.exe.
    cmd = bin_dir / "ilspycmd.cmd"
    cmd.write_text(
        f'@if "%1"=="--version" (echo ilspycmd: {version}& exit /b 0)\r\n'
        '@if "%FAKE_ILSPY_MODE%"=="hang" goto hang\r\n'
        f'@"{sys.executable}" "{script}" %*\r\n@exit /b %errorlevel%\r\n:hang\r\n@goto hang\r\n')
    return cmd


@pytest.fixture()
def fake(tmp_path, monkeypatch):
    monkeypatch.setenv(D.PATH_ENV, str(write_fake(tmp_path / "bin")))
    log = tmp_path / "calls.log"
    monkeypatch.setenv("FAKE_ILSPY_LOG", str(log))
    dll = tmp_path / "Game.dll"
    dll.write_bytes(b"v1")
    return dll, (lambda: log.read_text().splitlines() if log.exists() else [])


def test_export_once_then_cached(fake):
    dll, calls = fake
    first = D.decompile(str(dll), "PlayerController")
    assert "exported in" in first and "public class PlayerController" in first
    assert "ilspycmd 1.0.0.0" in first and "-ilspy1.0.0.0" in first
    second = D.decompile(str(dll), "PlayerController")
    assert "cached" in second and "public class PlayerController" in second
    assert len(calls()) == 1


def test_new_dll_version_gets_new_snapshot(fake):
    dll, calls = fake
    a = D.decompile(str(dll)).splitlines()[1]
    dll.write_bytes(b"v2")
    b = D.decompile(str(dll)).splitlines()[1]
    assert a != b and len(calls()) == 2
    assert len([p for p in D.snapshot_root().iterdir()]) == 2


def test_new_decompiler_version_gets_new_snapshot(fake, tmp_path, monkeypatch):
    dll, calls = fake
    D.decompile(str(dll))
    monkeypatch.setenv(D.PATH_ENV, str(write_fake(tmp_path / "bin2", version="2.0.0.0")))
    out = D.decompile(str(dll))
    assert "exported in" in out and "-ilspy2.0.0.0" in out and len(calls()) == 2


def test_snapshot_listing_and_type_lookup(fake):
    dll, _ = fake
    out = D.decompile(str(dll))
    assert "4 .cs files" in out and "search_text" in out
    assert "class Other" in D.decompile(str(dll), "Ns.Other")
    assert "2 files named Dup.cs" in D.decompile(str(dll), "Dup")
    assert "No file named Missing.cs" in D.decompile(str(dll), "Missing")


def test_failed_export_leaves_nothing(fake, monkeypatch):
    dll, _ = fake
    monkeypatch.setenv("FAKE_ILSPY_MODE", "fail")
    with pytest.raises(S.SearchError) as e:
        D.decompile(str(dll))
    assert e.value.code == "decompile_failed"
    assert list(D.snapshot_root().iterdir()) == []


def test_timeout_leaves_nothing(fake, monkeypatch):
    dll, _ = fake
    monkeypatch.setenv("FAKE_ILSPY_MODE", "hang")
    monkeypatch.setattr(D, "EXPORT_TIMEOUT", 0.5)
    started = time.perf_counter()
    with pytest.raises(S.SearchError) as e:
        D.decompile(str(dll))
    assert time.perf_counter() - started < 3
    assert e.value.code == "decompile_timeout"
    assert list(D.snapshot_root().iterdir()) == []


def test_bad_inputs(fake, tmp_path, monkeypatch):
    dll, _ = fake
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    with pytest.raises(S.SearchError) as e:
        D.decompile(str(txt))
    assert e.value.code == "not_dll"
    monkeypatch.setenv(D.PATH_ENV, str(tmp_path / "missing.exe"))
    with pytest.raises(S.SearchError) as e:
        D.decompile(str(dll))
    assert e.value.code == "ilspycmd_missing"


def test_resolution_order(tmp_path, monkeypatch):
    monkeypatch.delenv(D.PATH_ENV, raising=False)
    path_cmd = write_fake(tmp_path / "onpath")
    monkeypatch.setenv("PATH", str(tmp_path / "onpath"))
    bundled = tmp_path / "bundled" / "ilspycmd.exe"
    monkeypatch.setattr(D, "BUNDLED", bundled)
    assert os.path.samefile(D.find_ilspycmd(), path_cmd)  # no bundled copy: PATH
    bundled.parent.mkdir()
    bundled.write_bytes(b"")
    assert D.find_ilspycmd() == str(bundled)  # bundled copy wins over PATH
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(D, "BUNDLED", tmp_path / "none.exe")
    with pytest.raises(S.SearchError) as e:
        D.find_ilspycmd()
    assert e.value.code == "ilspycmd_missing"


def _managed_dll():
    pattern = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "dotnet", "shared",
                           "Microsoft.NETCore.App", "*", "System.Collections.Immutable.dll")
    return next(iter(sorted(glob.glob(pattern))), None)


@pytest.mark.skipif(not D.BUNDLED.is_file(), reason="run scripts/bundle.py fetch . first")
@pytest.mark.skipif(_managed_dll() is None, reason="no .NET assembly on this machine to decompile")
def test_bundled_ilspycmd_smoke(monkeypatch):
    monkeypatch.delenv(D.PATH_ENV, raising=False)
    out = D.decompile(_managed_dll(), "ImmutableArray")
    assert "ilspycmd 11.2.0.10050" in out and "static class ImmutableArray" in out
