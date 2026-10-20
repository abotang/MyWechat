$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path .venv/Scripts/python.exe)) { throw '请先运行 scripts/setup.ps1' }
& .\.venv\Scripts\python.exe -m mywechat @args
exit $LASTEXITCODE
