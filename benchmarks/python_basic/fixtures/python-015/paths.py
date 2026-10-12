from pathlib import Path


def resolve_inside(root, relative):
    path = (Path(root) / relative).resolve()
    if not str(path).startswith(str(Path(root).resolve())):
        raise ValueError("outside")
    return path
