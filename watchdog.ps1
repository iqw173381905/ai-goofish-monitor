# 闲鱼智能监控 - 守护进程（由启动器挂载，后台持续运行）
# 作用：周期性健康检查，服务异常时自动恢复（先等端口释放再启动，避免端口冲突连环失败）；
#       服务输出重定向到 logs\uvicorn_err.log，崩溃时留下 traceback 便于排查
$workDir = 'C:\Users\MrChen\Doubao\chats\2026-10-05\new-chat\ai-goofish-monitor'
Set-Location $workDir
$python = "$workDir\.venv\Scripts\python.exe"
$pythonw = "$workDir\.venv\Scripts\pythonw.exe"
$logDir = "$workDir\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
$wdLog = "$workDir\watchdog.log"
$errLog = "$logDir\uvicorn_err.log"
$outLog = "$logDir\uvicorn_out.log"

function WLog($m) {
    Add-Content -Path $wdLog -Value ("[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m) -Encoding UTF8
}

function Test-Health {
    # 最多重试 3 次，避免偶发慢响应被误判为服务死亡
    for ($i = 0; $i -lt 3; $i++) {
        try {
            $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -eq 200) { return $true }
        } catch {}
        Start-Sleep -Seconds 3
    }
    return $false
}

function Wait-PortFree {
    # 等待 8000 端口不再 LISTENING（最多 20 秒）
    for ($i = 0; $i -lt 20; $i++) {
        $l = netstat -ano | Select-String ':8000' | Select-String 'LISTENING'
        if (-not $l) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Start-Server {
    Wait-PortFree | Out-Null
    # 用 python.exe 隐藏窗口 + 输出重定向运行 run_server.py。
    # 说明：run_server.py 已禁用 uvicorn 日志（Windows 无控制台环境下
    # uvicorn 写日志会触发 buffer detached 崩溃）；重定向 stdout/stderr 到日志文件，
    # 应用 print 正常落盘，崩溃时也能留下 traceback。
    $p = Start-Process -FilePath $python -ArgumentList "$workDir\run_server.py" -WorkingDirectory $workDir -WindowStyle Hidden -RedirectStandardError $errLog -RedirectStandardOutput $outLog -PassThru
    WLog ("启动服务 PID={0}" -f $p.Id)
    # 等端口监听（最多 40 秒）
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Seconds 1
        $l = netstat -ano | Select-String ':8000' | Select-String 'LISTENING'
        if ($l) { return $true }
    }
    return $false
}

WLog '=== 守护进程启动 ==='
while ($true) {
    if (Test-Health) {
        Start-Sleep -Seconds 20
        continue
    }
    WLog 'health 检测失败，开始恢复...'
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'run_server\.py|uvicorn src\.app:app' } | ForEach-Object {
        WLog ("杀掉残留 PID={0}" -f $_.ProcessId)
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 3
    $ok = Start-Server
    if ($ok) {
        WLog '服务已监听 8000'
        Start-Sleep -Seconds 15
    } else {
        WLog '服务启动失败（端口未监听），30 秒后重试'
        Start-Sleep -Seconds 30
    }
}
