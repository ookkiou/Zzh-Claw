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
| `zzhclaw.eval` | 任务验收、批量评测、报告、失败诊断与跨 Agent 对比 |
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
- ✅ 离线任务集、自动验收与可恢复的 Agent 评测

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

## Agent 评测

从源码安装开发依赖后，可以对受信任的 Coding Agent 任务进行批量评测：

```bash
# 校验任务结构和资源，不调用模型、不执行验收
zzhclaw eval validate benchmarks/python_basic/benchmark.json

# 逐题检查原始代码失败、参考修复通过，不调用模型
zzhclaw eval verify benchmarks/python_basic/benchmark.json \
  --output runs/verification.json

# 使用下方模型环境变量配置；每个任务重复 3 次
zzhclaw eval run benchmarks/python_basic/benchmark.json \
  --output runs/baseline --repeat 3

# 中断后使用相同任务、模型、配置和源码续跑
zzhclaw eval run benchmarks/python_basic/benchmark.json \
  --output runs/baseline --repeat 3 --resume

# 从已有产物重建报告，不调用模型
zzhclaw eval report runs/baseline

# 配对比较相同 benchmark 资源上的两个运行
zzhclaw eval compare runs/baseline runs/candidate --output runs/comparison.md

# 同一模型的两份固定提示词对比：先运行 dev 冒烟，再运行 test
zzhclaw eval experiment benchmarks/python_basic/benchmark.json \
  --stage smoke --output runs/prompt-smoke
zzhclaw eval experiment benchmarks/python_basic/benchmark.json \
  --stage test --repeat 3 --output runs/prompt-test

# 同一模型对比 ZzhClaw 与 Aider：先 dev，冻结配置后再 test
# Aider 单独安装，不加入 ZzhClaw 的依赖环境
uv venv runs/tools/aider-venv --python 3.12
uv pip install --python runs/tools/aider-venv/bin/python aider-chat==0.86.2
zzhclaw eval cross-experiment benchmarks/python_challenge/benchmark.json \
  --aider-executable runs/tools/aider-venv/bin/aider \
  --split dev --repeat 1 --task-timeout 180 --output runs/cross-dev
zzhclaw eval cross-experiment benchmarks/python_challenge/benchmark.json \
  --aider-executable runs/tools/aider-venv/bin/aider \
  --split test --repeat 3 --task-timeout 180 --output runs/cross-test

# 从已有产物提取失败案例，不调用模型
zzhclaw eval analyze runs/prompt-test/candidate
```

`run` 支持 `--model`、`--task ID`、`--tag TAG`、`--split train/dev/test`、
`--max-iterations N`、`--system-prompt FILE`、`--keep-workspaces`、
`--keep-failed-workspaces` 和 `--fail-fast`。`--task` 可重复选取多个任务；
多个 `--tag` 表示同时包含全部标签。默认串行执行，单个任务失败后继续。

运行目录包含 `manifest.json`、`summary.json`、`report.md`，以及
`attempts/repeat-001/tasks/<task-id>/` 下的 `result.json`、`trace.jsonl` 和独立会话。
默认清理临时工作区；`--keep-workspaces` 可以保留修复后的代码。
续跑跳过已有完整结果（包括失败），重跑缺失、损坏或被中断的 attempt；
模型、提示词、任务资源、全局 skills 或源码变化时需要新建运行目录。
不要同时向同一个运行目录启动多个进程。

报告提供成功率、标签统计、工具调用与时延、超时与安全诊断、观测 pass@k 和 consistency@k。
未完成的评测会显示待完成次数；token 未接入时显示 `N/A`。
运行对比按任务 ID 和重复序号配对，展示胜负、成功率差值及效率变化。
退出码：全部通过 `0`，存在失败或未完成 `1`，配置或产物错误 `2`，用户中断 `130`。

当前工作区副本和写入沙箱不提供容器级隔离，任务及验收脚本必须可信。
验收命令中的 `{workspace}` 会替换为本次工作区，`{python}` 会替换为运行评测的 Python 解释器。
`run --task-timeout N` 和 `cross-experiment` 使用独立 Agent 进程，超过预算会终止
POSIX 进程组；验收在 Agent 结束后另有独立时限，不包含在 Agent 预算中。
普通 ZzhClaw `run` 不指定该参数时仍在进程内执行，不提供 Agent 硬时限。
外部 Aider 默认使用任务的 `task_timeout_seconds`；原始内部工具/安全指标无法观测时
显示 `N/A`。`agent.log` 保存最多末尾 1 MB 日志并替换环境变量中的密钥值。
Windows 目前只终止直接子进程，不保证终止孙进程。
内置 [python-basic v0.1](benchmarks/python_basic/README.md) 的 30 个离线编码任务，
分为 6 train、9 dev、15 test，提供外部验收和参考修复。
另有 [python-challenge v0.1](benchmarks/python_challenge/README.md) 的 6 道多文件任务，
包含 2 dev / 4 test，适合跨系统流程验证和探索，不作为通用排行榜。
Aider 使用全部任务源码作为初始可编辑上下文及自身系统提示词，ZzhClaw 自主读取文件；
两边共享模型、任务、验收和时间预算，内部策略与调用次数限制并不完全相同。
工作区外的测试和参考答案不是真正的权限隔离；小型人工任务集不能代表全面的 Agent 能力。

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
