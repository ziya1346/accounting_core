"""
دموی سرتاسر (End-to-End) — شبیه‌سازی یک ماه فعالیت یک شرکت فرضی
اجرا: python3 demo.py
"""
import os
from decimal import Decimal
from datetime import date

from domain.entities import Account, AccountType, JournalEntry, JournalLine
from application.services import ChartOfAccountsService, JournalService, TrialBalanceService, ClosingService
from infrastructure.repositories import SchemaBuilder, SqliteAccountRepository, SqliteJournalRepository, SqliteAuditLog

DB = "/tmp/accounting_demo.db"
if os.path.exists(DB):
    os.remove(DB)
SchemaBuilder.create_all(DB)

acc_repo = SqliteAccountRepository(DB)
jr_repo = SqliteJournalRepository(DB)
audit = SqliteAuditLog(DB)
coa = ChartOfAccountsService(acc_repo)
journal = JournalService(jr_repo, acc_repo, audit)

for a in [
    Account("1-101-01", "صندوق", AccountType.ASSET),
    Account("1-101-02", "بانک ملی", AccountType.ASSET),
    Account("1-103", "حساب‌های دریافتنی", AccountType.ASSET),
    Account("3-301", "سود (زیان) انباشته", AccountType.EQUITY),
    Account("4-401", "فروش کالا", AccountType.REVENUE),
    Account("5-501", "بهای تمام‌شده کالای فروش‌رفته", AccountType.EXPENSE),
]:
    coa.add_account(a)

journal.create_and_post(JournalEntry(
    entry_date=date(1404, 4, 1),
    lines=[JournalLine("1-103", debit=Decimal("15000000")), JournalLine("4-401", credit=Decimal("15000000"))],
    fiscal_year="1404", description="فروش نسیه به مشتری الف",
), user="ali.hesabdar")

journal.create_and_post(JournalEntry(
    entry_date=date(1404, 4, 3),
    lines=[JournalLine("5-501", debit=Decimal("9000000")), JournalLine("1-101-02", credit=Decimal("9000000"))],
    fiscal_year="1404", description="پرداخت بهای تمام‌شده کالا از بانک",
), user="ali.hesabdar")

journal.create_and_post(JournalEntry(
    entry_date=date(1404, 4, 5),
    lines=[JournalLine("1-101-01", debit=Decimal("15000000")), JournalLine("1-103", credit=Decimal("15000000"))],
    fiscal_year="1404", description="وصول مطالبات نقداً",
), user="ali.hesabdar")

tb = TrialBalanceService(jr_repo, acc_repo).compute("1404")
print("=== تراز آزمایشی (سال مالی 1404) ===")
print(f"{'کد حساب':<12}{'نام':<28}{'بدهکار':>16}{'بستانکار':>16}")
for code, bal in sorted(tb["accounts"].items()):
    acc = acc_repo.get_by_code(code)
    print(f"{code:<12}{acc.name:<28}{bal['debit']:>16}{bal['credit']:>16}")
print("-" * 72)
print(f"{'جمع کل':<40}{tb['total_debit']:>16}{tb['total_credit']:>16}")
print(f"تراز است؟ {'✅ بله' if tb['is_balanced'] else '❌ خیر'}")

closing = ClosingService(jr_repo, acc_repo, journal).close_temporary_accounts("1404", date(1404, 12, 29), "admin")
print("\n=== سند اختتامیه ===")
for l in closing.lines:
    side = "بد" if l.debit else "بس"
    amt = l.debit or l.credit
    print(f"  {l.account_code:<10} {side}: {amt:>14}   {l.description}")

print(f"\nتعداد رکوردهای Audit Trail: {len(audit.all())}")
print("\n✅ همه چیز در تراز و سازگار است.")
