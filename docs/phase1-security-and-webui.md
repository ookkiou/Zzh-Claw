# ZzhClaw 第一批优化 + Web UI 开发记录

> 记录时间：2026-09-17
> 范围：第一批安全加固与 Bug 修复 + DeepSeek 风格 Web UI
> 文档目的：复盘问题与解决、沉淀知识点、准备面试问答

---

## 一、概述

本阶段完成两件事：

1. **第一批优化**：针对安全、Bug、健壮性的 7 项加固（LLM 重试、原子写、迭代上限、JSON 容错、危险命令拦截、gitignore 精确化、依赖版本上限）
2. **Web UI**：从零搭建 FastAPI + WebSocket 的浏览器界面，模仿 DeepSeek 风格，复用现有 Agent 核心

两者都遵循一个原则：**最小侵入式改动，复用现有架构**（Agent 回调解耦设计让 Web 端只是"又一种前端"）。

---

## 二、第一批：安全加固与 Bug 修复

### 2.1 改动清单

| 文件 | 改动 | 行变化 |
|------|------|--------|
| `zzhclaw/ai/client.py` | LLM 调用加 `max_retries` + `timeout`，支持 `.env` 覆盖 | +14 -1 |
| `zzhclaw/coding/session/manager.py` | `save_session` 改原子写；`list_sessions` 损坏文件不再静默吞异常 | +25 -5 |
| `zzhclaw/agent/core.py` | `while True` → `for range(max_iterations)`；`json.loads` 容错；`execute_tool` 兜底 | +35 -5 |
| `zzhclaw/coding/tools/registry.py` | 危险命令黑名单（13 条正则）+ `check_dangerous_command()` | +63 -3 |
| `requirements.txt` | 8 个依赖加版本上限；websockets 约束修正 | +9 -9 |
| `.gitignore` | `*.json` → 精确路径；补 `.venv-1/` | +6 -1 |
| `.env.example` | 补充 `OPENAI_MAX_RETRIES` / `OPENAI_TIMEOUT` | +4 -0 |

### 2.2 逐项详解

#### (1) LLM 重试与超时 — `client.py`

**问题**：原代码 `OpenAI(api_key, base_url)` 无任何容错，网络抖动或 429 直接抛异常给用户。

**解决**：
```python
max_retries = int(os.getenv("OPENAI_MAX_RETRIES", "3"))
timeout = float(os.getenv("OPENAI_TIMEOUT", "60"))
self.client = OpenAI(
    api_key=self.api_key, base_url=self.base_url,
    max_retries=max_retries, timeout=timeout,
)
```

**关键点**：openai SDK 内置 `max_retries`（基于 httpx），对 429/5xx/连接错误自动指数退避重试，无需引入 tenacity。

#### (2) 会话原子写 — `manager.py`

**问题**：原 `save_session` 直接 `open(filepath, "w")` 全量重写。若写到一半进程崩溃，会话文件损坏且无法恢复。

**解决**：tempfile + os.replace 原子写
```python
fd, tmp_path = tempfile.mkstemp(dir=self.storage_dir, prefix=f".{session.id}.", suffix=".json.tmp")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(session.to_dict(), f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())   # 强制刷盘，防断电丢失
    os.replace(tmp_path, filepath)  # POSIX 原子操作
except Exception:
    os.unlink(tmp_path)  # 失败清理临时文件
    raise
```

**关键点**：
- `os.replace` 在同文件系统内是原子的（POSIX `rename(2)` 语义），要么完全成功要么完全失败
- `fsync` 确保数据真正落盘，而非停留在 OS 缓存
- 临时文件与目标文件同目录，保证 `os.replace` 不跨文件系统

#### (3) Agent 迭代上限 + 容错 — `core.py`

**问题 A**：`while True` 无上限，模型陷入工具调用死循环会无限烧钱。
**问题 B**：`args = json.loads(tool_call.function.arguments)` 无 try，模型返回坏 JSON 直接崩溃。
**问题 C**：`execute_tool` 若抛未捕获异常，整个循环挂掉，且会话里缺 tool 结果导致 tool_call_id 配对损坏。

