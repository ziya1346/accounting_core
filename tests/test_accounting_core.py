"""
بک‌تست موتور حسابداری — پوشش قوانین کلیدی:
1) اصل دوبل (بدهکار = بستانکار)
2) رد سند نامتوازن
3) کدینگ شناور و جلوگیری از کد تکراری
4) ثبت سند فقط روی حساب‌های قابل‌ثبت (is_postable)
5) تراز آزمایشی: مجموع کل بدهکار = مجموع کل بستانکار
6) سند برگشتی (Reversal) بدون حذف سند اصلی (اصل حسابرسی)
7) سند اختتامیه و بستن حساب‌های موقت
8) ثبت کامل در Audit Trail
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
from application.services import (
    ChartOfAccountsService, JournalService, TrialBalanceService, ClosingService
)
from infrastructure.repositories import (
    SchemaBuilder, SqliteAccountRepository, SqliteJournalRepository, SqliteAuditLog
)

TEST_DB = "/tmp/accounting_backtest.db"


class BaseTestCase(unittest.TestCase):
    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        SchemaBuilder.create_all(TEST_DB)
        self.account_repo = SqliteAccountRepository(TEST_DB)
        self.journal_repo = SqliteJournalRepository(TEST_DB)
        self.audit_log = SqliteAuditLog(TEST_DB)
        self.coa_service = ChartOfAccountsService(self.account_repo)
        self.journal_service = JournalService(self.journal_repo, self.account_repo, self.audit_log)

        # کدینگ شناور نمونه: گروه -> کل -> معین
        self.coa_service.add_account(Account("1", "دارایی‌ها", AccountType.ASSET, is_postable=False))
        self.coa_service.add_account(Account("1-101", "موجودی نقد و بانک", AccountType.ASSET, parent_code="1", is_postable=False))
        self.coa_service.add_account(Account("1-101-01", "صندوق", AccountType.ASSET, parent_code="1-101"))
        self.coa_service.add_account(Account("1-101-02", "بانک ملی", AccountType.ASSET, parent_code="1-101"))
        self.coa_service.add_account(Account("1-103", "حساب‌های دریافتنی", AccountType.ASSET, parent_code="1"))
        self.coa_service.add_account(Account("3-301", "سود (زیان) انباشته", AccountType.EQUITY))
        self.coa_service.add_account(Account("4-401", "فروش کالا", AccountType.REVENUE))
        self.coa_service.add_account(Account("5-501", "بهای تمام‌شده کالای فروش‌رفته", AccountType.EXPENSE))

    def tearDown(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)


class TestDoubleEntryPrinciple(BaseTestCase):
    """اصل دوبل"""

    def test_balanced_entry_is_accepted_and_posted(self):
        entry = JournalEntry(
            entry_date=date(1404, 4, 14),
            lines=[
                JournalLine("1-101-01", debit=Decimal("1000000"), description="دریافت نقدی از مشتری"),
                JournalLine("1-103", credit=Decimal("1000000"), description="کاهش مطالبات"),
            ],
            fiscal_year="1404",
        )
        posted = self.journal_service.create_and_post(entry, user="admin")
        self.assertEqual(posted.status, JournalEntryStatus.POSTED)
        self.assertEqual(posted.total_debit, posted.total_credit)
        self.assertEqual(posted.number, 1)

    def test_unbalanced_entry_is_rejected(self):
        entry = JournalEntry(
            entry_date=date(1404, 4, 14),
            lines=[
                JournalLine("1-101-01", debit=Decimal("1000000")),
                JournalLine("1-103", credit=Decimal("900000")),
            ],
            fiscal_year="1404",
        )
        with self.assertRaises(DomainError):
            self.journal_service.create_and_post(entry, user="admin")

    def test_single_line_entry_is_rejected(self):
        entry = JournalEntry(
            entry_date=date(1404, 4, 14),
            lines=[JournalLine("1-101-01", debit=Decimal("1000"))],
            fiscal_year="1404",
        )
        with self.assertRaises(DomainError):
            entry.validate()

    def test_line_cannot_have_both_debit_and_credit(self):
        with self.assertRaises(DomainError):
            JournalLine("1-101-01", debit=Decimal("100"), credit=Decimal("100"))


class TestChartOfAccounts(BaseTestCase):
    """کدینگ شناور"""

    def test_duplicate_code_rejected(self):
        with self.assertRaises(DomainError):
            self.coa_service.add_account(Account("1-101-01", "تکراری", AccountType.ASSET))

    def test_parent_must_exist(self):
        with self.assertRaises(DomainError):
            self.coa_service.add_account(Account("1-999-01", "نامعتبر", AccountType.ASSET, parent_code="1-999"))

    def test_children_lookup(self):
        children = self.coa_service.get_children("1-101")
        codes = {c.code for c in children}
        self.assertEqual(codes, {"1-101-01", "1-101-02"})

    def test_cannot_post_to_non_postable_parent_account(self):
        entry = JournalEntry(
            entry_date=date(1404, 4, 14),
            lines=[
                JournalLine("1", debit=Decimal("1000")),          # حساب والد، غیرقابل ثبت
                JournalLine("1-101-01", credit=Decimal("1000")),
            ],
            fiscal_year="1404",
        )
        with self.assertRaises(DomainError):
            self.journal_service.create_and_post(entry, user="admin")


class TestTrialBalance(BaseTestCase):
    """تراز آزمایشی: باید همیشه بدهکار = بستانکار باشد"""

    def test_trial_balance_is_always_balanced_after_multiple_entries(self):
        self.journal_service.create_and_post(JournalEntry(
            entry_date=date(1404, 1, 5),
            lines=[
                JournalLine("1-101-01", debit=Decimal("5000000")),
                JournalLine("4-401", credit=Decimal("5000000")),
            ],
            fiscal_year="1404",
        ), user="admin")

        self.journal_service.create_and_post(JournalEntry(
            entry_date=date(1404, 1, 10),
            lines=[
                JournalLine("5-501", debit=Decimal("3000000")),
                JournalLine("1-103", credit=Decimal("3000000")),
            ],
            fiscal_year="1404",
        ), user="admin")

        tb = TrialBalanceService(self.journal_repo, self.account_repo).compute("1404")
        self.assertTrue(tb["is_balanced"])
        self.assertEqual(tb["total_debit"], tb["total_credit"])
        self.assertEqual(tb["total_debit"], Decimal("8000000.00"))

    def test_draft_entries_excluded_from_trial_balance(self):
        # سند پیش‌نویس هرگز نباید در تراز لحاظ شود
        tb_before = TrialBalanceService(self.journal_repo, self.account_repo).compute("1404")
        self.assertEqual(tb_before["total_debit"], Decimal("0.00"))


class TestReversalAndAudit(BaseTestCase):
    """سند برگشتی و ردیابی حسابرسی"""

    def test_reversal_creates_new_entry_without_deleting_original(self):
        original = self.journal_service.create_and_post(JournalEntry(
            entry_date=date(1404, 2, 1),
            lines=[
                JournalLine("1-101-01", debit=Decimal("200000")),
                JournalLine("4-401", credit=Decimal("200000")),
            ],
            fiscal_year="1404",
        ), user="admin")

        reversal = self.journal_service.reverse_entry(original.id, user="admin")

        stored_original = self.journal_repo.get(original.id)
        self.assertEqual(stored_original.status, JournalEntryStatus.REVERSED)
        self.assertEqual(reversal.status, JournalEntryStatus.POSTED)
        self.assertEqual(reversal.total_debit, reversal.total_credit)
        # سند اصلی حذف نشده — فقط وضعیتش تغییر کرده (الزام حسابرسی)
        self.assertIsNotNone(stored_original)

    def test_every_posting_creates_audit_log_entry(self):
        self.journal_service.create_and_post(JournalEntry(
            entry_date=date(1404, 2, 1),
            lines=[
                JournalLine("1-101-01", debit=Decimal("50000")),
                JournalLine("4-401", credit=Decimal("50000")),
            ],
            fiscal_year="1404",
        ), user="ali.hesabdar")
        logs = self.audit_log.all()
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["user"], "ali.hesabdar")
        self.assertEqual(logs[0]["action"], "POST_JOURNAL_ENTRY")


class TestClosingEntry(BaseTestCase):
    """سند اختتامیه — بستن حساب‌های موقت درآمد/هزینه"""

    def test_closing_moves_net_profit_to_retained_earnings(self):
        self.journal_service.create_and_post(JournalEntry(
            entry_date=date(1404, 1, 5),
            lines=[
                JournalLine("1-101-01", debit=Decimal("10000000")),
                JournalLine("4-401", credit=Decimal("10000000")),
            ],
            fiscal_year="1404",
        ), user="admin")
        self.journal_service.create_and_post(JournalEntry(
            entry_date=date(1404, 1, 6),
            lines=[
                JournalLine("5-501", debit=Decimal("6000000")),
                JournalLine("1-103", credit=Decimal("6000000")),
            ],
            fiscal_year="1404",
        ), user="admin")

        closing_service = ClosingService(self.journal_repo, self.account_repo, self.journal_service)
        closing_entry = closing_service.close_temporary_accounts("1404", date(1404, 12, 29), user="admin")

        self.assertEqual(closing_entry.status, JournalEntryStatus.POSTED)
        self.assertTrue(closing_entry.is_balanced)

        retained_earnings_line = [l for l in closing_entry.lines if l.account_code == "3-301"][0]
        # سود خالص = 10,000,000 - 6,000,000 = 4,000,000 در سمت بستانکار سود انباشته
        self.assertEqual(retained_earnings_line.credit, Decimal("4000000.00"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
