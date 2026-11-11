"""Fixed synthetic corpus; warm calls, including local recording overhead."""
import argparse
import json
import os
from pathlib import Path
import statistics
import tempfile
import time
from fastsearch_mcp import search as S, telemetry as T


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    results = {}
    with tempfile.TemporaryDirectory(prefix='fastsearch-bench-', dir=Path(args.output).resolve().parent) as tmp:
        root = Path(tmp) / 'corpus'
        root.mkdir()
        for i in range(300):
            (root / f'item_{i:04}.txt').write_text(('ordinary line' + chr(10)) * 30 + 'needle' + chr(10), encoding='utf-8')
        os.environ['FASTSEARCH_TELEMETRY_DIR'] = str(Path(tmp) / 'usage')
        os.environ.pop('FASTSEARCH_ALLOWED_ROOTS', None)
        cases = [
            ('find_files', S.find_files, (str(root), '*.txt'), {'max_results': 1000, 'relative': True},
             lambda: sorted(p.name for p in root.rglob('*.txt'))),
            ('search_text', S.search_text, ('needle', str(root)), {'literal': True, 'max_results': 1000, 'relative': True},
             lambda: sorted((p.name, i) for p in root.rglob('*.txt') for i, line in enumerate(p.read_text(encoding='utf-8').splitlines(), 1) if 'needle' in line)),
        ]
        for name, fn, pos, kw, baseline in cases:
            samples = {'off': [], 'on': [], 'python_baseline': []}
            expected = fn(*pos, **kw)
            expected_base = baseline()
            if name == 'find_files':
                assert sorted(expected.splitlines()[1:]) == expected_base
            else:
                found = []
                file = None
                for line in expected.splitlines()[1:]:
                    if line.endswith('.txt'):
                        file = line
                    elif line.startswith('  ') and ': ' in line:
                        found.append((file, int(line.strip().split(':', 1)[0])))
                assert sorted(found) == expected_base
            for i in range(31):
                for mode in (['off', 'on'] if i % 2 == 0 else ['on', 'off']):
                    os.environ['FASTSEARCH_TELEMETRY'] = '1' if mode == 'on' else '0'
                    started = time.perf_counter()
                    assert sorted(T.invoke(fn, pos, kw).splitlines()) == sorted(expected.splitlines())
                    if i:
                        samples[mode].append((time.perf_counter() - started) * 1000)
                started = time.perf_counter()
                assert baseline() == expected_base
                if i:
                    samples['python_baseline'].append((time.perf_counter() - started) * 1000)
            results[name] = {'samples_ms': samples, 'summary': {k: {'p50_ms': statistics.median(v), 'p95_ms': sorted(v)[28]} for k, v in samples.items()}, 'same_results': True}
    Path(args.output).write_text(json.dumps({'conditions': '300 UTF-8 files, 31 lines each, warm runs; Python pathlib baseline, not PowerShell or task-level speedup', 'results': results}, indent=2), encoding='utf-8')
    print(json.dumps({k: v['summary'] for k, v in results.items()}, indent=2))


if __name__ == '__main__':
    main()
