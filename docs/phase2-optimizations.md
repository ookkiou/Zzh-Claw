# ZzhClaw 第二批优化开发记录

> 记录时间：2026-09-17
> 范围：/cd 工作目录 + 路径沙箱、edit_file 增量编辑、grep/glob 搜索、流式输出、CLI 体验改进、TUI Markdown 渲染、权限模式（一键执行）
> 文档目的：复盘问题与解决、沉淀知识点、准备面试问答
> 前置文档：[第一批优化 + Web UI](./phase1-security-and-webui.md)

---

## 一、概述

第二批聚焦**能力扩展**和**体验提升**，共 7 项：

| 编号 | 优化项 | 类型 | 复杂度 |
|------|--------|------|--------|
| p2a | `/cd` 工作目录 + 路径沙箱 | 安全 + 体验 | 中 |
| p2b | `edit_file` 增量编辑工具 | 能力 | 中 |
| p2c | `grep_files` / `glob_files` 搜索工具 | 能力 | 中 |
| p2d | 流式输出（LLMClient + Agent + 三端） | 架构级 | 高 |
| p2e | CLI 输入历史/补全/确认简化 | 体验 | 中 |
| p2e | TUI Markdown 渲染 | 体验 | 中 |
| p2f | 权限模式（confirm/smart/auto 一键执行） | 安全 + 体验 | 中 |

工具数量从 **5 个增至 8 个**（新增 edit_file / grep_files / glob_files）。最大改动是 **p2d 流式输出**——重写了 Agent 核心的 LLM 调用方式，并改造三端前端渲染。**p2f 权限模式**回应用户"每次都要确认太麻烦"的痛点，让 agent 可被"一键全权委托"，同时保留底层安全护栏。

---

## 二、逐项详解

### 2.1 p2a：`/cd` 工作目录 + 路径沙箱

**动机**：README TODO 明确列出。此前 `read_file`/`write_file` 只能用绝对路径或相对进程启动目录，用户想"在某项目里工作"很痛苦；且 `write_file` 可写任意路径（安全隐患）。

**核心设计**（`registry.py`）：
```python
_WORKSPACE = {"cwd": os.getcwd(), "sandbox": True}

def _resolve_path(path: str) -> str:
    """相对路径基于 cwd 解析，绝对路径规范化"""
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(_WORKSPACE["cwd"], path))

def _check_write_sandbox(resolved_path: str) -> Optional[str]:
    """写沙箱：用 realpath 防符号链接逃逸"""
    if not _WORKSPACE["sandbox"]:
        return None
    real_target = os.path.realpath(resolved_path)
    real_cwd = os.path.realpath(_WORKSPACE["cwd"])
    if not (real_target == real_cwd or real_target.startswith(real_cwd + os.sep)):
        return f"错误: 写入被沙箱拒绝。目标不在工作目录内..."
    return None
```

**分层沙箱策略**（关键设计决策）：
| 工具 | 是否沙箱 | 理由 |
|------|:---:|------|
| `read_file` | ❌ 不沙箱 | 读系统文件（如 `/etc/hosts`）通常安全且有用 |
| `write_file` / `edit_file` | ✅ 沙箱 | 防止误写/恶意写系统文件 |
| `run_bash` | ⚠️ 黑名单 | 已有危险命令黑名单（第一批），且在 cwd 下执行 |

**动态工具描述**：`get_tools_with_cwd()` 每次调用 LLM 前深拷贝 TOOLS，把当前 cwd 注入 read_file/write_file/run_bash 的描述，让模型知道相对路径基准：
```python
def get_tools_with_cwd() -> List[Dict[str, Any]]:
    cwd = _WORKSPACE["cwd"]
    for tool in TOOLS:
        t = json.loads(json.dumps(tool))  # 深拷贝避免污染原 TOOLS
        if t["function"]["name"] == "read_file":
            t["function"]["description"] += f"\n当前工作目录: {cwd}（相对路径基于此解析）"
        ...
```

**三端命令**：CLI/TUI/Web 都加了 `/cd [path]`（查看/切换）和 `/sandbox <on|off>`（开关写沙箱）。Web 端通过 WebSocket `system_message` 类型回显。

**MVP 限制**：`_WORKSPACE` 是模块级全局状态，多用户/多标签页会互相影响。生产环境需改为 `threading.local` 或依赖注入。已在代码注释标注。

