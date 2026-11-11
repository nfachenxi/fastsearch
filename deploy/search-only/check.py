import asyncio
import os
from pathlib import Path
import sys
import tempfile
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
        sample = Path(temp) / 'sample.txt'
        sample.write_text('needle' + chr(10) + 'tail', encoding='utf-8')
        env = dict(os.environ, FASTSEARCH_ALLOWED_ROOTS=str(Path(temp)/'legacy-root'), FASTSEARCH_TELEMETRY_DIR=str(Path(temp)/'unused-log'))
        params = StdioServerParameters(command=sys.executable, args=['-m','fastsearch_mcp'], env=env)
        async with stdio_client(params) as (r,w):
            async with ClientSession(r,w) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                assert {t.name for t in tools} == {'tree','find_files','search_text','count_matches','read_lines','decompile'}
                assert all('MUST use' in t.description for t in tools)
                assert all(len(t.description) < 1000 for t in tools)
                for tool,args in [('tree',{'path':temp}),('find_files',{'path':temp,'pattern':'*.txt'}),('search_text',{'path':str(sample),'pattern':'needle'}),('count_matches',{'path':str(sample),'pattern':'needle'}),('read_lines',{'path':str(sample)})]:
                    result = await session.call_tool(tool,args)
                    assert not result.model_dump(by_alias=True)['isError'], result
                result = await session.call_tool('search_text', {'path':temp, 'pattern':'needle', 'output':'files', 'max_output_chars':1024})
                assert not result.model_dump(by_alias=True)['isError'] and 'sample.txt' in result.content[0].text
                result = await session.call_tool('read_lines', {'path':str(sample), 'start':1, 'end':1, 'count_total':False})
                assert not result.model_dump(by_alias=True)['isError'] and 'has_more=true' in result.content[0].text
                result = await session.call_tool('find_files', {'path':str(Path(__file__).parent), 'pattern':'**/fastsearch_mcp/server.py', 'full_path':True})
                assert not result.model_dump(by_alias=True)['isError'] and 'server.py' in result.content[0].text
                result = await session.call_tool('read_lines', {'path':str(Path(temp)/'missing.txt')})
                assert result.model_dump(by_alias=True)['isError'], result
                assert 'path_missing' in result.content[0].text
                result = await session.call_tool('decompile', {'dll':str(sample)})
                assert result.model_dump(by_alias=True)['isError'] and 'not_dll' in result.content[0].text
        assert not (Path(temp)/'unused-log').exists()
        import fastsearch_mcp.decompile as D
        assert D.find_ilspycmd() == str(D.BUNDLED), 'bundled ilspycmd missing: ' + D.find_ilspycmd()
        print('PASS: six MCP tools; bundled ilspycmd; compact rules; files search; fast read; path glob; error flag; no usage log created.')

asyncio.run(main())
