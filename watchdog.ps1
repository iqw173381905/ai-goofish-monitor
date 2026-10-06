$workDir = 'C:\Users\MrChen\Doubao\chats\2026-10-05\new-chat\ai-goofish-monitor'
$exe = "$workDir\.venv\Scripts\python.exe"
Set-Location $workDir
while ($true) {
    $alive = $false
    try {
        $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $alive = $true }
    } catch { $alive = $false }
    if (-not $alive) {
        Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'uvicorn src.app:app' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 2
        $p = Start-Process -FilePath $exe -ArgumentList '-m','uvicorn','src.app:app','--host','127.0.0.1','--port','8000' -WindowStyle Hidden -PassThru
        Add-Content "$workDir\watchdog.log" ("[{0}] 重启服务 PID={1}" -f (Get-Date -Format 'HH:mm:ss'), $p.Id)
        Start-Sleep -Seconds 20
    } else {
        Start-Sleep -Seconds 15
    }
}