### 2.2 p2b：`edit_file` 增量编辑工具

**动机**：此前只有 `write_file` 全量覆盖。改一个大文件要重发整份内容——token 贵、易出错、diff 不可读。

**设计**：str_replace 风格，`old_text` → `new_text` 精确替换：
```python
def edit_file(path, old_text, new_text, replace_all=False) -> str:
    resolved = _resolve_path(path)
    sandbox_err = _check_write_sandbox(resolved)  # 复用写沙箱
    if sandbox_err: return sandbox_err
    if old_text == new_text: return "错误: old_text 和 new_text 相同"
    content = open(resolved).read()
    count = content.count(old_text)
    if count == 0: return "错误: 未找到要替换的文本（提示用 read_file 查实际内容）"
    if count > 1 and not replace_all:
        return f"错误: 找到 {count} 处匹配，不唯一（请加上下文或设 replace_all=true）"
    new_content = content.replace(old_text, new_text) if replace_all else content.replace(old_text, new_text, 1)
    open(resolved, "w").write(new_content)
    return f"成功编辑: {resolved}（替换 {count if replace_all else 1} 处）"
```

**唯一性强制**：默认要求 `old_text` 唯一匹配，多处匹配时报错并提示"加上下文或设 replace_all"。这防止模型误改多处相同代码。

**8 个测试场景**：唯一替换 / 多处报错 / replace_all / 未找到 / old==new / 文件不存在 / 沙箱拦截 / 最终内容验证，全部通过。

### 2.3 p2c：`grep_files` / `glob_files` 搜索工具

**动机**：此前模型在大项目里找代码只能 `run_bash("grep ...")`，慢、不安全、输出不可控。

**grep_files**（内容搜索，类似 `grep -rn`）：
```python
def grep_files(pattern, path=".", include=None, max_results=50, ignore_case=False):
    search_root = _resolve_path(path)
    regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)  # 无效正则报错不崩溃
    for root, dirs, files in os.walk(search_root):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.endswith(".egg-info")]
        for fname in files:
            if include and not fnmatch.fnmatch(fname, include): continue
            # 逐行匹配，errors="ignore" 跳过二进制
            ...
```

**关键技巧 `dirs[:] = ...`**：原地修改 `dirs` 列表会**影响 os.walk 的后续遍历**（剪枝），跳过 `.git/.venv/node_modules/__pycache__` 等目录。若用 `dirs = ...`（重新绑定）则无效，os.walk 仍会进入这些目录。

**glob_files**（路径查找，类似 `find`）：
```python
def glob_files(pattern, path=".", max_results=100):
    results = glob.glob(os.path.join(search_root, pattern), recursive=True)  # 支持 **
    # 过滤忽略目录 + 转相对路径 + 排序
```

**7 个测试场景**：内容搜索 / include 过滤 / 忽略大小写 / `**/*.py` 递归 / `docs/*.md` / 跳过 .venv.git / 无效正则容错，全部通过。

### 2.4 p2d：流式输出（架构级改动）

**动机**：此前 LLM 完整响应后才渲染，长回答等 10 秒很煎熬。流式输出是 DeepSeek/ChatGPT 的标配体验。

这是第二批**最大的改动**，涉及 LLMClient、Agent 核心、三端前端。

#### (1) LLMClient.chat_stream 生成器
```python
def chat_stream(self, messages, tools=None):
    """yield 每个 delta（content / tool_calls 增量）"""
    kwargs = {"model": self.model, "messages": messages, "stream": True}
    if tools: kwargs["tools"] = tools; kwargs["tool_choice"] = "auto"
    for chunk in self.client.chat.completions.create(**kwargs):
        if chunk.choices:
            delta = chunk.choices[0].delta
            if delta is not None:
                yield delta
```

