"""Manual browser acceptance: uv run --with playwright python tests/browser_check.py."""
from pathlib import Path
from datetime import datetime, timezone
import os
import tempfile
from playwright.sync_api import sync_playwright
from fastsearch_mcp import telemetry as T
from fastsearch_mcp.report import write_report

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(dir=root) as tmp:
    os.environ['FASTSEARCH_TELEMETRY_DIR'] = tmp
    for i in range(60):
        T.save(dict(id=str(i), timestamp='2026-11-09T00:00:00+00:00',
                    tool='tree' if i % 2 else 'search_text', path='D:/测试/<script>/',
                    duration_ms=i+1, status='error' if i == 0 else 'ok',
                    timed_out=False, display_limited=False, output_bytes=100))
    report = write_report(Path(tmp) / 'check.html', days=3650)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
        page = browser.new_page(viewport={'width': 1360, 'height': 1000})
        errors=[]
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(report.as_uri())
        assert page.locator('#rows tr').count() == 12, (errors, page.locator('body').inner_text()[:800])
        assert page.locator('#cards').inner_text().find('30.0 / 57.0') >= 0
        page.locator('#next').click()
        assert page.locator('#rows tr').count() == 12
        page.locator('#tool').select_option('tree')
        assert page.locator('#rows tr').count() == 12
        page.locator('#tool').select_option('')
        page.locator('#status').select_option('error')
        assert page.locator('#rows tr').count() == 1
        page.locator('#status').select_option('')
        page.locator('#from').fill('2026-11-10')
        assert page.locator('#rows tr').count() == 0
        page.locator('#from').fill('')
        page.locator('#sort').select_option('slow')
        assert '60.0 ms' in page.locator('#rows tr').first.inner_text()
        page.locator('#rows summary').first.click()
        assert not errors, errors
        page.locator('#rows summary').first.click()
        page.screenshot(path=str(root / 'reports' / 'panel-verification.png'), full_page=True)
        page.locator('#metric').select_option('latency')
        assert page.locator('#chart circle').count() == 1
        page.locator('#issues button').first.click()
        assert page.locator('#rows tr').count() == 1
        page.locator('#status').select_option('')
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path=str(root / 'reports' / 'panel-mobile.png'), full_page=True)
        assert not errors, errors
        browser.close()
print('Browser acceptance passed: filters, nearest-rank percentiles, pagination, sorting, details, no script errors.')
