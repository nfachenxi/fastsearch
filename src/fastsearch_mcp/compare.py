"""Replay a random sample of historical requests with native PowerShell."""
from datetime import datetime, timezone
import base64
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import time
import uuid

from .report import load_calls
from .telemetry import db_path


def comparison_path():
    return db_path().parent / 'comparisons'


def unsupported(call):
    p = call.get('parameters', {})
    if call.get('status') != 'ok' or call.get('timed_out') or call.get('scan_incomplete'):
        return '原调用失败、超时或扫描不完整'
    tool = call.get('tool')
    if tool not in ('read_lines', 'find_files', 'search_text'):
        return '本版仅复现读取行、文件查找和文本搜索'
    if tool == 'find_files':
        if any(p.get(k) for k in ('regex', 'full_path', 'extensions', 'max_depth', 'exclude', 'changed_within', 'min_size', 'max_size', 'case_sensitive')) or p.get('file_type') not in (None, 'file'):
            return '文件查找使用了暂不支持的过滤参数'
        if any(c in p.get('pattern', '') for c in '[]{}'):
            return 'glob 方括号或花括号在两种引擎中语义不同'
    if tool == 'search_text':
        if p.get('output', 'content') != 'content':
            return '暂不复现文件列表搜索'
        if call.get('display_limited'):
            return '原搜索展示受限，暂不对照'
        if not p.get('literal') or not p.get('pattern'):
            return '仅复现非空的字面量搜索，避免正则引擎差异'
        if any(p.get(k) for k in ('word', 'include', 'exclude', 'file_types', 'context', 'before', 'after', 'multiline', 'max_per_file')):
            return '文本搜索使用了暂不支持的上下文或过滤参数'
    enc = p.get('encoding')
    if enc and enc.lower() not in ('utf-8', 'utf8', 'utf-8-sig', 'utf-16', 'utf-16le', 'gbk', 'gb18030'):
        return '暂不支持该编码'
    if not Path(call.get('normalized_path') or p.get('path', '')).exists():
        return '原路径当前不存在'
    return None


