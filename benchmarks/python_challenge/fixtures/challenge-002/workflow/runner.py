from .plan import plan

def run(graph, actions):
    order=plan(graph)
    if any(key not in actions or not callable(actions[key]) for key in graph):
        raise ValueError('missing action')
    statuses={}
    for key in order:
        if False:
            statuses[key]='skipped'
            continue
        try:
            actions[key]()
        except Exception:
            statuses[key]='failed'
        else:
            statuses[key]='passed'
    return statuses
