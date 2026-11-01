"""
zzhclaw.web.server - FastAPI 后端

设计要点：
- 每个 WebSocket 连接拥有独立的 Agent + SessionManager 实例（多标签页安全）
- Agent.run() 是同步阻塞的，用 asyncio.to_thread 放到线程池跑
- 回调通过 asyncio.Queue 桥接到 WebSocket 消息
- confirm_tool 用 threading.Event 等待客户端响应
"""

import os
import json
import asyncio
import threading
from typing import Dict, Any, Optional, List
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ..ai import LLMClient
from ..agent import Agent
from ..coding.session import SessionManager
from ..coding.tools import (
    set_cwd, get_cwd, set_sandbox,
    list_skills, load_skill, create_skill, get_skills_dirs,
)


# ===== Pydantic 模型 =====
class SessionCreate(BaseModel):
    name: Optional[str] = None


class SessionRename(BaseModel):
    name: str


class ChatMessage(BaseModel):
    message: str


# ===== 应用工厂 =====
def create_app() -> FastAPI:
    app = FastAPI(title="ZzhClaw Web UI", version="1.0.0")

    # 静态文件
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # 主页
    @app.get("/")
    async def index():
        return FileResponse(str(static_dir / "index.html"))

    # ===== REST API: 会话管理 =====
    # 注意：REST API 使用一个共享的 SessionManager（仅用于列表/删除等无状态操作）
    # 有状态的"当前会话"由每个 WebSocket 连接自己维护
    shared_sm = SessionManager()

    @app.get("/api/sessions")
    async def list_sessions():
        return JSONResponse(shared_sm.list_sessions())

    @app.post("/api/sessions")
    async def create_session(body: SessionCreate):
        session = shared_sm.create_session(body.name)
        shared_sm.save_session()
        return {"id": session.id, "name": session.name}

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str):
        ok = shared_sm.delete_session(session_id)
        if not ok:
            raise HTTPException(404, "会话不存在")
        return {"ok": True}

    @app.patch("/api/sessions/{session_id}")
    async def rename_session(session_id: str, body: SessionRename):
        # 加载 -> 改名 -> 保存
        session = shared_sm.load_session(session_id)
        if not session:
            raise HTTPException(404, "会话不存在")
        session.name = body.name
        shared_sm.save_session()
        return {"ok": True}

    @app.get("/api/sessions/{session_id}/messages")
    async def get_session_messages(session_id: str):
        session = shared_sm.load_session(session_id)
        if not session:
            raise HTTPException(404, "会话不存在")
        # 返回当前分支的消息（简化：只返回 role/content/timestamp）
        msgs = []
        for m in session.current_branch.messages:
            msgs.append({
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp,
                "tool_calls": m.tool_calls,
                "tool_call_id": m.tool_call_id,
            })
        return {"session_id": session_id, "name": session.name, "messages": msgs}

    # ===== WebSocket: 聊天 =====
    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()

        # 每个连接独立的 Agent + SessionManager
        llm = LLMClient()
        sm = SessionManager()
        agent = Agent(llm, sm)

        # 确认机制：threading.Event + 结果存储
        confirm_event = threading.Event()
        confirm_result_holder: Dict[str, bool] = {"approved": False}

        # 事件队列：工作线程 -> asyncio 主线程
        event_queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def enqueue(event: Dict[str, Any]):
            """线程安全地把事件塞进 asyncio 队列"""
            loop.call_soon_threadsafe(event_queue.put_nowait, event)

        # Agent 回调 -> WebSocket 事件
        def on_tool_call(name: str, args: Dict):
            enqueue({"type": "tool_call", "name": name, "args": args})

        def on_tool_result(name: str, result: str):
            # 截断过长结果（前端可展开）
            display = result[:2000] + "..." if len(result) > 2000 else result
            enqueue({"type": "tool_result", "name": name, "result": display, "full_length": len(result)})

        def on_token(delta: str):
            """流式 token：实时推送到前端打字机渲染"""
            enqueue({"type": "token", "content": delta})

        def confirm_tool(name: str, args: Dict) -> bool:
            """阻塞工作线程，等待客户端通过 WebSocket 发送确认"""
            confirm_event.clear()
            confirm_result_holder["approved"] = False
            enqueue({"type": "confirm_request", "name": name, "args": args})
            confirm_event.wait()  # 阻塞直到客户端响应
            return confirm_result_holder["approved"]

        # 发送队列事件的后台任务
        async def event_sender():
            try:
                while True:
                    event = await event_queue.get()
                    if event is None:  # 毒丸，退出
                        break
                    await ws.send_json(event)
            except Exception:
                pass

        sender_task = asyncio.create_task(event_sender())

        # 告知前端当前权限模式（初始化顶部栏切换器显示）
        await ws.send_json({"type": "permission_mode", "mode": agent.permission_mode})

        try:
            while True:
                data = await ws.receive_json()
                msg_type = data.get("type")

                if msg_type == "chat":
                    user_input = data.get("message", "").strip()
                    if not user_input:
                        continue

                    # 斜杠命令处理（与 CLI/TUI 一致）
                    if user_input.startswith("/"):
                        parts = user_input.split(maxsplit=1)
                        cmd = parts[0][1:].lower()
                        arg = parts[1].strip() if len(parts) > 1 else ""

                        if cmd == "cd":
                            if not arg:
                                await ws.send_json({"type": "system_message", "content": f"当前工作目录: {get_cwd()}"})
                            else:
                                result = set_cwd(arg)
                                await ws.send_json({"type": "system_message", "content": result})
                            continue

                        elif cmd == "sandbox":
                            from ..coding.tools.registry import _WORKSPACE
                            if not arg:
                                state = "开启" if _WORKSPACE["sandbox"] else "关闭"
                                await ws.send_json({"type": "system_message", "content": f"写沙箱当前: {state}（用法: /sandbox on|off）"})
                            elif arg.lower() in ("on", "true", "1"):
                                set_sandbox(True)
                                await ws.send_json({"type": "system_message", "content": "写沙箱已开启：write_file 只能写工作目录内"})
                            elif arg.lower() in ("off", "false", "0"):
                                set_sandbox(False)
                                await ws.send_json({"type": "system_message", "content": "⚠️ 写沙箱已关闭：write_file 可写任意路径（谨慎）"})
                            else:
                                await ws.send_json({"type": "system_message", "content": "用法: /sandbox on|off"})
                            continue

                        elif cmd in ("help", "h"):
                            help_text = (
                                "可用命令:\n"
                                "  /cd [path]        - 查看/切换工作目录\n"
                                "  /sandbox <on|off> - 开关写沙箱\n"
                                "  /permission [mode] - 查看/切换权限模式 (confirm|smart|auto)\n"
                                "  /auto             - 一键切换全自动模式\n"
                                "  /skills           - 列出可用 skill（项目级+全局级）\n"
                                "  /skill new <name> [--global] - 创建 skill 模板\n"
                                "  /skill <name>     - 预览指定 skill 内容\n"
                                "  /help             - 显示本帮助\n"
                                "会话管理请用左侧边栏（新建/切换/重命名/删除）。"
                            )
                            await ws.send_json({"type": "system_message", "content": help_text})
                            continue

                        elif cmd == "save":
                            agent.save()
                            await ws.send_json({"type": "system_message", "content": "会话已保存"})
                            continue

                        elif cmd in ("permission", "perm"):
                            desc = {"confirm": "每个工具都确认", "smart": "只读自动，写/执行确认", "auto": "全自动，不再询问"}
                            if not arg:
                                cur = agent.permission_mode
                                await ws.send_json({"type": "system_message", "content": f"当前权限模式: {cur}（{desc[cur]}）\n用法: /permission confirm|smart|auto，或 /auto 一键全自动"})
                            else:
                                result = agent.set_permission_mode(arg.lower())
                                await ws.send_json({"type": "permission_mode", "mode": result})
                                if result == arg.lower():
                                    await ws.send_json({"type": "system_message", "content": f"权限模式已切换: {result}（{desc[result]}）"})
                                else:
                                    await ws.send_json({"type": "system_message", "content": f"无效模式: {arg}（可选 confirm|smart|auto）"})
                            continue

                        elif cmd == "auto":
                            agent.set_permission_mode("auto")
                            await ws.send_json({"type": "permission_mode", "mode": "auto"})
                            await ws.send_json({"type": "system_message", "content": "✅ 已切换全自动模式：agent 将自主执行所有工具\n仍受危险命令黑名单 + 写沙箱保护；恢复确认请输入 /permission confirm"})
                            continue

                        elif cmd == "skills":
                            skills = list_skills()
                            if not skills:
                                dirs = "、".join(d["path"] for d in get_skills_dirs())
                                await ws.send_json({"type": "system_message", "content": f"没有可用 skill（已扫描: {dirs}）\n用 /skill new <name> 在项目里创建一个"})
                            else:
                                lines = ["可用 skill:"]
                                for s in skills:
                                    lines.append(f"  [{s['scope']}] {s['name']}: {s['description'] or '（无描述）'}")
                                await ws.send_json({"type": "system_message", "content": "\n".join(lines)})
                            continue

                        elif cmd == "skill":
                            sparts = arg.split()
                            if sparts and sparts[0].lower() == "new":
                                if len(sparts) < 2:
                                    await ws.send_json({"type": "system_message", "content": "用法: /skill new <name> [--global]"})
                                else:
                                    scope = "global" if "--global" in sparts[2:] else "project"
                                    _, msg = create_skill(sparts[1], scope)
                                    await ws.send_json({"type": "system_message", "content": msg})
                            elif sparts:
                                await ws.send_json({"type": "system_message", "content": load_skill(sparts[0])})
                            else:
                                await ws.send_json({"type": "system_message", "content": "用法: /skills 列出 | /skill new <name> [--global] 创建 | /skill <name> 预览"})
                            continue

                        else:
                            await ws.send_json({"type": "system_message", "content": f"未知命令: /{cmd}（输入 /help 查看可用命令）"})
                            continue

                    # 确保有会话
                    if not sm.current_session:
                        agent.new_session("Web 会话")
                        await ws.send_json({
                            "type": "session_created",
                            "session_id": sm.current_session.id,
                            "name": sm.current_session.name,
                        })

                    # 在线程池里跑 Agent.run（同步阻塞）
                    async def run_agent():
                        try:
                            response = await asyncio.to_thread(
                                agent.run,
                                user_input,
                                on_tool_call=on_tool_call,
                                on_tool_result=on_tool_result,
                                confirm_tool=confirm_tool,
                                on_token=on_token,
                            )
                            await ws.send_json({
                                "type": "assistant_message",
                                "content": response,
                                "session_id": sm.current_session.id if sm.current_session else None,
                            })
                        except Exception as e:
                            await ws.send_json({"type": "error", "message": str(e)})

                    asyncio.create_task(run_agent())

                elif msg_type == "confirm":
                    # 客户端响应工具确认
                    confirm_result_holder["approved"] = bool(data.get("approved", False))
                    confirm_event.set()

                elif msg_type == "load_session":
                    session_id = data.get("session_id")
                    if agent.load_session(session_id):
                        sess = sm.current_session
                        msgs = []
                        for m in sess.current_branch.messages:
                            if m.role == "system":
                                continue  # 不展示 system prompt
                            msgs.append({
                                "role": m.role,
                                "content": m.content,
                                "timestamp": m.timestamp,
                                "tool_calls": m.tool_calls,
                                "tool_call_id": m.tool_call_id,
                            })
                        await ws.send_json({
                            "type": "session_loaded",
                            "session_id": sess.id,
                            "name": sess.name,
                            "messages": msgs,
                        })
                    else:
                        await ws.send_json({"type": "error", "message": f"无法加载会话 {session_id}"})

                elif msg_type == "new_session":
                    name = data.get("name") or None
                    agent.new_session(name)
                    sess = sm.current_session
                    await ws.send_json({
                        "type": "session_created",
                        "session_id": sess.id,
                        "name": sess.name,
                    })

                elif msg_type == "save_session":
                    agent.save()
                    await ws.send_json({"type": "saved"})

                elif msg_type == "set_permission":
                    # 顶部栏切换器点击：设置权限模式
                    mode = data.get("mode", "")
                    result = agent.set_permission_mode(mode)
                    await ws.send_json({"type": "permission_mode", "mode": result})

                elif msg_type == "ping":
                    await ws.send_json({"type": "pong"})

        except WebSocketDisconnect:
            pass
        except Exception as e:
            try:
                await ws.send_json({"type": "error", "message": f"WebSocket 异常: {e}"})
            except Exception:
                pass
        finally:
            # 清理：保存会话、停止 sender
            try:
                if sm.current_session:
                    sm.save_session()
            except Exception:
                pass
            event_queue.put_nowait(None)  # 毒丸
            sender_task.cancel()

    return app


# ===== 启动入口 =====
def run_web(host: str = "127.0.0.1", port: int = 8000, open_browser: bool = True):
    """启动 Web UI"""
    import uvicorn
    import webbrowser

    app = create_app()

    if open_browser:
        # 延迟打开浏览器，等服务起来
        def _open():
            import time
            time.sleep(1.5)
            webbrowser.open(f"http://{host}:{port}")
        threading.Thread(target=_open, daemon=True).start()

    print(f"\n🌐 ZzhClaw Web UI 启动中...")
    print(f"   地址: http://{host}:{port}")
    print(f"   按 Ctrl+C 停止\n")

    uvicorn.run(app, host=host, port=port, log_level="warning")
