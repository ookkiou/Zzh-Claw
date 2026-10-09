# 修复 Web UI WebSocket 库兼容性问题

## 问题现象

启动 Web UI 后，浏览器无法建立 WebSocket 连接，服务端日志反复刷出警告：

```
WARNING:  Unsupported upgrade request.
WARNING:  No supported WebSocket library detected. Please use "pip install 'uvicorn[standard]'", or install 'websockets' or 'wsproto' manually.
```

前端表现为：右上角 toast 提示"连接断开，3 秒后重连..."，循环往复，无法对话。

## 环境信息

| 组件 | 版本 |
|------|------|
| OS | macOS (darwin 27.0) |
| Python | 3.14.3 |
| uvicorn | 0.53.0 |
| fastapi | 0.141.1 |
| websockets | **13.1**（问题版本） |

## 诊断过程

### 第一步：确认依赖已安装

`websockets 13.1` 确实装在 `.venv` 里，`uvicorn[standard]` 的 extra 也解析了。排除"没装"的可能。

### 第二步：检查 uvicorn 的 WebSocket 实现加载

```python
from uvicorn.protocols.websockets import websockets_impl
# ✅ 导入成功，但抛出 UvicornDeprecationWarning：
# The `websockets` implementation is deprecated, and `--ws websockets`
# will point at the `websockets-sansio` implementation in a future release.
```

关键线索：uvicorn 0.53.0 把旧的 `websockets` 实现标记为 **deprecated**，默认想用新的 `websockets-sansio` 实现。

### 第三步：检查 sansio 实现的依赖

```python
from uvicorn.protocols.websockets import websockets_sansio_impl
# ✅ 模块存在

import websockets
print(hasattr(websockets, 'sansio'))   # ❌ False（13.1 没有 sansio API）
print(hasattr(websockets, 'asyncio'))  # True（但非 sansio 所需）
```

确认：`websockets-sansio` 实现需要 **websockets 14+** 才有的 `sansio` API，而当前 13.1 没有。

### 第四步：检查 uvicorn 默认 ws 协议

```python
from uvicorn.config import Config
c = Config(app=None)
print(c.ws)  # auto
```

确认 uvicorn 默认 `ws="auto"`，会优先探测 sansio 实现。

## 根本原因

版本依赖链断裂：

```
uvicorn 0.53.0 默认 ws="auto"
    ↓ 优先选择新实现
websockets-sansio（需要 websockets 14+ 的 sansio API）
    ↓ 但实际安装的是
websockets 13.1（只有 legacy API，无 sansio）
    ↓ auto 探测失败，且未优雅 fallback 到 legacy 实现
"No supported WebSocket library detected"
    ↓ 所有 WebSocket 升级请求被拒绝
浏览器连不上 /ws 端点
```

**直接诱因**：`requirements.txt` 里写的版本约束 `websockets>=12.0,<14.0` 上限 `<14.0` 恰好把 uvicorn 0.53 需要的 14+ 排除了。这是引入 Web UI 时写下的隐患。

## 修复方案

### 改动 1：升级 websockets

```bash
.venv/bin/python -m pip install "websockets>=14.0,<18.0"
# websockets 13.1 → 17.1
```

### 改动 2：修正 requirements.txt 版本约束

文件：`requirements.txt`

```diff
- websockets>=12.0,<14.0
+ websockets>=14.0,<18.0
```

理由：uvicorn 0.53.0 的 `auto` ws 协议需要 websockets 14+ 的 sansio API，上限放宽到 18.0 允许后续次版本更新，同时防止未来主版本破坏性变更。

## 验证结果

### 1. sansio 实现加载

```python
from uvicorn.protocols.websockets import websockets_sansio_impl
# ✅ 加载成功，无 deprecation 警告
```

### 2. 服务启动日志

```bash
.venv/bin/python zzhclaw.py --mode web --no-browser --port 8766
```

日志干净，**不再出现** `Unsupported upgrade request` 和 `No supported WebSocket library detected` 警告。

### 3. WebSocket 双向通信

```python
async with websockets.connect('ws://127.0.0.1:8766/ws') as ws:
    await ws.send(json.dumps({'type': 'ping'}))
    resp = await ws.recv()
    # ✅ 收到 {'type': 'pong'}
```

连接成功，ping/pong 正常，前端不再循环重连。

## 经验总结

### 1. uvicorn `ws="auto"` 的陷阱

uvicorn 在 WebSocket 实现过渡期（legacy → sansio），`auto` 会优先探测新实现。如果 websockets 版本不够新、缺少 sansio API，**auto 不会优雅 fallback 到 legacy**，而是直接报"无可用库"。

### 2. 依赖版本约束要跟着上游走

写 `requirements.txt` 时，版本上限不能只凭"当前稳定版"拍脑袋，要查上游（uvicorn）对下游（websockets）的实际 API 依赖。`<14.0` 这种约束在 uvicorn 升级后会变成定时炸弹。

### 3. 诊断要分层

本次诊断按"依赖是否安装 → 实现能否加载 → API 是否存在 → 默认配置是什么"四层递进，每层用最小命令验证，避免盲目升级/重装。

## 预防措施

### 方案 A：锁定 websockets 下限（已采用）

`requirements.txt` 中 `websockets>=14.0,<18.0` 确保 sansio API 可用。

### 方案 B：显式指定 ws 实现（可选加固）

若担心未来 `auto` 探测逻辑再变，可在 `server.py` 的 `uvicorn.run()` 里显式指定：

```python
uvicorn.run(app, host=host, port=port, log_level="warning", ws="websockets")
```

强制用 legacy 实现（虽然 deprecated 但当前仍可用），绕过 auto 探测的不确定性。

### 方案 C：CI 加 WebSocket 连通性测试

在 CI 流水线里加一步：启动服务 → 建立 WebSocket 连接 → 发 ping 收 pong。任何依赖升级破坏 WebSocket 都会立即被 CI 抓到，而不是等到用户浏览器连不上才发现。

## 不在范围

- 不改 WebSocket 业务逻辑（`/ws` 端点的消息协议、Agent 桥接保持不变）
- 不改前端重连机制（3 秒重连 + toast 提示是正确行为，问题在服务端）
- 不降级 uvicorn（升级 websockets 是更前瞻的方案）
