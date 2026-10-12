# 分层配置合并与严格校验

修复 configkit.load(defaults,overrides,env)。优先级 defaults<overrides<env，env 仅识别 APP_PORT/APP_DEBUG，其他变量忽略。递归合并 dict；override 的 None 表示删除该键，列表完全替换；最终结果及其嵌套对象与输入隔离。最终只允许 host/port/debug/database/labels：host 是非空白 str，port 为非 bool 的 int 且1..65535，debug 严格 bool，database 必须恰有 host/port 且同类校验，labels 可选但必须 list[str]。env APP_PORT 只接受 ASCII 十进制数字字符串（前导0合法，不接受符号/空白），APP_DEBUG 接受大小写不敏感 true/false/1/0，不 trim；非法均 ValueError，不能修改任何输入，含失败路径。
