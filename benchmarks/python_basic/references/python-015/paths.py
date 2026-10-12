from pathlib import Path


def resolve_inside(root, relative):
    base = Path(root).resolve()
    rel = Path(relative)
    if rel.is_absolute():
        raise ValueError("absolute")
    path = (base / rel).resolve()
    if not path.is_relative_to(base):
        raise ValueError("outside")
    return path
