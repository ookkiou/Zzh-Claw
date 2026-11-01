# python-repo v0.1 真实基线

日期：2026-10-22（Asia/Shanghai）。使用固定 ZzhClaw 历史版本的维护任务，先 dev 后 test，每题独立执行一次。

## 任务与验收

- 来源：`2ab74cee27b48a1241c0e7cdc0e2c5430087de5a`，42 个原始文件、288,208 字节，源码未注入缺陷，保留 MIT 许可证与逐文件 SHA256。
- 6 个维护者编写的复现任务，3 dev / 3 test；外部新增目标测试共 50 个参数化实例。
- 6/6 原始实现均在新增目标测试失败且原回归通过；6/6 参考修复均通过两个阶段。
- 每题原回归 247 passed / 3 skipped；摘要任务只替代已声明的旧契约用例，246 passed / 3 skipped / 1 deselected。
- 外部固定测试和 pytest 配置，钉住目标包导入来源；修改工作区中的测试不会修改外部判分。

## 实验配置

- 请求模型 ID：`deepseek-flash`，使用本地配置的同一兼容服务。
- ZzhClaw 默认系统 Prompt，24 次循环预算，300 秒 Agent 预算，90 秒独立验收预算；保留修复后的工作区。
- dev 用于验证运行条件；test 前冻结配置，未用 test 结果修改 Prompt 或验收。每题仅一次，不报告三次稳定性。
- 首次 dev 在模型调用前因任务仓库同名包遮蔽宿主 worker 而启动失败，保存在 zzhclaw-dev-import-draft；修复宿主入口并加回归测试后重新运行，预试不计入下表。

## 实测结果

| Split | 通过 | 任务成功率 | 平均耗时 | 平均工具调用 |
|---|---:|---:|---:|---:|
| dev | 3/3 | 100.0% | 59.99 秒 | 21.00 |
| test | 3/3 | 100.0% | 54.83 秒 | 20.00 |

| 任务 | 状态 | 新目标 / 原回归退出码 |
|---|---|---|
| repo-001 | passed | 0 / 0 |
| repo-002 | passed | 0 / 0 |
| repo-003 | passed | 0 / 0 |
| repo-004 | passed | 0 / 0 |
| repo-005 | passed | 0 / 0 |
| repo-006 | passed | 0 / 0 |

Token/cost 尚未接入，继续显示 N/A。耗时包含 Agent 启动、模型、工具和外部验收，不能直接与旧短题集的耗时解释为同等任务效率。

## 结论

本轮 6/6 通过，证明当前 Agent 在这些完整仓库维护场景中能修复目标问题并保持原有回归；当前任务仍未产生成功率区分。下一批应增加跨模块修改和更长的定位/修复链路，而非据本轮满分宣称通用能力。
这是单仓库同版本的少量维护任务，公开源码和维护者编写的任务不属于严格盲测，也不代表跨仓库泛化或通用排名。
dev 非通过案例：0；规则诊断：{}。
test 非通过案例：0；规则诊断：{}。

## 复现证据

- 完整资源 SHA256：`56e5f2d6814f4cda604a06c309dc7d2086d1debce46dff516ffec8725b911e86`。
- 宿主源码 SHA256：`8bb8b867dccd32fa12ebe7d393680cf2cd5d4a6b5a1afefdb4ba5a7040f61622`。
- 本地原始产物：`runs/python-repo-v0.1/{zzhclaw-dev,zzhclaw-test}`，包含 manifest/summary/report、逐题 result/trace/agent.log 和保留的工作区。
- 质量验收：`runs/python-repo-v0.1/verification.json`。原始数据被 Git 忽略，仅本文件公开汇总。
- 工程验证：382 passed / 3 skipped；新增代码静态检查通过。
- 源码与依赖来自当前本地工作区，manifest 记录 Git 基线、dirty 状态和内容指纹。

复现命令和任务契约见 [README](README.md)。
