"""
zzhclaw.web - Web UI (FastAPI + WebSocket)
模仿 DeepSeek 风格的浏览器界面
"""

from .server import create_app, run_web

__all__ = ["create_app", "run_web"]
