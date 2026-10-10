$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$logDirectory = Join-Path $projectRoot 'logs'
# Bạn học mẫu và nút "Vào thử"; tiến trình backend kế thừa biến này.
if (-not $env:DEMO_MODE) { $env:DEMO_MODE = 'true' }
New-Item -ItemType Directory -Force $logDirectory | Out-Null

if (-not (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath (Join-Path $projectRoot 'backend/.venv/Scripts/python.exe') `
        -ArgumentList '-X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8000' `
        -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDirectory 'backend.out.log') `
        -RedirectStandardError (Join-Path $logDirectory 'backend.err.log')
}

if (-not (Get-NetTCPConnection -State Listen -LocalPort 3001 -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath $env:ComSpec -ArgumentList '/c npm.cmd exec -- next dev -p 3001' `
        -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDirectory 'frontend.out.log') `
        -RedirectStandardError (Join-Path $logDirectory 'frontend.err.log')
}

Write-Host 'Web: http://localhost:3001'
Write-Host 'API: http://127.0.0.1:8000/docs'
Write-Host "Startup logs: $logDirectory"