#### (2) Agent.run 流式收集（核心难点）
OpenAI 流式响应里，**content 和 tool_calls 都是增量分片传来的**。tool_calls 尤其复杂：`id` 和 `function.name` 只在第一个分片，`function.arguments` 是 JSON 字符串的碎片，需要**按 index 累积拼接**：
```python
content_parts: List[str] = []
tool_calls_acc: Dict[int, Dict[str, str]] = {}
for delta in self.llm.chat_stream(messages, tools=get_tools_with_cwd()):
    # content 增量：实时推送
    if getattr(delta, "content", None):
        content_parts.append(delta.content)
        if on_token: on_token(delta.content)
    # tool_calls 增量：按 index 拼接
    if getattr(delta, "tool_calls", None):
        for tc in delta.tool_calls:
            idx = getattr(tc, "index", None) or 0
            acc = tool_calls_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
            if getattr(tc, "id", None): acc["id"] = tc.id
            fn = getattr(tc, "function", None)
            if fn:
                if getattr(fn, "name", None): acc["name"] = fn.name
                if getattr(fn, "arguments", None): acc["arguments"] += fn.arguments  # 碎片拼接

# 组装成标准 dict 格式
tool_calls_list = [{"id": acc["id"], "type": "function",
                    "function": {"name": acc["name"], "arguments": acc["arguments"]}}
                   for idx, acc in sorted(tool_calls_acc.items()) if acc["name"]]
```

**保留第一批所有容错**：json.loads try/except、execute_tool 兜底、max_iterations 上限——流式改造后一个都没丢（场景 5 专门验证了 max_iterations 仍生效）。

#### (3) 三端前端渲染

| 端 | 流式过程 | 完成后定型 |
|----|---------|-----------|
| **CLI** | ANSI `\r\033[K` 清除"思考中" + `print(delta, end="")` 打字机 | 换行；无 token 时用 rich Markdown 渲染 |
| **TUI** | `TokenMsg` → Static widget 累积纯文本 + `▊` 光标 | 移除 Static，挂载 `Markdown` widget 渲染 |
| **Web** | `token` 事件 → 流式气泡纯文本 + CSS 闪烁光标 | `marked.js` 渲染 Markdown + 代码高亮 |

**两阶段渲染**思想：流式过程用纯文本（快，不重复解析），完成后一次性渲染 Markdown（代码高亮/表格/列表）。兼顾打字机流畅度和最终排版质量。

#### (4) 多轮对话边界问题（重要修复）
**问题**：当模型"输出文本 + 调工具"再"输出文本"时，`on_token` 跨迭代累积，两轮文本会粘在一个气泡里（如"让我读文件"+"文件内容是..."粘成一句）。

**解决**：**工具调用时关闭当前流式气泡**，让下一轮 token 新建气泡。三端都修：
- CLI：`on_tool_call` 里 `print()` 换行 + 重置 `stream_started`
- TUI：`on_tool_call_msg` 里定型 streaming_widget（移除光标，置 None）
- Web：`closeStreamingBubble()` 把累积文本渲染成 Markdown，置 streamingEl=null

**验证回调顺序**：`token(让我看看) → tool_call → tool_result → token(看完了)`，确认前端边界逻辑成立，两轮文本成为独立气泡。

### 2.5 p2e：CLI 输入历史/补全/确认简化

**输入历史（↑↓）**：从 `prompt_toolkit.shortcuts.prompt` 换成 `PromptSession`：
```python
history_file = os.path.expanduser("~/.zzhclaw/history")
prompt_session = PromptSession(
    history=FileHistory(history_file),          # ↑↓ 翻历史，跨会话持久化
    auto_suggest=AutoSuggestFromHistory(),       # 灰色历史建议（→ 接受）
    completer=SlashCommandCompleter(),          # Tab 补全命令
)
```

**命令补全（Tab）**：自定义 Completer，只在 `/` 开头且无空格时补全：
```python
class SlashCommandCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith("/") and " " not in text:
            for cmd in CLI_COMMANDS:
                if cmd.startswith(text) and cmd != text:
                    yield Completion(cmd, start_position=-len(text))
```

**确认提示简化**（README TODO）：`summarize_args` 截断长参数，避免 write_file 大段内容刷屏：
```python
def summarize_args(args: dict) -> str:
    parts = []
    for k, v in args.items():
        sv = str(v).replace("\n", "\\n")
        if len(sv) > 60:
            sv = sv[:57] + f"...({len(str(v))}字符)"
        parts.append(f"{k}={sv!r}")
    return "{" + ", ".join(parts) + "}"
```

**双重转义防注入**：
- `rich_escape`（`rich.markup.escape`）：防 args 里的 `[bold]` 被 rich 当 markup
- `_html_escape`：防 args 里的 `<>&` 被 prompt_toolkit HTML 当标签

### 2.6 p2e：TUI Markdown 渲染

**动机**：此前 TUI 的 AI 回复是纯文本 Static，代码块/表格/列表都不渲染，而 CLI 反而有 `Markdown(response)`。

