import concurrent.futures
import json
import sqlite3
import sys

import pytest
from fastsearch_mcp import telemetry as T, search as S


@pytest.fixture(autouse=True)
def usage_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('FASTSEARCH_TELEMETRY_DIR', str(tmp_path / 'usage'))
    monkeypatch.delenv('FASTSEARCH_TELEMETRY', raising=False)
    monkeypatch.delenv('FASTSEARCH_ALLOWED_ROOTS', raising=False)


def records():
    with sqlite3.connect(T.db_path()) as db:
        return [json.loads(row[0]) for row in db.execute('SELECT data FROM calls')]


def test_concurrent_isolation():
    def work(path):
        T.update(result_count=path)
        return str(path)
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda i: T.invoke(work, (i,), {}), range(20)))
    rows = records()
    assert len(rows) == 20
    assert all(r['path'] == r['result_count'] for r in rows)


def test_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv('FASTSEARCH_TELEMETRY', '0')
    assert T.invoke(lambda: 'ok', (), {}) == 'ok'
    assert not T.db_path().exists()


def test_unwritable(tmp_path, monkeypatch):
    blocked = tmp_path / 'file'
    blocked.write_text('x')
    monkeypatch.setenv('FASTSEARCH_TELEMETRY_DIR', str(blocked))
    assert T.invoke(lambda: 'ok', (), {}) == 'ok'


def test_missing_path(tmp_path):
    with pytest.raises(S.SearchError):
        T.invoke(S.tree, (str(tmp_path / 'missing'),), {})
    assert records()[0]['error_code'] == 'path_missing'


def test_read_range_not_truncated(tmp_path):
    path = tmp_path / 'text.txt'
    path.write_text('a\nb\nc\n')
    T.invoke(S.read_lines, (str(path), 2, 2), {})
    r = records()[0]
    assert r['result_count'] == 1
    assert not r['display_limited']


def test_timeout_is_not_empty_success():
    def slow():
        S.run_streaming([sys.executable, '-c', 'import time; time.sleep(5)'], lambda _: True, timeout=.05)
        return ''
    T.invoke(slow, (), {})
    row = records()[0]
    assert row['timed_out'] and row['scan_incomplete']


def test_result_limit_and_count_display(tmp_path):
    for i in range(3):
        (tmp_path / f'{i}.txt').write_text('needle\n')
    T.invoke(S.find_files, (str(tmp_path),), {'max_results': 1, 'extensions': ['txt']})
    T.invoke(S.count_matches, ('needle', str(tmp_path)), {'max_files': 1, 'include': ['*.txt']})
    a, b = records()
    assert a['display_limited'] and a['scan_incomplete']
    assert b['display_limited'] and not b['scan_incomplete']
    assert b['result_count'] == 3


def test_bad_regex(tmp_path):
    out = T.invoke(S.search_text, ('Start(|Init', str(tmp_path)), {})
    assert out.startswith('NOTE: invalid regex')
    fallback = records()[0]
    assert fallback['regex_fallback'] is True and fallback['status'] == 'warning'
    assert 'regex parse error' in fallback['warning'] and not fallback['scan_incomplete']
    with pytest.raises(S.SearchError):
        T.invoke(S.count_matches, ('(unclosed', str(tmp_path)), {})
    assert records()[1]['status'] == 'error'


def test_fast_read_and_files_metrics(tmp_path):
    path = tmp_path / 'text.txt'
    path.write_text('needle' + chr(10) + 'needle' + chr(10) + 'tail')
    T.invoke(S.read_lines, (str(path), 1, 1), {'count_total': False})
    T.invoke(S.search_text, ('needle', str(path)), {'output': 'files'})
    read, files = records()
    assert read['has_more'] and read['total_lines'] is None
    assert not read['display_limited']
    assert files['result_unit'] == 'files' and files['result_count'] == 1


def test_output_budget_metrics(tmp_path):
    path = tmp_path / 'text.txt'
    path.write_text(('needle ' + 'x' * 200 + chr(10)) * 30)
    out = T.invoke(S.search_text, ('needle', str(path)), {'max_output_chars': 1024})
    row = records()[0]
    assert len(out) <= 1024
    assert row['display_limited'] and row['scan_incomplete']
    assert 'max_output_chars' in row['limit_reasons']