**解决**：
```python
for _ in range(max_iterations):  # 默认 20
    ...
    # JSON 容错：失败时把错误作为 tool result 回传，让模型自愈
    try:
        args = json.loads(raw_args)
        if not isinstance(args, dict):
            raise ValueError(f"预期 dict，实际 {type(args).__name__}")
    except (json.JSONDecodeError, ValueError) as e:
        err = f"工具参数解析失败: {e}; 原始参数: {raw_args!r}"
        self.session_manager.add_message("tool", err, tool_call_id=tool_call.id)
        continue
    # 工具执行兜底
    try:
        result = execute_tool(name, args)
    except Exception as e:
        result = f"工具执行异常: {type(e).__name__}: {e}"
```

**关键点**：错误信息作为 tool result 回传给模型，模型下一轮能看到错误并自我修正（自愈），而非直接崩溃。这依赖 OpenAI Function Calling 的 **tool_call_id 必须配对** 约束——每个 assistant 的 tool_calls 都必须有对应的 tool 结果消息。

#### (4) 危险命令黑名单 — `registry.py`

**问题**：`run_bash` 用 `shell=True` 直跑任意命令，`rm -rf /` 也会照做。即使有 confirm_tool，用户可能习惯性按 Y。

**解决**：13 条正则黑名单，命中直接拒绝（不依赖用户确认）：
```python
_DANGEROUS_PATTERNS = [
    (r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|...)[a-zA-Z]*\s+"
     r"(/(?=\s|$|;|&&|\||\*)"
     r"|~(?=/|\s|$|;|&&|\|)"
     r"|\$HOME(?=/|\s|$|;|&&|\|)"
     r"|/(etc|usr|var|bin|sbin|opt|System|Library|Applications|dev|proc|sys)(?=/|\s|$|;|&&|\|))",
     "rm -rf 系统关键路径"),
    (r"\bmkfs(\.\w+)?\b", "格式化磁盘"),
    (r"\bdd\s+[^|]*\bof=/dev/(sd|nvme|hd|disk|rdisk)", "dd 写入块设备"),
    (r"\b(curl|wget|fetch)\b[^|]*\|\s*(sudo\s+)?(ba|z|k|da)?sh\b", "远程脚本管道到 shell"),
    # ... 共 13 条
]
```

**设计克制点**：只拦截"针对系统关键路径的破坏"和"远程代码直接执行"，不拦截项目目录内的 `rm -rf ./build`、`rm -rf node_modules` 等正常操作。

### 2.3 遇到的问题与解决

#### 问题 1：危险命令正则边界 Bug

**现象**：第一版正则 `(\$HOME)(\s|$|;|&&|\|)` 漏拦截 `rm -rf $HOME/Documents`——因为 `$HOME` 后面是 `/`，不在结束字符集里。同样漏 `rm -rf ~/Documents`、`rm -rf /etc/passwd`。

**根因**：系统路径（`$HOME`、`~`、`/etc`）通常是**路径起点**，后面会跟 `/` 继续子路径，而单独的 `/`（根目录）后面必须是分隔符。

**解决**：用 **lookahead 断言** `(?=...)` 区分两种情况：
```python
r"/(?=\s|$|;|&&|\||\*)"           # 单独 / 后必须是分隔符或 *
r"|~(?=/|\s|$|;|&&|\|)"           # ~ 后允许跟 /（路径继续）
r"|\$HOME(?=/|\s|$|;|&&|\|)"      # $HOME 后允许跟 /
r"|/(etc|usr|...)(?=/|\s|$|;|&&|\|)"  # 系统目录后允许跟 /
```

**验证**：扩充到 24 条命中 + 13 条放行用例，最终 **0 漏拦截 / 0 误伤**。

**学到的**：正则的 **lookahead `(?=...)`** 是"断言后面是什么但不消耗字符"的利器，适合处理"同一模式在不同上下文有不同边界"的场景。比单纯扩展字符集更精确。

---

## 三、Web UI（DeepSeek 风格）

### 3.1 架构设计

```
浏览器 (HTML/CSS/JS)
    │ WebSocket (/ws)         │ REST (/api/sessions)
    ▼                         ▼
┌─────────────────────────────────────┐
│  FastAPI (server.py)                │
│  ├─ WebSocket 端点：每连接独立 Agent │
│  ├─ REST 端点：会话列表/增删改       │
│  └─ 静态文件：/static/*             │
└──────────────┬──────────────────────┘
               │ asyncio.to_thread
               ▼
┌─────────────────────────────────────┐
│  Agent 核心 (复用，零改动)           │
│  ├─ on_tool_call → WebSocket 消息    │
│  ├─ on_tool_result → WebSocket 消息  │
│  └─ confirm_tool → threading.Event   │
└─────────────────────────────────────┘
```