**解决**：用 `textual.widgets.Markdown` 渲染 AI 消息：
```python
from textual.widgets import Markdown

# add_message 里 assistant 分支
await log.mount(Markdown(content or "", classes="ai-message"))

# 流式完成后：移除纯文本 Static，挂载 Markdown widget
self.streaming_widget.remove()
await log.mount(Markdown(final_text or "", classes="ai-message"))
```

**顺带修复**：用户消息和工具消息加 `escape(content)`，防止用户输入 `[bold]` 被当 rich markup 渲染错乱。

### 2.7 p2f：权限模式（一键执行 / 保留批准权）

**动机**：用户反馈"每次 agent 执行工具都要问是否执行太麻烦"。需要在"全权委托 agent"和"保留逐个批准权"之间提供可选档位。

**三档设计**：
| 模式 | 图标 | 行为 | 适用 |
|------|:---:|------|------|
| `confirm`（默认） | 🔒 | 每个工具都问 Y/n | 谨慎操作、不熟任务 |
| `smart`（推荐折中） | ⚡ | 只读工具自动执行，写/执行工具仍问 | 日常使用 |
| `auto`（一键全权） | 🤖 | 所有工具自动执行，不再询问 | 信任 agent、批量任务 |

**工具风险分类**（`registry.py`）：
```python
READONLY_TOOLS = {"read_file", "grep_files", "glob_files", "web_search", "fetch_webpage"}
WRITE_TOOLS = {"write_file", "edit_file", "run_bash"}

def is_readonly_tool(name: str) -> bool:
    return name in READONLY_TOOLS
```

**决策逻辑内聚到 Agent**（`core.py`）：
```python
def _should_confirm(self, tool_name, confirm_tool) -> bool:
    if confirm_tool is None: return False             # 无回调直接放行
    if self.permission_mode == "auto": return False    # 全自动
    if self.permission_mode == "smart":
        return not is_readonly_tool(tool_name)        # 只读放行，写确认
    return True                                       # confirm 全问
```
run 循环里把原来的 `if confirm_tool:` 换成 `if self._should_confirm(name, confirm_tool):`。**关键**：决策放在 Agent 核心，三端前端零改动——它们只管提供 confirm_tool 回调，"要不要调用"由 Agent 按模式决定。

**关键安全模型**：auto 跳过的是"人工确认层"，但第一批的底层防护仍生效——run_bash 危险命令黑名单（`rm -rf /` 直接拒绝，不经过 confirm）、write/edit 路径沙箱（realpath 校验，只能写 cwd 内）。这两层是工具函数内部的硬性拦截，与权限模式**正交**。所以"一键全权"是有护栏的自主，不是裸奔。

**三端切换方式**：
- CLI/TUI：`/permission [confirm|smart|auto]` 查看/切换，`/auto` 一键全自动；TUI 在 Header 副标题实时显示 `权限: auto`
- Web：顶部栏可点击徽章循环切换（🔒confirm→⚡smart→🤖auto，三色区分），也支持斜杠命令

**Web 双向协议**：
```
前端点击徽章 → {"type":"set_permission","mode":"auto"}
服务端 agent.set_permission_mode(mode) → 回 {"type":"permission_mode","mode":result}
前端收到 → 更新徽章图标/颜色/label
连接建立时 → 服务端主动推送初始模式（前端初始化徽章）
```

**无效值保护**：`set_permission_mode` 对非法模式名不改变原状态并返回当前模式，前端徽章不会被错误值污染。

---

## 三、遇到的问题与解决

### 问题 1：流式多轮文本粘连
见 2.4(4)。根因是 on_token 跨迭代累积。解决：工具调用时关闭气泡。这是**设计阶段没预料到、测试时发现**的问题——单轮文本流式测试通过，但多轮（文本+工具+文本）才暴露。教训：流式测试必须覆盖多轮场景。

### 问题 2：py_compile 误校验 JS 文件
集成测试时我把 `app.js` 传给了 `python -m py_compile`，报 `SyntaxError: invalid character '（'`。这是**误报**——Python 编译器当然无法解析 JavaScript。解决：JS 用 `node --check` 校验。教训：不同语言用对应的语法检查工具。

