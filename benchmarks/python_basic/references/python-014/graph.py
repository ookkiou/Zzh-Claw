def dependency_order(graph):
    remaining = {node: set(deps) for node, deps in graph.items()}
    for deps in list(remaining.values()):
        for node in deps:
            remaining.setdefault(node, set())
    result = []
    while remaining:
        ready = sorted(node for node, deps in remaining.items() if not deps)
        if not ready:
            raise ValueError("cycle")
        node = ready[0]
        result.append(node)
        del remaining[node]
        for deps in remaining.values():
            deps.discard(node)
    return result
