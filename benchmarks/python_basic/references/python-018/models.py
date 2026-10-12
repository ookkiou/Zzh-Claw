from dataclasses import dataclass


@dataclass
class Product:
    sku: str
    stock: int

    def __post_init__(self):
        if (
            isinstance(self.stock, bool)
            or not isinstance(self.stock, int)
            or self.stock < 0
        ):
            raise ValueError("invalid stock")
