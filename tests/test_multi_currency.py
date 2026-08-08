"""
تست‌های پشتیبانی Multi-Currency
"""
import os
import sys
import unittest
from decimal import Decimal
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from domain.entities import (
    Account, AccountType, JournalEntry, JournalLine, DomainError, JournalEntryStatus
)
from domain.value_objects.currency import Currency
from domain.value_objects.exchange_rate import ExchangeRate
from application.services import ChartOfAccountsService, JournalService
from application.currency_conversion_service import CurrencyConversionService
from infrastructure.repositories import (
    SchemaBuilder, SqliteAccountRepository, SqliteJournalRepository, SqliteAuditLog
)

TEST_DB = "multi_currency_test.db"


class TestMultiCurrency(unittest.TestCase):

    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

        SchemaBuilder.create_all(TEST_DB)
        self.account_repo = SqliteAccountRepository(TEST_DB)
        self.journal_repo = SqliteJournalRepository(TEST_DB)
        self.audit_log = SqliteAuditLog(TEST_DB)
        self.coa_service = ChartOfAccountsService(self.account_repo)
        self.journal_service = JournalService(self.journal_repo, self.account_repo, self.audit_log)

        # حساب‌های نمونه
        self.coa_service.add_account(Account("1-101-01", "صندوق", AccountType.ASSET))
        self.coa_service.add_account(Account("1-103", "حساب‌های دریافتنی", AccountType.ASSET))
        self.coa_service.add_account(Account("4-401", "فروش کالا", AccountType.REVENUE))

        # سرویس تبدیل ارز
        self.conversion_service = CurrencyConversionService()

        # نرخ دلار به ریال
        self.conversion_service.add_rate(ExchangeRate(
            source_currency=Currency.USD,
            target_currency=Currency.IRR,
            rate=Decimal("580000"),
            rate_date=date(2026, 8, 1),
            rate_type="Spot",
            rate_source="CentralBank",
            valid_from=date(2026, 8, 1),
            valid_to=date(2026, 12, 31)
        ))

    def tearDown(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_same_currency_entry_works(self):
        """سند با ارز یکسان (ریال) باید بدون مشکل ثبت شود"""
        entry = JournalEntry(
            entry_date=date(2026, 8, 10),
            base_currency=Currency.IRR,
            lines=[
                JournalLine("1-101-01", debit=Decimal("1000000"), currency=Currency.IRR),
                JournalLine("4-401", credit=Decimal("1000000"), currency=Currency.IRR),
            ],
            fiscal_year="1405",
        )

        posted = self.journal_service.create_and_post(
            entry, user="admin", conversion_service=self.conversion_service
        )

        self.assertEqual(posted.status, JournalEntryStatus.POSTED)
        self.assertTrue(posted.is_balanced)
        self.assertEqual(posted.total_debit_in_base, Decimal("1000000.00"))

    def test_multi_currency_entry_is_converted_and_balanced(self):
        """سند چندارزی باید به ارز پایه تبدیل و تراز شود"""
        entry = JournalEntry(
            entry_date=date(2026, 8, 10),
            base_currency=Currency.IRR,
            lines=[
                # دریافت ۱۰۰ دلار
                JournalLine(
                    "1-101-01",
                    debit=Decimal("100"),
                    currency=Currency.USD,
                    description="دریافت دلار"
                ),
                # فروش معادل ریالی
                JournalLine(
                    "4-401",
                    credit=Decimal("58000000"),
                    currency=Currency.IRR,
                    description="فروش کالا"
                ),
            ],
            fiscal_year="1405",
        )

        posted = self.journal_service.create_and_post(
            entry, user="admin", conversion_service=self.conversion_service
        )

        self.assertEqual(posted.status, JournalEntryStatus.POSTED)
        self.assertTrue(posted.is_balanced)

        # مبلغ دلار باید تبدیل شده باشد
        usd_line = posted.lines[0]
        self.assertEqual(usd_line.amount_in_base, Decimal("58000000"))
        self.assertEqual(usd_line.exchange_rate, Decimal("580000"))

    def test_unbalanced_multi_currency_entry_is_rejected(self):
        """سند چندارزی نامتوازن باید رد شود"""
        entry = JournalEntry(
            entry_date=date(2026, 8, 10),
            base_currency=Currency.IRR,
            lines=[
                JournalLine("1-101-01", debit=Decimal("100"), currency=Currency.USD),
                JournalLine("4-401", credit=Decimal("50000000"), currency=Currency.IRR),  # مبلغ اشتباه
            ],
            fiscal_year="1405",
        )

        with self.assertRaises(DomainError):
            self.journal_service.create_and_post(
                entry, user="admin", conversion_service=self.conversion_service
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)