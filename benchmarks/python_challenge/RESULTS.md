# ZzhClaw × Aider 跨系统评测记录

日期：2026-10-12（Asia/Shanghai）。这是本地真实模型实验，属于小规模探索，不是通用 Agent 排行榜。

## 实验配置

- 模型请求 ID：`deepseek-flash`；两边使用同一 OpenAI 兼容端点。此 ID 是本地配置名称，不独立验证服务实际路由的底层权重。
- Benchmark：python-challenge@0.1.0；6 道原创多文件任务，2 dev / 4 test。共 85 个参数化验收实例；其中 test 63 个实例仍只对应 4 道独立任务。
- dev 两边各跑 2 题一次，均 2/2 通过；不计入下表 test 成绩。
- test 每题每系统 3 次，共 24 attempts。固定任务/模型/180 秒 Agent 进程预算/30 秒独立验收预算。
- Aider 0.86.2，Python 3.12.13，diff 格式、全部源码初始上下文，无自动 lint/test、无 shell 建议；使用其自身系统 Prompt。ZzhClaw 使用默认 Prompt、自主读取源码及自身工具，最多 12 次循环；Aider 内部轮次/编辑重试不受等价循环约束。
- 每次使用新工作副本及独立 HOME；Aider 配置和所有历史路径显式指定，禁用历史恢复。外部 Validator 统一判分，未向 Agent 暴露其运行结果。
- 串行先 ZzhClaw 后 Aider。耗时包含进程启动、模型等待、编辑、准备与验收，受服务负载和运行顺序影响。

## 真实 test 成绩

| 指标 | ZzhClaw | Aider |
|---|---:|---:|
| 通过次数 | 12/12 | 12/12 |
| Task Success Rate | 100.0% | 100.0% |
| 观测 pass@3 | 100.0% | 100.0% |
| consistency@3 | 100.0% | 100.0% |
| 平均端到端耗时 | 37.99 秒 | 53.42 秒 |
| 平均观测工具调用 | 13.25 | N/A |
| 超时率 | 0.0% | 0.0% |
| Token / Cost | N/A | N/A |

配对 12 次；仅 ZzhClaw 通过 0 次；仅 Aider 通过 0 次；同为通过或失败 12 次。Aider 减 ZzhClaw 的成功率差值：0.0 个百分点。

## 逐题结果

| 任务 | ZzhClaw 通过 | Aider 通过 |
|---|---:|---:|
| challenge-003 | 3/3 | 3/3 |
| challenge-004 | 3/3 | 3/3 |
| challenge-005 | 3/3 | 3/3 |
| challenge-006 | 3/3 | 3/3 |

## 解释与边界

两套系统在本轮 test 均满分，当前任务集仍未产生成功率区分，不能据此宣称任一系统能力更强。增加状态与边界条件并不自动保证难度足够。当前证据证明跨系统评测闭环已真实运行，后续需要更大、具有真实仓库背景和回归约束的独立任务集。

只有 4 道独立 test 题，每道占单次任务口径的 25 个百分点。重复运行主要观察稳定性，不能把 12 attempts 视为 12 道独立题。不做显著性或因果结论；效率差异还可能来自内部策略、进程启动、时间漂移和服务负载。

Aider 无内部工具/安全事件观测，报告为 N/A。底层 result.json 中的 tool_calls=0 只代表适配器记录到零个工具事件，必须结合 manifest.configuration.tool_metrics_available=false 解读，不能视为内部零调用。ZzhClaw 的安全计数也只是工具字符串近似；本地目录副本不提供 OS 读写/网络隔离。

工程预试保留在本地：cross-dev 为网络受限失败；cross-dev-network 为历史路径修复前 dev；cross-test-history-draft 在 2 次通过和 1 次中断后停止。发现 Aider 将聊天历史写入上层仓库，随后显式隔离历史路径并重跑 dev/test。任务、Prompt 和验收未根据预试成绩修改，但已看到部分相同 test 结果，因此本实验不宣称严格盲测。预试不计入最终成绩。

## 失败诊断

- zzhclaw：0 个非通过案例；规则诊断 {}。
- aider：0 个非通过案例；规则诊断 {}。

本轮没有任务级失败；ZzhClaw 轨迹未记录工具错误。Aider 的内部工具事件不可观测，不能据外部通过推断其内部没有重试或错误。

## 复现证据

- 完整任务资源验收 SHA256：`dbae0a56859368ded97cbd0e4102f933188585f7aa372af456d516ddc84fc059`。
- test 选中资源 SHA256：`22b94678e4c9b013b26c1f94148ddc671919a9ebb59c34c7c4d330ca6994993b`。
- 冻结源码 SHA256：`59c15323f6d68765f2e9ef4dd076409cc296610dac8d34ecf24019bb8fa3fd95`。
- ZzhClaw 默认系统提示词 SHA256：`c38ca0fa44f06da2bc70e3657ae60e2613567ef3ac7413acddb2110bf4072d0a`。
- 代码工作区尚未提交；manifest 记录 Git 基线与 dirty 状态及源码内容指纹。Aider 启动文件/版本、端点指纹、任务规格与进程预算见各运行 manifest。
- 本地原始产物：`runs/python-challenge-v0.1/cross-test/{zzhclaw,aider}`，包含 manifest/summary/report、每次 result/trace/agent.log、修复工作区与隔离的 Aider 历史；未提交 Git。
- 配对报告：`runs/python-challenge-v0.1/cross-test/comparison.md`。验收证据：`runs/python-challenge-v0.1/verification.json`。Aider 精确依赖清单：`runs/python-challenge-v0.1/aider-environment.txt`。
- 工程验证：353 passed / 3 skipped（缺少真实流录制 fixture）；相关代码 Ruff E/F/I 通过；6/6 原始失败、参考通过。

复现命令与方法见 [README](README.md)。Aider 接口来自 [官方 scripting 文档](https://aider.chat/docs/scripting.html) 与 [CLI options](https://aider.chat/docs/config/options.html)。
