# 带租约的内存队列

实现 queuekit.LeaseQueue(clock,ttl=10)。ttl 必须大于0，clock 为注入的单调时钟。put(key,payload) 深复制负载，未 ack 的相同 key（含租约过期）不可重复入队，抛 ValueError。claim() 以入队顺序取最早未租用或已过期项，空时返回 None；返回 frozen Lease(key,payload,token,deadline)，payload 与队列内部隔离，每次租约 token 都不同（同 key ack 后重新入队也不能复用）。租约在 now>=deadline 失效，过期项仍保留原入队位置。ack(key,token) 仅有效未过期 token 可删除并返回 True，否则 False 且不能改状态。实例互相独立。
