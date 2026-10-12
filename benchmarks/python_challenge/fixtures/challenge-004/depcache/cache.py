from copy import deepcopy

class DependencyCache:
    def __init__(self):
        self.values={}
        self.deps={}

    def set(self,key,value,deps=()):
        deps=set(deps)
        if key in deps or any(dep not in self.values for dep in deps):
            raise ValueError('invalid dependency')
        def reaches(node,seen):
            if node==key:
                return True
            if node in seen:
                return False
            seen.add(node)
            return any(reaches(dep,seen) for dep in self.deps.get(node,()))
        if any(reaches(dep,set()) for dep in deps):
            raise ValueError('cycle')
        self.values.pop(key,None)
        self.values[key]=value
        self.deps[key]=deps

    def get(self,key):
        return self.values[key]

    def invalidate(self,key):
        pending={key}
        changed=True
        while changed:
            changed=False
            for node,deps in self.deps.items():
                if node not in pending and deps & pending:
                    pending.add(node)
                    changed=True
        removed=pending & self.values.keys()
        for node in removed:
            del self.values[node]
            self.deps.pop(node,None)
        return set(removed)
