import pytest


@pytest.fixture(autouse=True)
def isolate_usage(tmp_path, monkeypatch):
    monkeypatch.setenv('FASTSEARCH_TELEMETRY_DIR', str(tmp_path / 'usage-log'))
    monkeypatch.setenv('FASTSEARCH_DECOMPILE_DIR', str(tmp_path / 'decompile'))
