"""Local per-call usage records. No search output or source text is stored."""
from __future__ import annotations

from contextvars import ContextVar
from contextlib import closing
from datetime import datetime, timezone
import inspect
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import threading
import uuid

from . import __version__

_current: ContextVar[dict | None] = ContextVar('fastsearch_metrics', default=None)
INSTANCE = uuid.uuid4().hex
_last_warning = 0.0
_write_lock = threading.Lock()


def update(**values):
    metrics = _current.get()
    if metrics is not None:
        metrics.update(values)


def limit(reason):
    metrics = _current.get()
    if metrics is not None:
        metrics['display_limited'] = True
        reasons = metrics.setdefault('limit_reasons', [])
        if reason not in reasons:
            reasons.append(reason)


def db_path():
    base = Path(os.environ.get('FASTSEARCH_TELEMETRY_DIR') or
                str(Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share'))) / 'fastsearch-mcp'))
    return base / 'usage.sqlite3'


def save(event):
    global _last_warning
    try:
        path = db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _write_lock, closing(sqlite3.connect(path, timeout=0.5)) as db, db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA synchronous=NORMAL')
            db.execute('CREATE TABLE IF NOT EXISTS calls (id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, tool TEXT NOT NULL, data TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS calls_time ON calls(timestamp)')
            db.execute('INSERT INTO calls VALUES (?, ?, ?, ?)',
                       (event['id'], event['timestamp'], event['tool'], json.dumps(event, ensure_ascii=False)))
    except (OSError, sqlite3.Error) as exc:
        now = time.monotonic()
        if now - _last_warning > 60:
            print(f'fastsearch usage record failed: {exc}', file=sys.stderr)
            _last_warning = now


def invoke(fn, args, kwargs, started=None):
    """Called in the worker thread; each invocation owns its context and record."""
    if os.environ.get('FASTSEARCH_TELEMETRY', '1') == '0':
        return fn(*args, **kwargs)
    started = started if started is not None else time.perf_counter()
    bound = inspect.signature(fn).bind(*args, **kwargs)
    bound.apply_defaults()
    event = dict(id=uuid.uuid4().hex, timestamp=datetime.now(timezone.utc).isoformat(),
                 instance=INSTANCE, version=__version__, tool=fn.__name__,
                 path=bound.arguments.get('path', ''), parameters=dict(bound.arguments),
                 timed_out=False, scan_incomplete=False, display_limited=False, status='ok')
    token = _current.set(event)
    try:
        result = fn(*args, **kwargs)
        event.update(output_chars=len(result), output_bytes=len(result.encode('utf-8')))
        return result
    except Exception as exc:
        event.update(status='error', error_code=getattr(exc, 'code', type(exc).__name__), error=str(exc)[:2000])
        raise
    finally:
        event['duration_ms'] = (time.perf_counter() - started) * 1000
        _current.reset(token)
        save(event)
