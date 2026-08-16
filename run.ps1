$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host ''
Write-Host '正在啟動 AniTrack 動漫追蹤 ...'
Write-Host '服務位址: http://127.0.0.1:8000  (關閉本視窗即停止)'
Write-Host ''

$job = Start-Job -ScriptBlock {
    Start-Sleep -Seconds 2
    try {
        $null = Invoke-WebRequest -Uri 'http://127.0.0.1:8000' -UseBasicParsing -TimeoutSec 8
    } catch {}
    Start-Process 'http://127.0.0.1:8000'
}

& "$root\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

Stop-Job $job -ErrorAction SilentlyContinue
Remove-Job $job -Force -ErrorAction SilentlyContinue
Write-Host ''
Write-Host '服務已停止。'
Read-Host '按 Enter 結束'