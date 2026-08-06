# 修复 TUI 工具确认时无法输入「是/否」

## 问题
TUI 异步化后,工具确认提示出现时,用户无法在输入框输入「是/否」——键盘打字字符不打进输入框。
但用户能用中文输入第一条消息(触发工具),说明中文输入法本身工作正常。

## 根因(推断)
- 症状「字符不打进输入框」= `Input` 失焦(键盘输入不进任何文本框;IME 跟随焦点,故中文也输不进去)。
- 探索确认:Textual 8.2.7,`ScrollableContainer.can_focus=True`(你的 `MessageLog` 继承它,可聚焦),`Input.can_focus=True`,`Static.can_focus=False`。
- 推断:`process_message` / `_show_confirm_prompt` 里 `log.mount(...)` 挂载新 widget(thinking 提示、确认提示)后,Textual 的焦点从 `Input` 转移到了可聚焦的 `MessageLog` 容器,导致 `Input` 失焦。
- 异步化前 `agent.run` 同步阻塞事件循环,用户在工具调用期间根本无法输入,问题被掩盖;异步化后事件循环保持响应,才暴露这个失焦问题。

## 改动(主修复)
文件:`zzhclaw/tui/app.py`

### 改动 1:`_show_confirm_prompt` 末尾聚焦 Input
位置:`_show_confirm_prompt` 方法,在 `self._set_input_placeholder("输入 是 确认 / 否 取消")` 之后
新增一行:
```python
self.query_one("#user-input", Input).focus()
```
理由:确认提示出现后必须让 `Input` 重新获得焦点,用户才能输入「是/否」。

### 改动 2:`process_message` 挂载 thinking 后聚焦 Input
位置:`process_message` 里 `log.mount(thinking)` / `log.scroll_end()` 之后,`self.processing = True` 之前
新增一行:
```python
self.query_one("#user-input", Input).focus()
```
理由:防止 thinking 阶段 `Input` 失焦。此时 `processing=True`,用户若尝试输入会被拦截并提示「正在处理中」,比失焦无反应更清晰。

## 备选方案(若主修复无效)
若 `focus()` 因 mount 的 async 时序未生效,改用按键确认绕过 `Input`:
- `_show_confirm_prompt` 里设 `self.query_one("#user-input", Input).disabled = True`(禁用 Input,按键不进 Input)
- 给 `ZzhClawApp` 加 `on_key` 方法:`_confirm_pending` 非空时,按 `y` 确认、`n` 取消(复用 `_handle_confirm_input` 的确认/清理/唤醒逻辑),并 `event.stop()`
- `_handle_confirm_input` 末尾恢复 `Input.disabled = False` 并 `focus()`

## 验证
1. 语法:`python3 -m py_compile zzhclaw/tui/app.py`
2. 启动:`python3 zzhclaw.py`
3. 输入中文「读一下 README.md」→ 确认提示出现后,输入「是」回车 → 工具执行,显示结果和 AI 回复
4. 再试输入「否」回车 → 工具被拒,AI 基于拒绝信息回复
5. 确认过程中输入框字符应正常显示(中文「是/否」或 y/n 均可)

## 不在范围
- 不改确认判断逻辑(`是/否/y/n` 判断已正确)
- 不改异步化架构(`to_thread` + `call_from_thread` + `threading.Event` 保持不变)
