import unittest
from datetime import date
from decimal import Decimal

from domain.value_objects.currency import Currency
from domain.value_objects.money import Money
from domain.value_objects.exchange_rate import ExchangeRate
from application.currency_conversion_service import CurrencyConversionService, DomainError


class TestCurrencyConversionService(unittest.TestCase):

    def setUp(self):
        self.service = CurrencyConversionService()

        self.rate_usd_irr = ExchangeRate(
            source_currency=Currency.USD,
            target_currency=Currency.IRR,
            rate=Decimal("580000"),
            rate_date=date(2026, 8, 7),
            rate_type="Spot",
            rate_source="CentralBank",
            valid_from=date(2026, 8, 1),
            valid_to=date(2026, 8, 31)
        )
        self.service.add_rate(self.rate_usd_irr)

        self.rate_eur_irr = ExchangeRate(
            source_currency=Currency.EUR,
            target_currency=Currency.IRR,
            rate=Decimal("630000"),
            rate_date=date(2026, 8, 7),
            rate_type="Spot",
            rate_source="CentralBank",
            valid_from=date(2026, 8, 1),
            valid_to=date(2026, 8, 31)
        )
        self.service.add_rate(self.rate_eur_irr)

    def test_convert_same_currency(self):
        money = Money.of(1000, Currency.IRR)
        result = self.service.convert(money, Currency.IRR, date(2026, 8, 7))
        self.assertEqual(result.amount, Decimal("1000"))
        self.assertEqual(result.currency, Currency.IRR)

    def test_convert_usd_to_irr(self):
        money = Money.of(100, Currency.USD)
        result = self.service.convert(money, Currency.IRR, date(2026, 8, 7))
        self.assertEqual(result.amount, Decimal("58000000"))
        self.assertEqual(result.currency, Currency.IRR)

    def test_convert_with_specific_rate(self):
        money = Money.of(50, Currency.USD)
        result = self.service.convert_with_rate(money, self.rate_usd_irr)
        self.assertEqual(result.amount, Decimal("29000000"))
        self.assertEqual(result.currency, Currency.IRR)

    def test_get_rate_success(self):
        rate = self.service.get_rate(Currency.USD, Currency.IRR, date(2026, 8, 15))
        self.assertEqual(rate.rate, Decimal("580000"))

    def test_get_rate_not_found(self):
        with self.assertRaises(DomainError):
            self.service.get_rate(Currency.USD, Currency.EUR, date(2026, 8, 15))

    def test_rate_outside_validity_period(self):
        with self.assertRaises(DomainError):
            self.service.get_rate(Currency.USD, Currency.IRR, date(2026, 9, 15))

    def test_convert_currency_mismatch_in_rate(self):
        money = Money.of(100, Currency.EUR)
        with self.assertRaises(DomainError):
            self.service.convert_with_rate(money, self.rate_usd_irr)

    def test_get_available_rates(self):
        rates = self.service.get_available_rates(source=Currency.USD)
        self.assertEqual(len(rates), 1)
        self.assertEqual(rates[0].target_currency, Currency.IRR)

    def test_add_multiple_rates_and_select_closest(self):
        older_rate = ExchangeRate(
            source_currency=Currency.USD,
            target_currency=Currency.IRR,
            rate=Decimal("570000"),
            rate_date=date(2026, 8, 1),
            rate_type="Spot",
            rate_source="CentralBank",
            valid_from=date(2026, 8, 1),
            valid_to=date(2026, 8, 31)
        )
        self.service.add_rate(older_rate)

        rate = self.service.get_rate(Currency.USD, Currency.IRR, date(2026, 8, 10))
        self.assertEqual(rate.rate, Decimal("580000"))


if __name__ == "__main__":
    unittest.main()
