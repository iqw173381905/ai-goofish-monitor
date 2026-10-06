# 闲鱼智能监控 - 一键启动器（桌面快捷方式双击运行）
# 作用：启动 Web 服务（未运行时）-> 挂 watchdog 守护 -> 打开监控页面
$workDir = 'C:\Users\MrChen\Doubao\chats\2026-10-05\new-chat\ai-goofish-monitor'
Set-Location $workDir
$pyw = "$workDir\.venv\Scripts\pythonw.exe"
$url = 'http://127.0.0.1:8000/dashboard'

# 1) 服务未运行则启动
$alive = $false
try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 3
    if ($r.StatusCode -eq 200) { $alive = $true }
} catch { $alive = $false }

if (-not $alive) {
    # 清掉可能残留的 uvicorn 进程，避免端口冲突
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'uvicorn src.app:app' } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
    if (-not (Test-Path $pyw)) { $pyw = "$workDir\.venv\Scripts\python.exe" }
    Start-Process -FilePath $pyw -ArgumentList '-m','uvicorn','src.app:app','--host','127.0.0.1','--port','8000' -WindowStyle Hidden
    # 最多等 60 秒就绪
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        try {
            $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { break }
        } catch {}
    }
}

# 2) watchdog 守护未运行则挂一个（避免进程累积，先查再挂）
$wd = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'watchdog.ps1' }
if (-not $wd) {
    Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',"$workDir\watchdog.ps1" -WindowStyle Hidden
}

# 3) 打开监控页面
try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 3
    if ($r.StatusCode -eq 200) { Start-Process $url }
} catch {
    Start-Process $url
}
