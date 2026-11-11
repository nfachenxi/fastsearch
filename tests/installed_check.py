"""Verify the installed launcher (first fastsearch-mcp on PATH, or argv[1]), using an isolated telemetry database."""
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
import sqlite3
import tempfile
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from fastsearch_mcp import __version__

LAUNCHER = sys.argv[1] if len(sys.argv) > 1 else shutil.which('fastsearch-mcp')

async def main():
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
        env=dict(os.environ, FASTSEARCH_TELEMETRY_DIR=tmp, FASTSEARCH_ALLOWED_ROOTS=tmp)
        sample=Path(tmp)/'sample.txt'
        sample.write_text('needle', encoding='utf-8')
        params=StdioServerParameters(command=LAUNCHER, env=env)
        async with stdio_client(params) as (r,w):
            async with ClientSession(r,w) as session:
                await session.initialize()
                assert 'decompile' in {t.name for t in (await session.list_tools()).tools}
                for tool,args in [('tree',{'path':tmp}),('find_files',{'path':tmp,'pattern':'*.txt'}),('search_text',{'path':str(sample),'pattern':'needle'}),('count_matches',{'path':str(sample),'pattern':'needle'}),('read_lines',{'path':str(sample)})]:
                    result=await session.call_tool(tool,args)
                    assert not result.content[0].text.startswith('ERROR:')
        db=sqlite3.connect(Path(tmp)/'usage.sqlite3')
        rows=[json.loads(r[0]) for r in db.execute('SELECT data FROM calls')]
        db.close()
        assert len(rows)==5 and all(r['version']==__version__ for r in rows), {r['version'] for r in rows}
        print(f'Installed MCP launcher {LAUNCHER}: six tools listed, five read tools recorded successfully, version {__version__}')

asyncio.run(main())
