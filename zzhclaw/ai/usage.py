"""用户配置的文本 token 单价；不推断服务商账单规则。"""

import math
import os
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RequestPricing:
    input_per_million: float
    output_per_million: float
    currency: str = "USD"

    def __post_init__(self):
        for value in (self.input_per_million, self.output_per_million):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("token 单价必须是有限非负数字")
            if not math.isfinite(value) or value < 0:
                raise ValueError("token 单价必须是有限非负数字")
        if not isinstance(self.currency, str) or not self.currency.strip():
            raise ValueError("价格币种不能为空")

    @classmethod
    def from_env(cls):
        input_price = os.getenv("OPENAI_INPUT_PRICE_PER_MILLION")
        output_price = os.getenv("OPENAI_OUTPUT_PRICE_PER_MILLION")
        if input_price is None and output_price is None:
            return None
        if input_price is None or output_price is None:
            raise ValueError("请同时配置输入和输出 token 单价")
        return cls(
            float(input_price),
            float(output_price),
            os.getenv("OPENAI_PRICE_CURRENCY", "USD").strip(),
        )

    def to_dict(self):
        return asdict(self)

    def estimate(self, input_tokens: int, output_tokens: int):
        return (
            input_tokens * self.input_per_million
            + output_tokens * self.output_per_million
        ) / 1_000_000
