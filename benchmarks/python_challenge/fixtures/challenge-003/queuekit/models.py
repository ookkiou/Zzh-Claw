from dataclasses import dataclass

@dataclass(frozen=True)
class Lease:
    key: str
    payload: object
    token: str
    deadline: float
