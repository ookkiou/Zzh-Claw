def fibonacci(n: int) -> list[int]:
    """计算斐波那契数列前 n 项。

    斐波那契数列定义：
        F(0) = 0
        F(1) = 1
        F(n) = F(n-1) + F(n-2)  (n >= 2)

    参数:
        n: 要生成的项数（非负整数）

    返回:
        包含前 n 项的列表

    示例:
        >>> fibonacci(10)
        [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]
    """
    if not isinstance(n, int) or n < 0:
        raise ValueError("n 必须是非负整数")

    if n == 0:
        return []

    # 动态规划迭代求解，时间复杂度 O(n)，空间复杂度 O(1)
    fib = [0] * n
    if n >= 1:
        fib[0] = 0
    if n >= 2:
        fib[1] = 1
    for i in range(2, n):
        fib[i] = fib[i - 1] + fib[i - 2]
    return fib


if __name__ == "__main__":
    for count in (0, 1, 2, 5, 10, 20):
        print(f"fibonacci({count}) = {fibonacci(count)}")