**核心思想**：Agent 的**回调解耦设计**在这里发挥价值——Web 端只是把回调从"打印到终端"换成"发 WebSocket 消息"，Agent 核心零改动。

### 3.2 文件清单与职责

| 文件 | 行数 | 职责 |
|------|------|------|
| `zzhclaw/web/__init__.py` | 8 | 模块导出 `create_app` / `run_web` |
| `zzhclaw/web/server.py` | 281 | FastAPI 后端：WebSocket + REST + 静态文件 |
| `zzhclaw/web/static/index.html` | 155 | 页面结构：侧边栏 + 聊天区 + 输入区 + 弹窗 |
| `zzhclaw/web/static/style.css` | 1009 | DeepSeek 风格：CSS 变量主题、深色/浅色、响应式 |
| `zzhclaw/web/static/app.js` | 648 | 前端逻辑：WebSocket、Markdown、工具确认、会话管理 |
| `zzhclaw.py`（改） | +21 | 加 `--mode web` + `--host/--port/--no-browser` |

### 3.3 关键技术点

#### (1) 同步 Agent 桥接到异步 WebSocket

**挑战**：`Agent.run()` 是同步阻塞的（内部调 openai 同步 SDK），但 FastAPI WebSocket 是异步的。回调（工具调用/结果/确认）需要在 Agent 执行过程中实时推送到浏览器。

**解决**：三层桥接
```python
# 1. asyncio.Queue 作为线程安全的事件通道
event_queue: asyncio.Queue = asyncio.Queue()
loop = asyncio.get_event_loop()

def enqueue(event):
    loop.call_soon_threadsafe(event_queue.put_nowait, event)  # 线程安全塞入

# 2. Agent 回调 → enqueue
def on_tool_call(name, args):
    enqueue({"type": "tool_call", "name": name, "args": args})

# 3. asyncio.to_thread 跑同步 Agent，后台 task 消费队列发 WebSocket
async def run_agent():
    response = await asyncio.to_thread(agent.run, user_input, on_tool_call=..., ...)
asyncio.create_task(run_agent())

async def event_sender():
    while True:
        event = await event_queue.get()
        if event is None: break  # 毒丸
        await ws.send_json(event)
```

**关键点**：
- `loop.call_soon_threadsafe` 是从**工作线程**安全调用**主事件循环**的唯一正确方式
- `asyncio.to_thread` 把同步阻塞函数放到线程池，不卡事件循环
- 毒丸（None）优雅终止 sender task

#### (2) 工具确认的跨线程同步

**挑战**：`confirm_tool(name, args) -> bool` 需要阻塞工作线程，等浏览器用户点"允许/取消"后再返回。

**解决**：`threading.Event`
```python
confirm_event = threading.Event()
confirm_result_holder = {"approved": False}

def confirm_tool(name, args):  # 工作线程
    confirm_event.clear()
    enqueue({"type": "confirm_request", "name": name, "args": args})
    confirm_event.wait()  # 阻塞，直到主线程 set
    return confirm_result_holder["approved"]

# 主线程收到客户端 confirm 消息
elif msg_type == "confirm":
    confirm_result_holder["approved"] = bool(data.get("approved"))
    confirm_event.set()  # 唤醒工作线程
```

**关键点**：用 dict 而非局部变量存结果，避免闭包陷阱；Event.wait() 阻塞工作线程但不卡事件循环。

#### (3) 每连接独立 Agent（多标签页安全）

```python
@app.websocket("/ws")
async def websocket_endpoint(ws):
    llm = LLMClient()
    sm = SessionManager()
    agent = Agent(llm, sm)  # 每个 WebSocket 连接独立实例
```

**关键点**：REST API 用共享 SessionManager（无状态的列表/删除），有状态的"当前会话"由每个连接自己维护，避免多标签页互相干扰。

#### (4) 前端流式渲染与交互

