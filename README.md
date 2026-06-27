# ZzhClaw 

🚀 用 Python 创作的 AI 编码助手，让你的终端也能拥有智能编程伙伴！

## 简介

ZzhClaw 是一个轻量级的 AI 助手，运行在你的终端里。它可以帮你：
- 自然语言对话，解答编程问题
- 直接读写文件，帮你修改代码
- 执行终端命令，无需切换窗口
- 联网搜索，获取最新信息
- 读取网页内容，总结资料
- 保存会话历史，随时继续之前的对话

既可以用命令行（CLI）快速操作，也可以用终端界面（TUI）获得更直观的体验。

## 模块说明

| 模块 | 说明 |
|------|------|
| `zzhclaw.ai` | 统一的 LLM API 封装 (兼容 OpenAI API) |
| `zzhclaw.agent` | Agent 核心，支持工具调用和状态管理 |
| `zzhclaw.coding` | 编码助手核心（含工具、会话、CLI） |
| `zzhclaw.tui` | Textual 终端界面 |

## 项目结构

```
zzhclaw/
├── zzhclaw/              # 主包
│   ├── __init__.py
│   ├── ai/               # LLM API 封装
│   │   ├── __init__.py
│   │   └── client.py
│   ├── agent/            # Agent 核心
│   │   ├── __init__.py
│   │   └── core.py
│   ├── coding/           # 编码助手核心
│   │   ├── __init__.py
│   │   ├── tools/        # 工具定义
│   │   │   ├── __init__.py
│   │   │   └── registry.py
│   │   ├── session/      # 会话管理
│   │   │   ├── __init__.py
│   │   │   └── manager.py
│   │   └── cli/          # 命令行界面
│   │       ├── __init__.py
│   │       └── app.py
│   └── tui/              # Textual 终端界面
│       ├── __init__.py
│       └── app.py
├── zzhclaw.py            # 入口
├── requirements.txt      # 依赖
└── .env                 # 配置
```

## 功能

- ✅ 基础聊天
- ✅ 工具调用 (read_file, write_file, run_bash, web_search, fetch_webpage)
- ✅ 会话管理 (保存/加载历史)
- ✅ 会话分支
- ✅ TUI 界面 (Textual)
- ✅ 工具执行前确认 (CLI 模式)

## 安装

```bash
cd zzhclaw
pip3 install -r requirements.txt
```

## 运行

### TUI 模式 

```bash
python3 zzhclaw.py
```

### CLI 模式 (推荐)

```bash
python3 zzhclaw.py --mode cli
```

## CLI 命令

| 命令 | 说明 |
|------|------|
| `/help`, `/h` | 显示帮助 |
| `/list` | 列出所有会话 |
| `/load <id>` | 加载会话 |
| `/new [name]` | 创建新会话 |
| `/save` | 保存当前会话 |
| `/fork <index> <name>` | 从某条消息分支 |
| `/delete`, `/rm <id>` | 删除会话 |
| `/quit`, `/exit`, `/q` | 退出 |

## TUI 快捷键 / 命令

| 按键 / 命令 | 说明 |
|-------------|------|
| `q` | 退出 |
| `Ctrl+L` | 清屏 |
| `/help`, `/h` | 显示帮助 |
| `/list` | 列出所有会话 |
| `/load <id>` | 加载会话 |
| `/new [name]` | 创建新会话 |
| `/save` | 保存当前会话 |
| `/delete`, `/rm <id>` | 删除会话 |

## 会话存储位置

`~/.zzhclaw/sessions/`

## TODO
增加TUI的权限准许功能，重构异步逻辑

设计TUI的界面风格，增加命令的直观使用

增加联网搜索功能

使用pm2让它长期跑以及接入im

增加goal

设置当前工作目录

cli情况下，agent调用工具时弹出的执行请求过长，后续化简成：在xxx地点执行xxx操作即可

