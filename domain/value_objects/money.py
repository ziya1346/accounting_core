from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from dataclasses import dataclass
from .currency import Currency


@dataclass(frozen=True)
class Money:
    """Value Object برای پول — غیرقابل تغییر و با اعتبارسنجی"""
    amount: Decimal
    currency: Currency

    def __post_init__(self):
        object.__setattr__(self, "amount", Decimal(str(self.amount)).quantize(
            Decimal("1") if self.currency.decimal_digits == 0 else Decimal("0.01"),
            rounding=ROUND_HALF_UP
        ))

    @classmethod
    def of(cls, amount, currency: Currency | str) -> "Money":
        if isinstance(currency, str):
            currency = Currency.from_code(currency)
        return cls(Decimal(str(amount)), currency)

    def add(self, other: "Money") -> "Money":
        self._check_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def subtract(self, other: "Money") -> "Money":
        self._check_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def multiply(self, factor) -> "Money":
        return Money(self.amount * Decimal(str(factor)), self.currency)

    def _check_same_currency(self, other: "Money"):
        if self.currency != other.currency:
            raise ValueError(f"ارزها متفاوت هستند: {self.currency} و {other.currency}")

    def __str__(self) -> str:
        return f"{self.amount:,} {self.currency.value}"