### 问题 3：edit_file 的 f-string bug
第一版错误信息第二行缺 `f` 前缀：
```python
return (
    f"错误: 找到 {count} 处匹配...\n"
    "请提供更多上下文...替换全部 {count} 处。"  # ← 缺 f，{count} 原样输出
)
```
解决：补 `f` 前缀。教训：多行字符串拼接时，每行都要检查 f 前缀。

### 问题 4：Mock 无状态导致工具重复 20 次
测试流式工具调用时，无状态 MockLLM 每轮都返回相同 tool_call，导致 on_tool_call 被调 20 次。这**不是产品 bug**——反而验证了第一批的 `max_iterations=20` 上限保护在流式改造后仍生效（死循环被截断）。解决：改用有状态 Mock（第一轮调工具，第二轮文本结束）模拟真实模型行为。教训：Mock 要模拟真实的"有状态"交互，否则会测出假问题/漏测真问题。

### 问题 5：TUI 流式 widget 替换的位置问题
流式完成后要把 Static 换成 Markdown widget。担心顺序错乱。分析：streaming_widget 在 done 触发时一定是最后挂载的（中间无其他 widget 插入），所以 `remove()` + `mount(Markdown)` 到末尾能保持顺序。多轮场景下，中间气泡已被 on_tool_call_msg 定型为 Static，最终气泡仍是最后一个。教训：widget 替换前要确认它在布局中的位置。

### 问题 6：WebSocket 测试的消息队列残留
测试权限模式时，`/auto` 命令会让服务端连发两条消息（`permission_mode` + `system_message`），但测试的 `recv_until` 只消费了第一条，把 `system_message` 留在队列。下一步 `/permission` 查看时抓到了上一步的残留消息，断言失败。这**不是产品 bug**——产品逻辑正确（前 5 步全过），是测试没 drain 干净。解决：改用 `drain(wait=0.6)` 收集一个时间窗内的全部消息再断言。教训：测试异步消息协议时，一个操作可能产生多条消息，不能假设"一发一收"，要么全部消费要么用时间窗 drain。

---

## 四、我学到了什么

### 4.1 技术知识点

| 知识点 | 具体收获 |
|--------|---------|
| **OpenAI 流式 tool_calls 格式** | id/name 只在首分片，arguments 是 JSON 碎片，需按 index 累积拼接 |
| **os.walk 剪枝** | `dirs[:] = ...` 原地修改影响遍历；`dirs = ...` 重新绑定无效 |
| **realpath 防沙箱逃逸** | 符号链接可绕过 startswith 检查，必须 realpath 解析真实路径 |
| **prompt_toolkit PromptSession** | FileHistory（↑↓）+ AutoSuggestFromHistory（灰建议）+ 自定义 Completer（Tab） |
| **ANSI 终端控制** | `\r` 回行首 + `\033[K` 清到行尾，实现可被覆盖的"思考中"提示 |
| **两阶段渲染** | 流式纯文本（快）+ 完成后 Markdown 定型（美），兼顾流畅与排版 |
| **Textual Markdown widget** | `Markdown(content)` 渲染富文本，`remove()+mount()` 替换 widget |
| **双重转义防注入** | rich markup 用 `rich.markup.escape`，prompt_toolkit HTML 用自定义 escape |
| **深拷贝防污染** | `json.loads(json.dumps(tool))` 深拷贝 TOOLS，动态改描述不污染原列表 |
| **有状态 Mock** | 模拟真实多轮交互，无状态 Mock 会测出假问题 |
| **权限决策内聚** | 确认决策放 Agent 核心（`_should_confirm`），三端前端零改动只提供回调 |
| **安全护栏正交分层** | 人工确认（可关）与黑名单/沙箱（不可绕过）分离，auto 关前者留后者 |

### 4.2 工程方法论

1. **分层沙箱**：读放行、写沙箱、执行黑名单——按操作风险分级，而非一刀切
2. **流式测试要覆盖多轮**：单轮通过不代表多轮通过，边界问题藏在迭代切换处
3. **改造要保留安全网**：流式重写 Agent.run 后专门验证 max_iterations 仍生效（场景 5）
4. **Mock 要贴近真实**：有状态 Mock 模拟"调工具后看结果再回复"的真实模型行为
5. **工具对应语言**：Python 用 py_compile，JS 用 node --check，不混用
6. **策略与机制分离**：权限模式（策略）放 Agent 核心，确认回调（机制）放前端，新增模式不改前端
7. **异步协议测试要 drain**：一个操作可能产生多条消息，用时间窗收全部再断言，别假设一发一收