- **Markdown**：marked.js + highlight.js（代码高亮 + 语言标签 + 复制按钮）
- **WebSocket 自动重连**：onclose 后 3 秒重试 + toast 提示
- **心跳保活**：每 30 秒 ping，防代理超时断开
- **主题系统**：CSS 变量 + `data-theme` 属性 + localStorage 持久化
- **键盘快捷键**：Cmd+K 新建、Cmd+B 侧边栏、Cmd+Shift+L 主题、Esc 取消确认

### 3.4 遇到的问题与解决

#### 问题 1：create_app() 漏 return

**现象**：`AttributeError: 'NoneType' object has no attribute 'title'`。

**根因**：`create_app()` 函数末尾定义了 WebSocket 端点后直接结束，**忘了 `return app`**。

**解决**：函数末尾补 `return app`。

**教训**：工厂函数容易在定义完一堆嵌套路由后忘记 return。写完应立即跑导入冒烟测试。

#### 问题 2：WebSocket 库兼容性（最隐蔽的坑）

**现象**：服务启动后浏览器连不上 `/ws`，日志刷：
```
WARNING: Unsupported upgrade request.
WARNING: No supported WebSocket library detected.
```

**诊断过程**（四层递进）：
1. 确认 websockets 13.1 已装 → 排除"没装"
2. `from uvicorn.protocols.websockets import websockets_impl` → 成功但抛 DeprecationWarning，提示未来用 `websockets-sansio`
3. `hasattr(websockets, 'sansio')` → **False**（13.1 没有 sansio API）
4. `Config(app=None).ws` → `auto`（默认优先探测 sansio）

**根因**：uvicorn 0.53.0 默认 `ws="auto"`，优先探测新的 `websockets-sansio` 实现，该实现需要 **websockets 14+** 的 sansio API；13.1 只有 legacy API，auto 探测失败后**不优雅 fallback**，直接报"无可用库"。

**雪上加霜**：我写的 `requirements.txt` 约束 `websockets>=12.0,<14.0`，上限 `<14.0` 恰好排除了需要的 14+。

**解决**：
```bash
.venv/bin/python -m pip install "websockets>=14.0,<18.0"  # 13.1 → 17.1
```
```diff
- websockets>=12.0,<14.0
+ websockets>=14.0,<18.0
```

**教训**：
- uvicorn 在 WebSocket 实现过渡期（legacy → sansio），`auto` 探测不 fallback
- 依赖版本上限要查**上游对下游的实际 API 依赖**，不能只看当前稳定版拍脑袋

#### 问题 3：环境混淆（最坑用户的）

**现象**：修复后用户跑还是同样警告。

**诊断**：
```bash
lsof -i :8000          # 发现 PID 9110 占用
ps -p 9110 -o command  # 路径是 /Library/Frameworks/.../Python（系统 python3！）
python3 -c "import websockets"  # ModuleNotFoundError（系统 python3 没装）
```

**根因**：用户用**系统 python3** 启动（没激活 .venv，或开新终端忘了激活），系统 python3 有 fastapi/uvicorn（旧版）但**没 websockets**。我升级的是 .venv，对系统 python3 跑的进程毫无影响。旧进程 PID 9110 一直占着 8000 端口。

**解决**：
1. `kill 9110` 释放端口
2. 用 `.venv/bin/python zzhclaw.py --mode web` 重启
3. 验证 WebSocket 连接成功、ping/pong 正常

**教训**：
- venv 激活后开新终端窗口会失效，`python3` 又指向系统
- 最保险是用**绝对路径** `.venv/bin/python`，不依赖激活状态
- 排查环境问题先 `which python3` + `lsof -i :端口` 确认实际运行环境

---

## 四、我学到了什么

### 4.1 技术知识点

| 知识点 | 具体收获 |
|--------|---------|
| **原子文件写入** | tempfile.mkstemp + os.fdopen + fsync + os.replace 四步，POSIX rename 原子语义 |
| **正则 lookahead** | `(?=...)` 断言不消耗字符，处理"同模式不同上下文边界" |
| **Function Calling 配对约束** | tool_call_id 必须配对，错误也要回传 tool 结果让模型自愈 |
| **asyncio 线程桥接** | loop.call_soon_threadsafe 是工作线程→事件循环的唯一安全通道 |
| **asyncio.to_thread** | 同步阻塞函数放线程池，不卡事件循环 |
| **threading.Event 跨线程确认** | wait/set 阻塞工作线程但不卡事件循环，dict 存结果避闭包陷阱 |
| **uvicorn WebSocket 演进** | legacy → sansio，auto 探测优先新实现但不 fallback |
| **CSS 变量主题系统** | :root + [data-theme="dark"] 覆盖，一处定义全局生效 |
| **WebSocket 重连 + 心跳** | onclose 3 秒重试 + 30 秒 ping 防代理超时 |
| **依赖版本管理** | 上限要查上游 API 依赖，不能只看当前稳定版 |
| **venv 环境隔离** | which python3 + lsof 端口确认实际运行环境，绝对路径最保险 |

