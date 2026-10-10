# -*- coding: utf-8 -*-
"""
闲鱼监控 Web 服务启动入口（Windows 隐藏窗口运行专用）。
"""
import os

# 关键：清除豆包客户端注入的沙箱 Python 环境变量。
# 否则服务进程 spawn 的任务/续期等 python 子进程会继承它们，
# 新解释器启动时 "Failed to import encodings" 直接崩溃（日志尾部常见 Fatal Python error）。
for _var in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
    os.environ.pop(_var, None)

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
