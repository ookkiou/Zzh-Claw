# 依赖工作流执行器

修复 workflow.plan(graph) 和 workflow.run(graph,actions)。graph 映射字符串任务名到依赖列表。plan 返回拓扑顺序，每一步从当前可执行任务中按字典序取最小者；空图返回空。未知依赖、环、缺少 callable action 必须在执行任何 action 前抛 ValueError。run 中普通 Exception 将该任务记为 failed，依赖失败或 skipped 的任务跳过，独立分支继续；成功为 passed。不得修改 graph/actions，连续调用无状态泄漏。重复依赖不影响结果。
