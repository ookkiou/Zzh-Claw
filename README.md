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

## 项目结构

```
zzhclaw/
├── zzhclaw/              # 主包
│   ├── __init__.py
│   ├── ai.py             # LLM API 封装
│   ├── agent.py          # Agent 核心
│   ├── tools.py          # 工具定义
│   ├── session.py        # 会话管理
│   ├── cli.py            # 命令行界面
│   └── tui.py            # Textual 终端界面
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