---

## 五、面试可能问的问题

### 5.1 流式输出相关

**Q1：OpenAI 流式响应里 tool_calls 是怎么传的？你怎么处理？**

A：流式下 tool_calls 是增量分片。每个 chunk 的 `delta.tool_calls` 是列表，元素有 `index`（区分并行的多个工具调用）、`id`（仅首分片有）、`function.name`（仅首分片有）、`function.arguments`（JSON 字符串的碎片，分多个 chunk 传）。我用一个 `Dict[int, Dict]` 按 index 累积：首分片存 id/name，后续分片把 arguments 字符串拼接起来。流结束后按 index 排序组装成标准 tool_calls 格式。关键点是 arguments 必须拼完整才能 json.loads，中途的碎片是不合法 JSON。

**Q2：流式输出怎么和工具调用共存？多轮对话时气泡怎么划分？**

A：一次 Agent.run 可能多轮迭代（文本→工具→文本）。on_token 跨迭代累积，若不处理会把多轮文本粘在一个气泡。我的方案是"工具调用时关闭当前气泡"：on_tool_call 触发时，把已累积的流式文本定型（CLI 换行、TUI/Web 渲染成 Markdown 并重置状态），下一轮 token 新建气泡。这样每轮 LLM 文本是独立气泡，中间夹着工具面板。我专门验证了回调顺序是 token→tool_call→tool_result→token，确保边界逻辑成立。

**Q3：流式改造后怎么保证不破坏原有的容错？**

A：第一批加的三层容错（json.loads try/except、execute_tool 兜底、max_iterations 上限）在流式重写时全部保留。我专门写了一个"无状态 Mock 永远返回工具调用"的测试场景，验证 max_iterations=20 仍能截断死循环——证明流式改造没破坏安全网。这是回归测试的思路：架构级改动后，必须验证旧的保护机制仍生效。

### 5.2 沙箱与安全相关

**Q4：路径沙箱怎么防止符号链接逃逸？**

A：用 `os.path.realpath` 解析真实路径再比较。如果只用 `os.path.abspath` + `startswith`，攻击者可以在 cwd 里建一个软链接 `evil -> /etc`，然后写 `evil/passwd`，abspath 看起来在 cwd 内但实际写到了 /etc。realpath 会解析软链接到真实路径 `/etc/passwd`，startswith(cwd) 失败，正确拦截。

**Q5：为什么 read_file 不沙箱但 write_file 沙箱？**

A：按操作风险分级。读系统文件（如 /etc/hosts 看配置、/usr/lib 看库）通常安全且对编码有用，沙箱会限制能力。写系统文件风险高（误写/恶意写 /etc/passwd、~/.ssh），必须沙箱。run_bash 介于两者之间，用危险命令黑名单（第一批）+ 在 cwd 下执行。这是"最小权限"和"可用性"的平衡。

### 5.3 工具设计相关

**Q6：edit_file 为什么要求 old_text 唯一？多处匹配怎么办？**

A：唯一性是为了精确性。如果 old_text 匹配多处，模型可能只想改一处，全改会误伤。所以默认 count>1 时报错，提示"加更多上下文使其唯一"。如果确实要全改，显式设 replace_all=true。这个设计参考了成熟的 str_replace_editor 工具，强制模型提供足够上下文，减少误改。

**Q7：grep_files 为什么用 dirs[:] 而不是 dirs =？**

A：os.walk 的 top-down 遍历中，`dirs` 列表是**引用**，walk 内部会根据它决定进入哪些子目录。`dirs[:] = [...]`（切片赋值）是原地修改列表内容，walk 能看到修改后的列表从而剪枝。`dirs = [...]`（重新绑定）只是让局部变量指向新列表，walk 内部的引用没变，仍会进入被忽略的目录。这是 Python 列表引用语义的经典坑。

### 5.4 前端体验相关

**Q8：流式输出为什么用"两阶段渲染"而不直接实时渲染 Markdown？**

A：实时渲染 Markdown 每个 token 都要重新解析整段文本 + 重渲染 DOM，性能差且闪烁。两阶段：流式过程显示纯文本（只追加，快），完成后一次性用 marked.js/Markdown widget 渲染完整内容（代码高亮、表格、列表）。这样既有打字机流畅感，又有最终排版质量。DeepSeek/ChatGPT 也是类似策略。

