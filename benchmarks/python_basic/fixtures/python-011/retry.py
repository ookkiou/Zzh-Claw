def retry_call(fn, attempts, exceptions=(Exception,)):
    return fn()
