# python-repo v0.1

本轮真实基线见 [RESULTS.md](RESULTS.md)。

这套任务使用 ZzhClaw 的真实历史源码，要求在完整仓库中定位问题、修改实现并通过原有回归测试。6 个任务共用固定源快照，每次运行仍复制成独立工作区。

来源提交：[2ab74cee27b48a1241c0e7cdc0e2c5430087de5a](https://github.com/ookkiou/Zzh-Claw/tree/2ab74cee27b48a1241c0e7cdc0e2c5430087de5a)，MIT 许可证保留在快照内。42 个原始文件共 288,208 字节，包含应用源码、Web 静态资源、配置、README、许可证与原有测试。原文件逐项 SHA256 见 [source.json](source.json)。原始实现未作缺陷注入；任务需求和复现用例由本项目维护者根据该版本行为编写，不是收录的上游 issue/PR。

| ID | Split | 任务 | 修复要求 |
|---|---|---|---|
| repo-001 | dev | 命令输出解码 | 保留非 UTF-8 输出中的有效文本及退出反馈 |
| repo-002 | dev | 命令环境 | 不向普通工具命令继承指定凭据，保留开发变量 |
| repo-003 | dev | 搜索参数边界 | 无效上限在扫描前返回错误，合法行为不变 |
| repo-004 | test | 会话文件路径 | 约束 ID、拒绝穿越和目录外软链，保留正常读写 |
| repo-005 | test | 分支消息所有权 | 嵌套消息可变对象独立，序列化和 ID 兼容 |
| repo-006 | test | 分支摘要 | 丢弃覆盖未来消息的摘要，正确继承已有事实 |

## 验收方式

1. 执行工作区代码上的新增目标测试，共 50 个参数化实例。
2. 执行外部冻结的原回归测试。一般为 247 passed / 3 skipped；跳过项是原版本缺少真实流录制 fixture。
3. repo-006 明确改变摘要旧契约，因此只排除 `test_fork_inherits_summary_clamped_to_fork_point` 这一条旧行为断言，其他回归保留（246 passed / 3 skipped / 1 deselected），并通过新增用例验证新行为。

外部 driver 固定 pytest 配置，确认 `zzhclaw` 从目标工作区导入。工作区中的测试和 pytest 配置修改不会更改外部判分。参考修复只存在于工作区之外，不作为运行输入。`eval verify` 要求原始实现仅在新增目标用例上失败，而原回归通过；参考修复须两阶段均通过。

这是受信任的本地执行环境，复用宿主已安装的依赖，不自动安装依赖、不联网运行验收。普通工具进程提供 `ZZHCLAW_PYTHON`，可执行 `"$ZZHCLAW_PYTHON" -m pytest`。外部目标测试不在 Agent 的本地测试列表中，因此“本地原测试全过”不等于任务通过。

## 使用

从项目根目录执行：

```bash
zzhclaw eval verify benchmarks/python_repo/benchmark.json \
  --output runs/python-repo/verification.json

# 先用 dev 验证运行条件
zzhclaw eval run benchmarks/python_repo/benchmark.json \
  --split dev --repeat 1 --max-iterations 24 --task-timeout 300 \
  --keep-workspaces --output runs/python-repo/dev

# 冻结配置后运行 test
zzhclaw eval run benchmarks/python_repo/benchmark.json \
  --split test --repeat 1 --max-iterations 24 --task-timeout 300 \
  --keep-workspaces --output runs/python-repo/test
zzhclaw eval analyze runs/python-repo/test
```

Agent 进程预算 300 秒；验收总预算 90 秒，其中新增目标用例和原回归各最多 40 秒。Agent 与验收预算独立。第一轮每题一次，只报告成功率和轨迹，不称为三次稳定性实验。

## 解释范围

这是单仓库、同版本任务集；dev/test 按缺陷划分并分别聚焦工具与会话模块，不代表仓库之间独立。6 道题和多个参数化用例也不是同样数量的独立真实问题。维护者知道参考修复，公开源码可能被模型见过，本轮用于维护场景基线，不宣称严格盲测或通用排名。增加仓库规模不自动保证难度更高，区分度以实测为准。