**Q9：CLI 的"AI 思考中..."提示怎么做到被流式输出覆盖的？**

A：用 ANSI 转义。打印"思考中"时用 `end=""` 不换行，光标停在行尾。第一个 token 到来时打印 `\r\033[K`（回车到行首 + 清除到行尾），抹掉"思考中"，再打印"AI"标签和 token。后续 token 直接 `print(delta, end="", flush=True)` 追加。flush=True 确保立即输出不被缓冲。

### 5.5 架构相关

**Q10：get_tools_with_cwd 为什么每次深拷贝 TOOLS？**

A：因为要动态注入 cwd 到工具描述，但不能污染原 TOOLS 列表（cwd 会变，且 TOOLS 是模块级常量）。用 `json.loads(json.dumps(tool))` 深拷贝每个工具 dict，在副本上改描述。如果直接改 TOOLS，第二次调用时描述里会有重复的 cwd 注入，且并发场景下数据竞争。

### 5.6 权限模式相关

**Q11：一键执行（auto 模式）怎么保证安全？**

A：关键是区分"人工确认层"和"底层防护层"。auto 模式跳过的只是 confirm_tool 人工确认，但第一批建立的两道底层护栏仍然生效：① run_bash 的危险命令黑名单（rm -rf /、mkfs、curl|sh 等在工具内部直接拒绝，根本不经过 confirm_tool）；② write_file/edit_file 的路径沙箱（realpath 校验，只能写工作目录内）。这两层是工具函数内部的硬性拦截，与权限模式正交。所以 auto 是"有护栏的自主"——agent 可以自由读写工作目录、跑安全命令，但碰不到系统关键路径和危险命令。

**Q12：权限模式的决策逻辑为什么放在 Agent 核心而不是各前端？**

A：因为 confirm_tool 是 Agent.run 的回调参数，Agent 在调用它之前最有上下文（知道工具名、能查 is_readonly_tool）。我把决策内聚成 `_should_confirm(tool_name, confirm_tool)`：confirm 全问、smart 只读放行写确认、auto 全放行。三端前端零改动——它们只负责提供 confirm_tool 回调（CLI 用 pt_prompt、TUI 用 post_message+Event、Web 用 enqueue+Event），至于"要不要调用这个回调"完全由 Agent 按 permission_mode 决定。这符合第一批确立的"Agent 核心与 UI 解耦"原则：核心定义策略，前端只提供机制。若放前端，三端要各写一遍模式判断，重复且易不一致。

**Q13：smart 模式怎么划分只读和写工具？为什么这样分？**

A：按副作用划分。只读工具（read_file/grep_files/glob_files/web_search/fetch_webpage）无副作用，自动放行不会造成损害，省去大量确认。写/执行工具（write_file/edit_file/run_bash）有副作用（改文件、跑命令），保留确认。这个划分让日常"读代码、搜代码"流畅无阻，而"改文件、执行命令"仍有人工把关，是 confirm（全问，太烦）和 auto（全放，太险）之间的实用折中。划分表维护在 registry.py 的 READONLY_TOOLS/WRITE_TOOLS 常量，新增工具时归类即可。

---

## 六、测试覆盖

| 模块 | 测试场景数 | 关键验证点 |
|------|:---:|------|
| p2a 工作目录+沙箱 | 5 | 相对路径解析、沙箱拦截、沙箱开关、read 放行 |
| p2b edit_file | 8 | 唯一替换、多处报错、replace_all、未找到、old==new、文件不存在、沙箱、内容验证 |
| p2c grep/glob | 7 | 内容搜索、include 过滤、忽略大小写、递归 glob、跳过忽略目录、无效正则容错 |
| p2d 流式后端 | 5 | 纯文本拼接、arguments 分片累积、会话格式、多工具 index、max_iterations 保护 |
| p2d 多轮边界 | 1 | 回调顺序 token→tool_call→tool_result→token |
| p2e CLI 辅助 | 6 | summarize_args 截断/换行转义、html_escape、补全（/he→/help、带空格不补全、非斜杠不补全） |
| 集成冒烟 | 5 | 首页/CSS/JS/API 全 200、WebSocket ping/pong、/cd、/help |
| p2f 权限后端逻辑 | 15 | confirm/smart/auto × 只读/写工具的确认行为、动态切换、无效值保护 |
| p2f 权限 WebSocket 集成 | 7 | 初始推送、set_permission、/auto、/permission 查看/切换、无效值 |