# Request data is supplied as JSON through an environment variable, never as code.
SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$q = $env:FASTSEARCH_COMPARE_REQUEST | ConvertFrom-Json
$p = $q.parameters
$root = $q.path
$watch = [Diagnostics.Stopwatch]::StartNew()
$enc = 'utf8'
if ($p.encoding -in @('gbk','gb18030')) { $enc = $p.encoding }
elseif ($p.encoding -in @('utf-16','utf-16le')) { $enc = 'unicode' }
$count = 0
$body = ''
switch ($q.tool) {
 'read_lines' {
   $start = [Math]::Max(1, [int]$p.start)
   $limit = [Math]::Max(1, [Math]::Min(2000, [int]$p.max_lines))
   $end = if ($null -eq $p.end -or [int]$p.end -lt $start) { $start+$limit-1 } else { [Math]::Min([int]$p.end,$start+$limit-1) }
   $lines = @(Get-Content -LiteralPath $root -Encoding $enc | Select-Object -Skip ($start-1) -First ($end-$start+1))
   $count = $lines.Count
   $body = $lines -join [Environment]::NewLine
 }
 'find_files' {
   $pattern = if ($p.pattern) { [string]$p.pattern } else { '*' }
   $limit = [Math]::Max(1,[Math]::Min(10000,[int]$p.max_results))
   $items = @(Get-ChildItem -LiteralPath $root -Recurse -Force:([bool]$p.hidden) | Where-Object { $_.Name -like $pattern -and ($p.file_type -ne 'file' -or -not $_.PSIsContainer) } | Select-Object -First $limit)
   $count = $items.Count
   $body = ($items | ForEach-Object { $_.FullName }) -join [Environment]::NewLine
 }
 'search_text' {
   $files = if (Test-Path -LiteralPath $root -PathType Leaf) { @(Get-Item -LiteralPath $root) } else { @(Get-ChildItem -LiteralPath $root -Recurse -File -Force:([bool]$p.hidden)) }
   $case = if ($null -eq $p.case_sensitive) { [regex]::IsMatch([string]$p.pattern,'[A-Z]') } else { [bool]$p.case_sensitive }
   $limit = [Math]::Max(1,[Math]::Min(5000,[int]$p.max_results))
   $hits = @($files | Select-String -Pattern ([string]$p.pattern) -SimpleMatch -CaseSensitive:$case -Encoding $enc | Select-Object -First $limit)
   $count = $hits.Count
   $body = ($hits | ForEach-Object { '{0}:{1}:{2}' -f $_.Path,$_.LineNumber,$_.Line }) -join [Environment]::NewLine
 }
}
$watch.Stop()
@{duration_ms=$watch.Elapsed.TotalMilliseconds; result_count=$count; output_bytes=[Text.Encoding]::UTF8.GetByteCount($body); powershell_version=$PSVersionTable.PSVersion.ToString()} | ConvertTo-Json -Compress
'''


def run_sample(call, executable, timeout):
    p = dict(call['parameters'])
    path = call.get('normalized_path') or p['path']
    notes = ['历史 MCP 与当前 PowerShell 不同时间执行；文件与缓存可能变化。',
             '未保存历史正文，未验证结果内容一致；不据此计算提速百分比。']
    if call['tool'] != 'read_lines':
        notes.append('PowerShell 不遵循 .gitignore、MCP 默认排除和二进制/大小跳过规则；结果排序、限量及格式也可能不同。')
    if not p.get('encoding'):
        notes.append('PowerShell 默认 UTF-8；MCP 自动识别编码可能不同。')
    if call.get('display_limited'):
        notes.append('历史 MCP 输出被限量或裁剪。')
    row = dict(source_id=call['id'], tool=call['tool'], path=path, parameters=p,
               original_time=call['timestamp'], original_version=call.get('version'),
               mcp_ms=call['duration_ms'], mcp_count=call.get('result_count'),
               notes=notes, command=SCRIPT, status='ok')
    env = dict(os.environ, FASTSEARCH_COMPARE_REQUEST=json.dumps(dict(tool=call['tool'], path=path, parameters=p), ensure_ascii=False))
    encoded = base64.b64encode(SCRIPT.encode('utf-16le')).decode('ascii')
    started = time.perf_counter()
    try:
        result = subprocess.run([executable, '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                                env=env, capture_output=True, timeout=timeout, creationflags=0x08000000 if os.name == 'nt' else 0)
        row['process_ms'] = (time.perf_counter()-started)*1000
        if result.returncode:
            row.update(status='error', error=result.stderr.decode('utf-8', 'replace')[:2000])
        else:
            row['powershell'] = json.loads(result.stdout.decode('utf-8-sig'))
            row['count_equal'] = row['mcp_count'] == row['powershell']['result_count']
    except subprocess.TimeoutExpired:
        row.update(status='timeout', timeout_seconds=timeout)
    except (OSError, ValueError) as exc:
        row.update(status='error', error=str(exc))
    return row


def generate_comparison(*, count=5, days=30, seed=None, timeout=30, source=None, output=None):
    if count < 1 or days < 1 or timeout <= 0:
        raise ValueError('count, days and timeout must be positive')
    executable = shutil.which('pwsh')
    if not executable:
        raise RuntimeError('PowerShell 7 (pwsh) is required')
    candidates, skipped = [], {}
    for call in load_calls(source, days):
        reason = unsupported(call)
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
        else:
            candidates.append(call)
    actual_seed = seed if seed is not None else random.SystemRandom().randrange(2**32)
    selected = random.Random(actual_seed).sample(candidates, min(count, len(candidates)))
    result = dict(id=uuid.uuid4().hex, generated=datetime.now(timezone.utc).isoformat(),
                  seed=actual_seed, requested=count, eligible=len(candidates), skipped=skipped,
                  samples=[run_sample(c, executable, timeout) for c in selected])
    target = Path(output) if output else comparison_path() / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + result['id'][:8] + '.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return target