### 4.2 工程方法论

1. **冒烟测试分层**：导入检查 → 签名验证 → 纯函数测试 → 启动 + curl → WebSocket 连通性，每层最小命令验证
2. **诊断四层递进**：依赖是否装 → 实现能否加载 → API 是否存在 → 默认配置是什么
3. **最小侵入改动**：复用现有架构（Agent 回调解耦），新前端只换回调实现
4. **克制的安全策略**：黑名单只拦系统级破坏，不误伤项目内正常操作
5. **验证驱动**：每个修复都配测试用例（24 命中 + 13 放行），用数据说话

---

## 五、面试可能问的问题

### 5.1 安全相关

**Q1：你的危险命令黑名单是怎么设计的？为什么不用白名单？**

A：黑名单 13 条正则，覆盖 rm -rf 系统路径、mkfs、dd 写块设备、shutdown、fork 炸弹、chmod/chown -R /、curl|sh 远程执行、csrutil disable。设计克制：只拦系统级破坏，放行项目内 `rm -rf ./build` 等正常操作。

不用白名单是因为编码助手场景下命令多样性极高（git、npm、python、grep...），白名单会严重限制可用性。黑名单 + 用户确认（confirm_tool）双层防护更平衡：黑名单拦最危险的（不给误按 Y 机会），confirm_tool 让用户判断次危险的。

**Q2：正则边界 bug 是怎么发现和修复的？**

A：第一版 `(\$HOME)(\s|$|;|&&|\|)` 漏拦截 `rm -rf $HOME/Documents`，因为 `$HOME` 后是 `/` 不在结束集。根因是系统路径通常是路径起点会跟 `/`，而单独 `/`（根目录）后必须是分隔符。用 lookahead `(?=/|\s|$|;|&&|\|)` 区分：`~`/`$HOME`/系统目录后允许 `/`，单独 `/` 后不允许。扩充到 24 命中 + 13 放行用例验证，0 漏 0 误伤。

### 5.2 并发/异步相关

**Q3：同步的 Agent.run() 怎么桥接到异步 WebSocket？**

A：三层桥接。① asyncio.Queue 作事件通道，工作线程用 `loop.call_soon_threadsafe(queue.put_nowait, event)` 安全塞入（这是工作线程→事件循环的唯一正确方式，直接 put_nowait 会线程不安全）。② `asyncio.to_thread(agent.run, ...)` 把同步阻塞放线程池，不卡事件循环。③ 后台 `asyncio.create_task(event_sender())` 消费队列发 WebSocket，毒丸 None 优雅终止。

**Q4：工具确认怎么跨线程阻塞等待？**

A：threading.Event。工作线程 confirm_tool 里 `enqueue(确认请求)` 然后 `event.wait()` 阻塞；主事件循环收到客户端 confirm 消息后 `holder["approved"]=...; event.set()` 唤醒。用 dict 而非局部变量存结果避免闭包陷阱。Event.wait 阻塞工作线程但不卡事件循环，其他连接不受影响。

**Q5：为什么每个 WebSocket 连接要独立 Agent 实例？**

A：多标签页安全。有状态的"当前会话"由每连接自己的 SessionManager 维护，避免标签页 A 切换会话影响标签页 B。REST API（列表/删除）用共享 SessionManager 因为这些是无状态操作。会话文件共享存储在 `~/.zzhclaw/sessions/`，三端（CLI/TUI/Web）互通。

### 5.3 文件 IO 相关

**Q6：原子写具体怎么实现？为什么需要 fsync？**

A：四步：① `tempfile.mkstemp(dir=同目录)` 创建临时文件（同目录保证 os.replace 不跨文件系统）。② `os.fdopen(fd, "w")` 写数据 + `f.flush()`（用户态缓冲→内核）+ `os.fsync(f.fileno())`（内核→磁盘）。③ `os.replace(tmp, target)` POSIX 原子 rename。④ 异常时 `os.unlink(tmp)` 清理。

