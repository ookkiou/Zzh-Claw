# 本地命令执行契约

`zzhclaw.runtime` 是工具层和评测层共用的基础设施。`run_bash`、外部 Validator、Agent supervisor 和 Aider 版本探测都使用 `run_command`。不依赖模型客户端或评测包，不新增运行时依赖。

## 调用方式

```python
import sys
from pathlib import Path
from zzhclaw.runtime import run_command

result = run_command(
    [sys.executable, "-m", "pytest", "-q"],
    cwd=Path("my-project"),
    timeout=30,
    output_limit=100_000,
    log_path=Path("runs/check.log"),
    log_limit=1_000_000,
)
print(result.to_dict())
```

argv 默认 `shell=False`。只有工具执行用户指定的 shell 命令时显式传入字符串和 `shell=True`。stdin 为非交互模式；不用于启动持久后台服务。

## 结构化状态

| status | error_code | 含义 |
|---|---|---|
| succeeded | null | 命令退出 0，输出收集完成 |
| failed | command_failed | 命令退出非零，例如测试失败 |
| timeout | command_timeout | 超过预算，执行清理 |
| cancelled | command_cancelled | `cancel_event` 被设置，执行清理 |
| spawn_error | command_spawn_error | 可执行文件/cwd 等无法启动 |
| capture_error | command_capture_error | 无法完整收集输出，不能据退出 0 判定成功 |

结果包含退出码、stdout/stderr、耗时和两路截断标记；timeout/cancelled 的 exit_code 为 null。`metadata()` 导出不含 stdout/stderr 的执行摘要。KeyboardInterrupt/SystemExit 等仍向上传播，finally 负责清理，CLI/Runner 继续采用原来的中断处理。

## 输出和日志

两路输出各有独立读取线程，使用最多 16 个 16 KiB 块的有界队列。读取期间只保留设定上限，超限继续排空，避免 stdout/stderr 互相阻塞。不会先无限 capture 再截断。

stdout/stderr 保留前缀，可选合并日志保留尾部；UTF-8 解码使用替换字符。工具默认每路 100,000 字节；Agent 日志默认最多 1,000,000 字节。已知环境凭据值在输出/日志中替换为 `[REDACTED]`；脱敏后再次约束字节长度。截断后的日志不能视为完整原始输出。

日志在命令退出、超时、取消或可捕获中断清理时写出。直接 SIGKILL 或机器崩溃无法运行 Python finally，不保证保留该命令日志；worker 的逐事件轨迹是独立机制。

## 进程清理和环境

POSIX 为每条命令创建独立进程组。超时/取消先 SIGTERM，等待最多 1 秒，再 SIGKILL；命令正常退出也清理同组后台进程。输出回收可能额外耗时，因此 timeout 是开始停止执行的预算，不是函数在该毫秒必定返回的实时保证。

ZzhClaw worker 接收 SIGTERM 时先终止正在执行的内层工具命令组，再退出，避免外层超时漏掉嵌套工具。主动脱离进程组、外部直接 SIGKILL worker 等情况不提供完整进程树保证；Windows 只清理直接子进程。这些机制不构成容器或 OS 权限隔离。

工具环境额外提供 `ZZHCLAW_PYTHON`，指向当前运行 ZzhClaw 的 Python 解释器，可使用 `"$ZZHCLAW_PYTHON" -m pytest` 复用已有依赖。

默认 `command_environment()` 只继承 PATH/HOME/语言/临时目录/Python 开发环境/代理与证书/SSH agent 等基本变量。模型 API key、云凭据和 token 不自动进入普通工具进程。需要 API 的 Agent 进程由适配器显式提供 env，validator 使用任务声明的环境变量。

环境过滤不阻止命令主动读取磁盘凭据；HOME、PYTHONPATH 以及受信任脚本仍可访问本机资源。只应用于受信任本地任务。

## 文本工具兼容与 Trace

`ToolResult` 是 str 的兼容子类。模型、CLI/TUI/Web 回调和 JSON 会话仍得到原有文字；执行代码同时携带 error_code 与 metadata。工具在实际错误分支标注 `tool_error`、`workspace_violation`、`policy_rejected`、`unknown_tool`，不会根据成功输出是否包含“错误”字样判断失败。

Agent 的 tool_result 事件增加 `result_schema_version=1`、error_code，以及命令的退出码/超时/截断/耗时信息。命令非零退出（包括修复前的测试失败）计入命令错误，但不等同于任务最终失败。新旧工具错误口径不应直接当作优化收益比较。新轨迹优先按结构化字段计算工具错误与安全诊断；旧 JSON/JSONL 继续使用原有字符串回退，不能将历史近似指标变成精确观测。

ValidatorResult 新增可选的 stdout_truncated、stderr_truncated、error_code，旧结果缺少字段仍可读。Agent 输出目录额外生成 command.json；旧报告和历史真实实验结果保持原样。源码发生变化后，旧运行不能直接 --resume，应使用新的输出目录。
