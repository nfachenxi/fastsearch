import json
import shutil
from pathlib import Path
import pytest
from fastsearch_mcp import telemetry as T, search as S
from fastsearch_mcp.compare import generate_comparison, unsupported, run_sample
from fastsearch_mcp.report import load_calls, write_report


@pytest.mark.skipif(not shutil.which('pwsh'), reason='requires PowerShell 7')
def test_real_sample_is_separate_and_safe(tmp_path, monkeypatch):
    monkeypatch.delenv('FASTSEARCH_ALLOWED_ROOTS', raising=False)
    monkeypatch.delenv('FASTSEARCH_TELEMETRY', raising=False)
    file = tmp_path / 'sample.txt'
    file.write_text('alpha'+chr(10)+'$(throw dangerous)'+chr(10)+'omega', encoding='utf-8')
    T.invoke(S.read_lines, (str(file), 2, 2), {})
    T.invoke(S.search_text, ('$(throw dangerous)', str(file)), {'literal':True})
    before = load_calls()
    target = generate_comparison(count=5, seed=42)
    data=json.loads(target.read_text(encoding='utf-8'))
    assert len(data['samples']) == 2
    assert len(load_calls()) == len(before)
    for row in data['samples']:
        assert row['status'] == 'ok', row
        assert row['powershell']['result_count'] == 1
        assert row['process_ms'] >= row['powershell']['duration_ms']
    report=write_report(tmp_path/'report.html')
    assert data['id'] in report.read_text(encoding='utf-8')
    second=json.loads(generate_comparison(count=5,seed=42).read_text(encoding='utf-8'))
    assert [s['source_id'] for s in data['samples']] == [s['source_id'] for s in second['samples']]


def test_unsupported_and_empty(tmp_path, monkeypatch):
    assert unsupported({'status':'ok','tool':'search_text','parameters':{'literal':True, 'pattern':'needle', 'output':'files'}}) == '暂不复现文件列表搜索'
    assert unsupported({'status':'ok','tool':'tree'})
    assert unsupported({'status':'ok','tool':'search_text','parameters':{'literal':False}})
    if shutil.which('pwsh'):
        data=json.loads(generate_comparison(count=5).read_text(encoding='utf-8'))
        assert data['samples'] == [] and data['eligible']==0
