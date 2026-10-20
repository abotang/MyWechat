$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
exit $LASTEXITCODE
