def dependents(graph, key):
    return {node for node, deps in graph.items() if key in deps}