**总计 59 个测试场景**，全部通过。测试方式：mock LLM（不消耗真实 API）+ 临时目录（不污染项目）+ 真实服务启动（集成验证）。

---

## 七、附录

### 7.1 新增/修改文件清单

```
新增工具（registry.py）：
  edit_file / grep_files / glob_files / 工作目录管理（set_cwd/get_cwd/set_sandbox）
  _IGNORE_DIRS / _resolve_path / _check_write_sandbox / get_tools_with_cwd

修改文件：
  zzhclaw/ai/client.py          +25   chat_stream 生成器
  zzhclaw/agent/core.py         +50 -27  run 流式重写 + on_token
  zzhclaw/coding/tools/registry.py  +346  工作目录/沙箱/edit_file/grep/glob
  zzhclaw/coding/tools/__init__.py  +18   导出新函数
  zzhclaw/coding/cli/app.py     +91 -9   流式/历史/补全/确认简化/cd/sandbox
  zzhclaw/tui/app.py            +104 -13 流式/Markdown/cd/sandbox
  zzhclaw/web/server.py         +55      on_token/斜杠命令
  zzhclaw/web/static/app.js     +82      流式气泡/工具图标/system_message
  zzhclaw/web/static/style.css  +14      流式光标动画

权限模式（p2f）增量改动：
  zzhclaw/coding/tools/registry.py  +12   READONLY_TOOLS/WRITE_TOOLS/is_readonly_tool
  zzhclaw/agent/core.py             +29   permission_mode/set_permission_mode/_should_confirm
  zzhclaw/coding/cli/app.py         +31   /permission /auto 命令 + 启动显示 + Tab 补全
  zzhclaw/tui/app.py                +43   /permission /auto + Header 副标题指示
  zzhclaw/web/server.py             +31   斜杠命令 + set_permission 消息 + 初始推送
  zzhclaw/web/static/index.html     +4    顶部栏权限徽章
  zzhclaw/web/static/app.js         +39   权限配置/循环切换/permission_mode 处理
  zzhclaw/web/static/style.css      +50   权限徽章三色样式
```

### 7.2 工具总览（8 个）

| 工具 | 功能 | 沙箱 |
|------|------|:---:|
| read_file | 读文件（相对路径基于 cwd） | ❌ |
| write_file | 全量写文件 | ✅ |
| edit_file | 增量替换（str_replace 风格） | ✅ |
| run_bash | 执行命令（cwd 下 + 黑名单） | ⚠️ |
| web_search | 联网搜索 | — |
| fetch_webpage | 抓网页 | — |
| grep_files | 内容正则搜索 | ❌ |
| glob_files | 路径 glob 查找 | ❌ |

### 7.3 启动命令

```bash
cd /Users/zzh/Documents/GitHub/zzhclaw
.venv/bin/python zzhclaw.py --mode cli   # CLI（↑↓历史 / Tab补全 / 流式）
.venv/bin/python zzhclaw.py --mode tui   # TUI（Markdown 渲染 / 流式）
.venv/bin/python zzhclaw.py --mode web   # Web（DeepSeek 风格 / 流式打字机）
```

### 7.4 权限模式命令速查

| 端 | 切换方式 |
|----|---------|
| CLI/TUI | `/permission [confirm\|smart\|auto]` 查看/切换；`/auto` 一键全自动 |
| TUI | Header 副标题实时显示 `权限: {mode}` |
| Web | 顶部栏徽章点击循环（🔒→⚡→🤖）；也支持 `/permission` `/auto` 命令 |

三档语义：`confirm` 每个工具都问（默认）｜`smart` 只读自动、写/执行确认（推荐）｜`auto` 全自动（仍受黑名单+沙箱保护）。

### 7.5 后续可优化（第三批候选）

- 回调 → 生成器事件流重构（`for event in agent.run_stream()`）
- 同步 → 全异步（AsyncOpenAI，去掉 threading.Event 桥接）
- 上下文压缩（长会话用 LLM 摘要老对话）
- 跨会话记忆检索（给 sessions 建向量索引）
- `_WORKSPACE` 改 threading.local 支持多用户
- 工具装饰器化注册（`@tool` 自动收集 schema）
- 正式 pytest 测试套件（当前是临时验证脚本）
