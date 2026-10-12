# 事务转账与幂等重试

修复 ledger.Ledger.transfer(key,source,target,value)。余额输入为 Decimal；转账金额允许十进制字符串/数字，必须有限、正数、至多两位有效小数（1.230 合法），bool 非法。禁止同账户、未知账户及余额不足。失败不得改变余额或占用 key；成功 key 相同参数（金额按数值比较）重试返回原回执，不再次扣款，参数冲突抛 ValueError。回执包含 key/source/target/amount，amount 为 Decimal，调用者修改回执不应影响后续重试。构造时复制余额字典。
