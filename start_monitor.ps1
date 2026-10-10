# 闲鱼智能监控 - 一键启动器（桌面快捷方式双击运行）
# 作用：启动 Web 服务（未运行时）-> 挂 watchdog 守护 -> 自动打开浏览器进入监控页面
$ErrorActionPreference = 'SilentlyContinue'
$workDir = 'C:\Users\MrChen\Doubao\chats\2026-10-05\new-chat\ai-goofish-monitor'
Set-Location $workDir
$python = "$workDir\.venv\Scripts\python.exe"
$url = 'http://127.0.0.1:8000/dashboard'
$logDir = "$workDir\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
$log = "$logDir\launcher.log"
function WLog($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $log -Value $line -Encoding UTF8
}

function Wait-PortFree {
    # 等待 8000 端口不再 LISTENING（最多 20 秒），避免端口未释放导致启动失败
    for ($i = 0; $i -lt 20; $i++) {
        $l = netstat -ano | Select-String ':8000' | Select-String 'LISTENING'
        if (-not $l) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

WLog '=== 启动器开始 ==='

# 1) 服务未运行则启动（已运行则跳过）
# 健康检查重试 2 次，避免偶发慢响应导致误判重启正在运行的服务
$alive = $false
for ($try = 0; $try -lt 3; $try++) {
    try {
        $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $alive = $true; break }
    } catch {}
    Start-Sleep -Seconds 2
}
WLog ("服务已运行: {0}" -f $alive)

if (-not $alive) {
    # 服务确认不在时才清理残留并重启；避免与 watchdog 并发时互杀
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'run_server\.py|uvicorn src\.app:app' } | ForEach-Object {
        WLog ("杀掉残留 PID={0}" -f $_.ProcessId)
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
    Wait-PortFree | Out-Null
    # 关键：清除豆包客户端注入的沙箱 Python 环境变量（PYTHONPATH/PYTHONHOME），
    # 否则任务/续期等 python 子进程继承后 "Failed to import encodings" 崩溃
    $env:PYTHONPATH = ''
    $env:PYTHONHOME = ''
    $env:PYTHONSTARTUP = ''
    $errLog = "$logDir\uvicorn_err.log"
    $outLog = "$logDir\uvicorn_out.log"
    Start-Process -FilePath $python -ArgumentList "$workDir\run_server.py" -WorkingDirectory $workDir -WindowStyle Hidden -RedirectStandardError $errLog -RedirectStandardOutput $outLog
    WLog '已启动服务，等待就绪...'
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        try {
            $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        } catch {}
    }
    WLog ("服务就绪: {0}" -f $ready)
}

# 2) watchdog 守护未运行则挂一个（避免进程累积，先查再挂）
$wd = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'watchdog.ps1' }
if (-not $wd) {
    Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',"$workDir\watchdog.ps1" -WindowStyle Hidden
    WLog 'watchdog 已挂载'
} else {
    WLog 'watchdog 已存在，跳过'
}

# 3) 确保服务就绪后打开监控页面（无条件打开，失败则重试一次）
Start-Sleep -Seconds 1
$opened = $false
try {
    Start-Process $url
    $opened = $true
} catch {}
if (-not $opened) {
    Start-Sleep -Seconds 2
    try { Start-Process $url; $opened = $true } catch {}
}
WLog ("浏览器打开: {0} -> {1}" -f $opened, $url)
WLog '=== 启动器完成 ==='
