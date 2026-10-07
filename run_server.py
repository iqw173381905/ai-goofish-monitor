# -*- coding: utf-8 -*-
"""
闲鱼监控 Web 服务启动入口（Windows 隐藏窗口运行专用）。

为什么不用 `pythonw -m uvicorn ...`：
Windows 下 pythonw 无控制台，uvicorn 的 access/error 日志写入无效 stdout/stderr
会触发 "underlying buffer has been detached"，异常抛进事件循环导致服务崩溃。

为什么直接传 app 对象而不是 "src.app:app" 字符串：
uvicorn 用字符串导入时会在 Windows 上 spawn 子进程运行服务器（进程树多一层、
守护/启动脚本杀进程时易残留子进程）。直接传 app 对象 → 单进程运行，便于守护管理。

本入口：
1. 在导入 app 前禁用 uvicorn 全部 logger（access/error/启动横幅）；
2. 以 log_config=None 启动 uvicorn —— 跳过 uvicorn 默认的 logging 配置
   （否则 dictConfig 会重置并重新启用 logger，禁用失效）；
3. access_log=False 双保险关闭访问日志。
应用自身的日志/print 不受影响（任务日志走文件）。
"""
import logging

for _logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error", "uvicorn.asgi"):
    _logger = logging.getLogger(_logger_name)
    _logger.handlers = []
    _logger.propagate = False
    _logger.disabled = True

import uvicorn
from src.app import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_config=None,
        access_log=False,
    )