需要 fsync 是因为 flush 只到内核页缓存，断电会丢；fsync 强制落盘。不调 fsync 的话，os.replace 虽然原子但内容可能还是旧的（崩溃时）。

**Q7：os.replace 为什么是原子的？跨文件系统会怎样？**

A：os.replace 底层是 POSIX `rename(2)`，同文件系统内是原子操作（要么完全成功要么完全失败，不会看到中间状态）。跨文件系统 rename 会失败（EXDEV），因为不同文件系统的 inode 无法直接移动，需要复制+删除，这就不是原子的了。所以临时文件必须和目标同目录。

### 5.4 网络/WebSocket 相关

**Q8：uvicorn 的 WebSocket 库检测为什么会失败？**

A：uvicorn 0.53 默认 `ws="auto"`，优先探测新的 websockets-sansio 实现（需要 websockets 14+ 的 sansio API）。装的 13.1 只有 legacy API，`hasattr(websockets, 'sansio')` 为 False。auto 探测失败后不优雅 fallback 到 legacy，直接报"No supported WebSocket library"。升级 websockets 13.1→17.1 解决，同时修正 requirements.txt 上限 `<14.0`→`>=14.0,<18.0`。

**Q9：WebSocket 断线重连和心跳怎么做的？**

A：前端 `ws.onclose` 后 setTimeout 3 秒重连 + toast 提示用户。心跳每 30 秒发 ping，服务端回 pong，防止 Nginx 等代理因空闲超时断开连接。重连时会重新建立独立的 Agent 实例，但会话文件持久化所以历史不丢。

### 5.5 依赖管理相关

**Q10：依赖版本上限应该怎么定？**

A：不能只看当前稳定版拍脑袋。要查**上游对下游的实际 API 依赖**。比如 uvicorn 0.53 需要 websockets 14+ 的 sansio API，所以下限必须 >=14。上限设当前主版本+1（如 <18），允许次版本更新但防主版本破坏性变更。我第一版写 `<14.0` 就是只看了"当前装的 13.1 是稳定版"，没查 uvicorn 的 API 依赖，成了定时炸弹。

### 5.6 架构设计相关

**Q11：Web UI 怎么复用现有 Agent 核心？**

A：靠 Agent 的**回调解耦设计**。Agent.run() 接受三个回调（on_tool_call/on_tool_result/confirm_tool），不依赖具体 UI。CLI 端回调打印到终端，TUI 端用 post_message 发主线程，Web 端用 enqueue 发 WebSocket。三种前端共享同一份 Agent 核心，零改动。这是策略模式/依赖注入的体现：核心定义接口（回调签名），前端提供实现。

**Q12：如果让你重构，回调换成什么更好？**

A：生成器（yield 事件）。回调的缺点是扩展性差——加新事件类型（流式 token、进度、思考中）要改函数签名。生成器 `for event in agent.run_stream()` 更清晰，调用方用 match/case 分发，加事件类型不破坏接口。这也是第二批流式输出要做的改造。

---

## 六、附录

### 6.1 验证命令速查

```bash
# 确认环境（必须用 .venv）
which python3   # 应输出 .venv/bin/python3

# 危险命令拦截测试
.venv/bin/python -c "from zzhclaw.coding.tools.registry import check_dangerous_command; print(check_dangerous_command('rm -rf /'))"

# WebSocket 连通性
.venv/bin/python -c "
import asyncio, websockets, json
async def t():
    async with websockets.connect('ws://127.0.0.1:8000/ws') as ws:
        await ws.send(json.dumps({'type':'ping'}))
        print(await ws.recv())
asyncio.run(t())
"
```

### 6.2 启动命令

```bash
cd /Users/zzh/Documents/GitHub/zzhclaw
.venv/bin/python zzhclaw.py --mode web          # 自动开浏览器
.venv/bin/python zzhclaw.py --mode web --port 8765 --no-browser  # 自定义
```

### 6.3 相关文档

- [WebSocket 库兼容性问题详细排查](./fix-websocket-library-compatibility.md)
- [TUI 工具确认焦点丢失修复](../.trae/documents/fix-tui-confirm-input.md)（历史记录，.trae 被 gitignore）
