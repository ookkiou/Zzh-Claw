# 依赖缓存传递失效

修复 depcache.DependencyCache 的 set(key,value,deps=()) / get(key) / invalidate(key)。set 依赖必须全部已有，不得自依赖或形成环（替换已有 key 也要先检测）；非法 set 抛 ValueError 且原缓存不变。合法替换已有 key 应使其所有传递依赖者失效，再保存新值/新依赖；其他节点保留。invalidate 返回被删除 key 的集合，未知 key 返回空集合。get 未知 key 抛 KeyError。输入/输出 value 均深复制，deps 不保留调用者可变引用；多个实例独立。
