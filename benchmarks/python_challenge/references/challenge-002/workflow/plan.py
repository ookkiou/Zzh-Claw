def plan(graph):
    graph = {key: tuple(deps) for key, deps in graph.items()}
    if any(dep not in graph for deps in graph.values() for dep in deps):
        raise ValueError("unknown dependency")
    pending = set(graph)
    output = []
    while pending:
        ready = sorted(
            key for key in pending if all(dep in output for dep in graph[key])
        )
        if not ready:
            raise ValueError("cycle")
        key = ready[0]
        pending.remove(key)
        output.append(key)
    return output
