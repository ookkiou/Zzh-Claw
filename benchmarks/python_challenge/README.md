# python-challenge v0.1

真实跨系统实验见 [RESULTS.md](RESULTS.md)。

6 道原创多文件 Python 任务，用于验证 ZzhClaw 与外部 CLI Agent 的统一验收与重复对比。比 basic 集增加状态机、传递依赖、原子性、所有权和切片输入等组合条件；是否具有更高区分度须由真实结果判断。

| ID | Split | 内容 | 主要验收 |
|---|---|---|---|
| challenge-001 | dev | 幂等转账 | 金额校验、失败无副作用、回执复制、重试冲突 |
| challenge-002 | dev | 依赖工作流 | 字典序拓扑、执行前校验、失败传播、独立分支 |
| challenge-003 | test | 租约队列 | 边界到期、失效 token、FIFO、负载隔离 |
| challenge-004 | test | 依赖缓存 | 环检测、替换原子性、传递失效、固定种子 DAG |
| challenge-005 | test | 增量帧解析 | 随机切片、空帧、超长头、协议错误与 reset |
| challenge-006 | test | 分层配置 | 递归删除、优先级、严格类型、输入不变 |

任务需求在 prompt 和 fixture README 中完整给出；外部 validator 不引入未说明的实现方式要求。参考修复和验收都位于工作区外。使用现有 `eval verify` 检查所有原始实现退出 1、参考实现退出 0；收集错误不算有效失败。固定种子生成测试检查更多组合，不能视为额外独立任务。

```bash
zzhclaw eval verify benchmarks/python_challenge/benchmark.json \
  --output runs/challenge-verification.json
zzhclaw eval cross-experiment benchmarks/python_challenge/benchmark.json \
  --aider-executable runs/tools/aider-venv/bin/aider \
  --split dev --repeat 1 --task-timeout 180 --output runs/cross-dev
zzhclaw eval cross-experiment benchmarks/python_challenge/benchmark.json \
  --aider-executable runs/tools/aider-venv/bin/aider \
  --split test --repeat 3 --task-timeout 180 --output runs/cross-test
```

方法约定：

- 比较指定配置的完整系统。尽量共享底层模型，但 Prompt、上下文组织和编辑策略属于各系统自身配置。
- Aider 0.86.2，CLI `--message-file` 非交互运行，`openai/<MODEL_ID>` 映射到同一 OpenAI 兼容服务。主/weak model 均指定同一模型；禁用 git、自动提交、自动 lint/test、URL 检测、shell 建议、更新检查和统计上报。diff 编辑格式，全部 fixture 源码与 README 作为初始可编辑上下文。配置/模型配置/输入历史/聊天历史/LLM 历史均显式指定每次 attempt 独立文件，并禁用历史恢复。没有自动向 Aider 注入外部验收结果或进行失败重试。
- ZzhClaw 使用默认系统提示词与原有工具、自主探索源码、最多 12 次循环。独立 HOME 不加载用户全局 skills。Aider 的内部模型轮次和修复重试由其自身管理，没有等价的循环上限；统一约束是每题 180 秒 Agent 预算。
- 每次从干净 fixture 复制，忽略 bytecode/cache/lock。相同输入、相同外部 validator，成功必须由 validator 退出 0 判定，Agent 自述不能决定成绩。
- Agent 预算包括进程启动、模型等待和编辑，结束后另运行最多 30 秒 validator。主指标延时还包含工作区准备和验收；不同 Python/CLI 启动开销也算实际使用成本。
- POSIX 超时/中断终止进程组；普通退出、错误、超时分别保留记录。默认串行先运行 ZzhClaw 后运行 Aider，服务时间漂移可能影响延时，当前不做因果或显著性结论。
- Aider 工具/迭代/安全指标未接内部事件，汇总显示 N/A。token/cost 尚未接入。可比较成功率、重复稳定性和端到端耗时，不能把工具次数零值当作效率优势。
- dev 可调试接口；test 冻结后每题各 3 次。4 道 test 题，每道占 25 个百分点，12 attempts 也只有 4 个独立任务；不证明广泛能力或排名。公开人工题不能保证未污染，工作目录隔离不是读权限/容器隔离。

接口参考：[Aider scripting](https://aider.chat/docs/scripting.html)、[CLI options](https://aider.chat/docs/config/options.html)。
