param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'First create .venv and install backend requirements. See README.md.'
}
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'frontend\dist\index.html'))) {
    throw 'First build the frontend. See README.md.'
}
& $pythonPath -m alembic -c backend/alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
& $pythonPath -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port $Port
