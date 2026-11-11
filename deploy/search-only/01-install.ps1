$ErrorActionPreference = 'Stop'
Get-Command uv -ErrorAction Stop | Out-Null
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) {
 uv venv (Join-Path $PSScriptRoot '.venv')
 if ($LASTEXITCODE -ne 0) { throw 'Environment creation failed.' }
}
uv pip install --python $python --reinstall-package fastsearch-mcp $PSScriptRoot
if ($LASTEXITCODE -ne 0) { throw 'Installation failed.' }
Write-Host 'MCP command path:'
Write-Host (Join-Path $PSScriptRoot '.venv/Scripts/fastsearch-mcp.exe')
