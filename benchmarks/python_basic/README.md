# python-basic v0.1

30 个原创、离线、确定性 Python 编码任务。任务覆盖缺陷修复、功能实现、重构和多文件协作，使用标准库实现，验收依赖 pytest。它用于分析 ZzhClaw 的工具执行与代码修改行为，不是通用编码能力排行榜。

已完成的真实模型实验见 [v0.1 实测报告](RESULTS.md)：同一模型、两份系统提示词、90 个正式 attempt。该报告包含完整率、效率、工具错误案例和解释边界。

## 数据与判分

- `tasks.jsonl`：任务契约、标签、难度、划分及验收命令。
- `fixtures/<task-id>/`：Agent 可见的初始工作区。
- `validators/`：工作区外的验收测试，包含正常、边界、异常及适用的副作用检查。
- `references/<task-id>/`：工作区外的参考修复，仅用于任务质量验证，不注入 Agent 上下文。
- `prompts/baseline.txt`：冻结的默认助手提示词；`candidate.txt`：直接完成编码任务的提示词。

每个任务只有全部验收测试通过才算成功。重构任务除行为外，还检查指定接口、委托关系或单遍迭代等约束；有限测试无法证明所有输入或复杂度性质。

拆分为 6 个 train、9 个 dev、15 个 test。完整目录见 [TASKS.md](TASKS.md)。train 用于练习，dev 用于调试与提示词选择；固定配置后再运行 test。三组任务均可公开查看，因此这不是第三方保密测试集。不要在看过 test 结果后反复改提示词，再把同一份 test 作为未见数据宣传。

所谓隐藏验收只表示不复制到工作区、不传入模型上下文。当前工具与验收共用宿主权限，Agent 仍可能通过绝对路径或 shell 访问外部资源；提示词禁令不能提供安全隔离。只有可信的任务与代理适合当前本地流程。测试/答案泄漏会使成绩失去意义。

## 验证任务质量

在仓库根目录安装开发依赖后运行：

```bash
python -m zzhclaw eval verify benchmarks/python_basic/benchmark.json \
  --output runs/python-basic-v0.1/verification.json
```

每个任务以独立副本执行两次验收：原始实现必须返回 pytest 的测试失败码 `1`，应用参考修复后必须返回 `0`。收集错误、超时、缺失依赖和零测试都不能算合格的原始失败。JSON 保存每次验收输出、时间及 benchmark 资源指纹。它证明任务可判分，不是模型成绩。

## 同一模型的提示词实验

先在仓库根目录创建 `.env`，配置 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL_ID`。密钥不要提交到 Git。

```bash
# dev 集中的两个任务，每个配置各执行一次，检查真实模型适配
python -m zzhclaw eval experiment benchmarks/python_basic/benchmark.json \
  --stage smoke --output runs/prompt-smoke

# 固定两份提示词后，15 个 test 任务，每配置每任务重复 3 次
python -m zzhclaw eval experiment benchmarks/python_basic/benchmark.json \
  --stage test --repeat 3 --output runs/prompt-test

# 配置、资源和源码未改变时，可在原命令后附加 --resume
```

正式实验共 90 个 attempt，最多每个 attempt 12 个 Agent 迭代；一个迭代可能包含多个工具调用或 API 重试，不等于一次固定成本调用。未接入 token/cost 统计时无法据此计算实际费用。任务级总时限尚未实施，只有模型请求与验收进程超时。

保持模型、服务端点、工具、skills、任务划分、迭代预算及环境一致，仅替换系统提示词。当前顺序执行 baseline 后 candidate，没有控制采样种子、服务端模型更新或时间漂移，不能把配对差值直接解读为因果效应或显著提升。资源或源码变化后必须新建运行目录。

输出包含两侧 `manifest.json`、`summary.json`、`report.md`、`failures.json/md`、完整轨迹与保留的工作区，以及总体 `comparison.md`。失败分类是自动诊断线索，需要阅读修改后的代码和轨迹确认根因。

## 报告解释

成功率按已完成的有效 attempt 统计，基础设施异常仍在分母中；必须同时查看状态分布与未完成数量。observed pass@3 是已完成 3 次的任务至少成功一次的比例，consistency@3 是全部 3 次成功的比例。两者不是额外采样池上的无偏估计。

同时比较工具次数、时延、超时、安全诊断和按标签成功率，阅读两侧胜负任务；工具和安全错误仍有字符串分类的局限。小样本或全通过结果不能证明两份提示词等价，也不能证明安全。

发布结果时应附运行身份、模型 ID、提示词指纹、资源与源码指纹、任务范围、重复次数、完整率和局限。只有完成真实模型实验后才能填写模型成功率、改进幅度或失败根因；参考修复和 FakeLLM 结果必须单独标注。
