from __future__ import annotations
from decimal import Decimal
from datetime import date
from typing import Optional, List
from domain.value_objects.money import Money
from domain.value_objects.currency import Currency
from domain.value_objects.exchange_rate import ExchangeRate
from domain.entities import DomainError


class CurrencyConversionService:
    """
    سرویس تبدیل ارز
    مسئولیت: تبدیل مبلغ بین ارزهای مختلف با استفاده از نرخ‌های معتبر
    """

    def __init__(self, exchange_rates: Optional[List[ExchangeRate]] = None):
        self._rates: List[ExchangeRate] = exchange_rates or []

    def add_rate(self, rate: ExchangeRate) -> None:
        """افزودن نرخ ارز جدید"""
        self._rates.append(rate)

    def get_rate(
        self,
        source: Currency,
        target: Currency,
        on_date: date,
        rate_type: Optional[str] = None
    ) -> ExchangeRate:
        """
        یافتن مناسب‌ترین نرخ ارز برای تاریخ مشخص
        اولویت: دقیق‌ترین نرخ معتبر در تاریخ درخواست‌شده
        """
        candidates = [
            r for r in self._rates
            if r.source_currency == source
            and r.target_currency == target
            and r.is_valid_on(on_date)
        ]

        if rate_type:
            candidates = [r for r in candidates if r.rate_type.lower() == rate_type.lower()]

        if not candidates:
            raise DomainError(
                f"نرخ ارز معتبری از {source.value} به {target.value} برای تاریخ {on_date} یافت نشد"
            )

        # انتخاب نزدیک‌ترین نرخ به تاریخ درخواستی
        candidates.sort(key=lambda r: abs((r.rate_date - on_date).days))
        return candidates[0]

    def convert(
        self,
        money: Money,
        target_currency: Currency,
        on_date: date,
        rate_type: Optional[str] = None
    ) -> Money:
        """
        تبدیل مبلغ به ارز هدف
        """
        if money.currency == target_currency:
            return money

        rate = self.get_rate(
            source=money.currency,
            target=target_currency,
            on_date=on_date,
            rate_type=rate_type
        )

        converted_amount = rate.convert(money.amount)
        return Money.of(converted_amount, target_currency)

    def convert_with_rate(
        self,
        money: Money,
        rate: ExchangeRate
    ) -> Money:
        """
        تبدیل با نرخ مشخص (بدون جستجو)
        """
        if money.currency != rate.source_currency:
            raise DomainError(
                f"ارز مبدأ مبلغ ({money.currency.value}) با ارز مبدأ نرخ ({rate.source_currency.value}) مطابقت ندارد"
            )

        converted_amount = rate.convert(money.amount)
        return Money.of(converted_amount, rate.target_currency)

    def get_available_rates(
        self,
        source: Optional[Currency] = None,
        target: Optional[Currency] = None,
        on_date: Optional[date] = None
    ) -> List[ExchangeRate]:
        """لیست نرخ‌های موجود با فیلتر اختیاری"""
        result = self._rates

        if source:
            result = [r for r in result if r.source_currency == source]
        if target:
            result = [r for r in result if r.target_currency == target]
        if on_date:
            result = [r for r in result if r.is_valid_on(on_date)]

        return result