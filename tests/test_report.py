import json
import subprocess
import sys

from fastsearch_mcp import telemetry as T
from fastsearch_mcp.report import load_calls, write_report


def test_report_empty(tmp_path):
    output = write_report(tmp_path / 'empty.html', path=tmp_path / 'absent.sqlite3')
    assert '"calls": []' in output.read_text(encoding='utf-8')


def test_report_safe_and_complete(tmp_path, monkeypatch):
    monkeypatch.setenv('FASTSEARCH_TELEMETRY_DIR', str(tmp_path))
    monkeypatch.delenv('FASTSEARCH_TELEMETRY', raising=False)
    def search(path):
        return 'body should not be saved'
    T.invoke(search, ('</script><script>alert(1)</script>',), {})
    assert len(load_calls()) == 1
    text = write_report(tmp_path / 'report.html').read_text(encoding='utf-8')
    assert '</script><script>alert(1)</script>' not in text
    assert 'body should not be saved' not in text
    payload = text.split('type="application/json">')[1].split('</script>')[0]
    assert json.loads(payload)['calls'][0]['path'].startswith('</script>')


def test_report_cli(tmp_path, monkeypatch):
    monkeypatch.setenv('FASTSEARCH_TELEMETRY_DIR', str(tmp_path / 'usage'))
    out = tmp_path / 'report.html'
    result = subprocess.run([sys.executable, '-m', 'fastsearch_mcp', 'report', '--output', str(out)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert out.exists()
