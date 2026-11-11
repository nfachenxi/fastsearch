"""Generate an offline HTML snapshot of local usage."""
from datetime import datetime, timedelta, timezone
from contextlib import closing
from importlib.resources import files
import json
from pathlib import Path
import sqlite3
from urllib.parse import quote

from .telemetry import db_path

SHANGHAI = timezone(timedelta(hours=8))


def load_calls(path=None, days=30):
    path = Path(path or db_path())
    if not path.exists():
        return []
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        exists = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='calls'").fetchone()
        if not exists:
            return []
        return [json.loads(row[0]) for row in db.execute(
            'SELECT data FROM calls WHERE timestamp >= ? ORDER BY timestamp', (since,))]


def write_report(output, *, days=30, path=None):
    if days < 1:
        raise ValueError('days must be positive')
    data = dict(calls=load_calls(path, days), days=days,
                generated=datetime.now(SHANGHAI).isoformat())
    comparison_dir = Path(path or db_path()).parent / 'comparisons'
    data['comparisons'] = []
    for item in sorted(comparison_dir.glob('*.json'), reverse=True):
        data['comparisons'].append(json.loads(item.read_text(encoding='utf-8')))
    # Prevent input text from terminating the inert JSON script element.
    payload = json.dumps(data, ensure_ascii=False)
    for char, code in [('<', 'u003c'), ('>', 'u003e'), ('&', 'u0026')]:
        payload = payload.replace(char, chr(92) + code)
    template = files('fastsearch_mcp').joinpath('assets/report.html').read_text(encoding='utf-8')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    comparison_output = output.with_name(output.stem + '-comparison.html')
    template = template.replace('__COMPARISON_LINK__', quote(comparison_output.name))
    output.write_text(template.replace('__REPORT_DATA__', payload), encoding='utf-8')
    comparison_data = dict(data, calls=[], comparison_only=True)
    comparison_payload = json.dumps(comparison_data, ensure_ascii=False)
    for char, code in [('<', 'u003c'), ('>', 'u003e'), ('&', 'u0026')]:
        comparison_payload = comparison_payload.replace(char, chr(92) + code)
    comparison_output.write_text(template.replace('__REPORT_DATA__', comparison_payload), encoding='utf-8')
    return output.resolve()
