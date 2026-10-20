param([string]$Python = "python")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$ver = & $Python -c 'import sys; print(str(sys.version_info.major)+"."+str(sys.version_info.minor))'
if ($LASTEXITCODE -ne 0) { throw "无法运行 Python：$Python" }
if ($ver -ne '3.12') {
    throw "需要 Python 3.12.x，当前为 $ver。可用 -Python 指定 Python 3.12 可执行文件。"
}
& $Python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw "虚拟环境创建失败。请安装含 pip 的 Python 3.12。" }
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "依赖安装失败；检查网络/PyPI访问。" }
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
if (-not (Test-Path config/profile.json)) { Copy-Item config/profile.example.json config/profile.json }
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { throw "测试失败，不能启动。" }
Write-Host '安装完成。先运行 .\scripts\run.ps1 probe。'
