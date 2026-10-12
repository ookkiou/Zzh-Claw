from copy import deepcopy

def merge(left,right):
    result=left.copy()
    for key,value in right.items():
        if value is None:
            result[key]=None
        elif isinstance(value,dict) and isinstance(result.get(key),dict):
            result[key]=merge(result[key],value)
        elif isinstance(value,dict):
            result[key]=merge({},value)
        else:
            result[key]=value
    return result
