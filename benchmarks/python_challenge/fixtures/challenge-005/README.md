# 增量二进制帧解码

修复 framekit.encode(bytes) 和 Decoder(max_size=1024) 的 feed(bytes)/finish()/reset()。协议是4字节大端无符号长度加 payload，允许空 payload。feed 支持任意切片、多帧合并、半帧缓存，返回本次完整 payload 列表。头部一齐且长度超过 max_size 就立即 FrameError（ValueError 子类），即使 payload 未到齐。finish 在残留半帧时抛 FrameError，否则 None；finish 后或协议错误后 feed/finish 都抛 FrameError，reset 可恢复且保留 max_size。max_size 是非 bool 的非负 int，否则 ValueError。encode/feed 非 bytes 输入抛 TypeError，feed 类型错误不破坏已有缓存。
