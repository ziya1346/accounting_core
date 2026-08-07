from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from .currency import Currency


@dataclass(frozen=True)
class ExchangeRate:
    """Value Object نرخ ارز با اعتبار زمانی"""
    source_currency: Currency
    target_currency: Currency
    rate: Decimal
    rate_date: date
    rate_type: str
    rate_source: str
    valid_from: date
    valid_to: date | None = None

    def __post_init__(self):
        if self.rate <= 0:
            raise ValueError("نرخ ارز باید مثبت باشد")
        if self.source_currency == self.target_currency and self.rate != Decimal("1"):
            raise ValueError("نرخ ارز یکسان باید برابر ۱ باشد")
        if self.valid_to and self.valid_from > self.valid_to:
            raise ValueError("تاریخ شروع اعتبار نمی‌تواند بعد از تاریخ پایان باشد")

    def is_valid_on(self, check_date: date) -> bool:
        if check_date < self.valid_from:
            return False
        if self.valid_to and check_date > self.valid_to:
            return False
        return True

    def convert(self, amount: Decimal) -> Decimal:
        return amount * self.rate
