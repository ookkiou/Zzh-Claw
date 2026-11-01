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
│   ├── __main__.py       # 命令行入口 (zzhclaw / python -m zzhclaw)
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
├── pyproject.toml        # 打包与依赖配置
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

需要 Python 3.10+。

```bash
pipx install zzhclaw        # 推荐：独立虚拟环境 + 全局 zzhclaw 命令
```

```bash
uv tool install zzhclaw     # 或 uv 用户；免安装直接跑：uvx zzhclaw
```

```bash
pip install zzhclaw         # 或装进当前环境
```

### 从源码安装（开发）

```bash
git clone https://github.com/ookkiou/Zzh-Claw.git && cd Zzh-Claw
pip install -e ".[dev]"
```

## 运行

```bash
zzhclaw                     # TUI 终端界面（默认）
zzhclaw --mode cli          # CLI 模式 (推荐)
zzhclaw --mode web          # 浏览器界面
python -m zzhclaw           # 未装全局命令时的等价写法
```

## 配置

首次运行前需要提供模型密钥，两种方式任选其一：

```bash
# 1) 环境变量（对 pipx / uv 安装最直接）
export OPENAI_API_KEY=sk-xxx
export OPENAI_MODEL_ID=gpt-4o-mini          # 可选，默认 gpt-4o-mini
export OPENAI_BASE_URL=https://api.openai.com/v1   # 可选，兼容 OpenAI 协议的服务都能用
zzhclaw

# 2) 在当前目录放一个 .env（参见仓库里的 .env.example）
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
