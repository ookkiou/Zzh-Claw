def retry_call(fn, attempts, exceptions=(Exception,)):
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts <= 0:
        raise ValueError("invalid attempts")
    for index in range(attempts):
        try:
            return fn()
        except exceptions:
            if index + 1 == attempts:
                raise
