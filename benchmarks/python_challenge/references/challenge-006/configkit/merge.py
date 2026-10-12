from copy import deepcopy


def merge(left, right):
    result = deepcopy(left)
    for key, value in right.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        elif isinstance(value, dict):
            result[key] = merge({}, value)
        else:
            result[key] = deepcopy(value)
    return result
