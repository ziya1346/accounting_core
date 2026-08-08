"""from domain.value_objects.currency import Currency
from application.currency_conversion_service import CurrencyConversionService
Application Layer — لایه کاربرد
شامل Use Caseها و سرویس‌های اصلی سیستم حسابداری
"""
from __future__ import annotations
from decimal import Decimal
from datetime import date
from typing import List, Optional, Dict, Any

from domain.entities import (
    Account, AccountType, JournalEntry, JournalLine,
    DomainError, JournalEntryStatus, JournalEntryType
)


class ChartOfAccountsService:
    def __init__(self, account_repo):
        self.account_repo = account_repo

    def add_account(self, account: Account) -> Account:
        account.validate()

        existing = self.account_repo.get_by_code(account.code)
        if existing:
            raise DomainError(f"کد حساب تکراری است: {account.code}")

        if account.parent_code:
            parent = self.account_repo.get_by_code(account.parent_code)
            if not parent:
                raise DomainError(f"حساب والد یافت نشد: {account.parent_code}")

        self.account_repo.add(account)   # <-- متد صحیح در Repository
        return account

    def get_children(self, parent_code: str) -> List[Account]:
        all_accounts = self.account_repo.all()
        return [acc for acc in all_accounts if acc.parent_code == parent_code]

    def get_account(self, code: str) -> Optional[Account]:
        return self.account_repo.get_by_code(code)


class JournalService:
    def __init__(self, journal_repo, account_repo, audit_log):
        self.journal_repo = journal_repo
        self.account_repo = account_repo
        self.audit_log = audit_log

    def prepare_entry_for_posting(
        self,
        entry: JournalEntry,
        conversion_service: CurrencyConversionService
    ) -> JournalEntry:
        """
        آماده‌سازی سند برای ثبت:
        - تبدیل مبالغ ردیف‌هایی که ارز متفاوتی دارند به ارز پایه
        - پر کردن فیلدهای exchange_rate و amount_in_base
        """
        for line in entry.lines:
            if line.currency == entry.base_currency:
                # ارز ردیف با ارز پایه یکسان است
                line.amount_in_base = line.debit if line.debit > 0 else line.credit
                line.exchange_rate = Decimal("1")
            else:
                # نیاز به تبدیل ارز
                original_amount = line.debit if line.debit > 0 else line.credit

                rate = conversion_service.get_rate(
                    source=line.currency,
                    target=entry.base_currency,
                    on_date=entry.entry_date
                )

                converted_amount = rate.convert(original_amount)

                line.exchange_rate = rate.rate
                line.amount_in_base = converted_amount

        return entry

    def create_and_post(
        self,
        entry: JournalEntry,
        user: str,
        conversion_service: CurrencyConversionService = None
    ) -> JournalEntry:
        # اگر سرویس تبدیل ارز داده شده باشد، سند را آماده کن
        if conversion_service is not None:
            entry = self.prepare_entry_for_posting(entry, conversion_service)

        # اعتبارسنجی حساب‌ها
        for line in entry.lines:
            account = self.account_repo.get_by_code(line.account_code)
            if not account:
                raise DomainError(f"حساب یافت نشد: {line.account_code}")
            if not account.is_postable:
                raise DomainError(f"امکان ثبت سند روی حساب والد وجود ندارد: {line.account_code}")

        entry.validate()   # اعتبارسنجی بر اساس amount_in_base انجام می‌شود
        entry.post()

        entry.number = self.journal_repo.next_number(entry.fiscal_year)
        self.journal_repo.save(entry)

        self.audit_log.record(
            user=user,
            action="POST_JOURNAL_ENTRY",
            entity_id=entry.id,
            details=f"number={entry.number}, fiscal_year={entry.fiscal_year}, base_currency={entry.base_currency.value}"
        )

        return entry

    def reverse_entry(self, entry_id: str, user: str) -> JournalEntry:
        original = self.journal_repo.get(entry_id)
        if not original:
            raise DomainError("سند یافت نشد")

        reversal = original.reverse()
        reversal.number = self.journal_repo.next_number(original.fiscal_year)
        reversal.post()

        self.journal_repo.save(original)
        self.journal_repo.save(reversal)

        self.audit_log.record(
            user=user,
            action="REVERSE_JOURNAL_ENTRY",
            entity_id=reversal.id,
            details=f"original_id={original.id}"
        )

        return reversal

class TrialBalanceService:
    def __init__(self, journal_repo, account_repo):
        self.journal_repo = journal_repo
        self.account_repo = account_repo

    def compute(self, fiscal_year: str) -> Dict[str, Any]:
        entries = self.journal_repo.all_posted(fiscal_year)

        totals: Dict[str, Dict[str, Decimal]] = {}

        for entry in entries:
            for line in entry.lines:
                if line.account_code not in totals:
                    totals[line.account_code] = {
                        "debit": Decimal("0.00"),
                        "credit": Decimal("0.00")
                    }
                totals[line.account_code]["debit"] += line.debit
                totals[line.account_code]["credit"] += line.credit

        total_debit = sum(v["debit"] for v in totals.values())
        total_credit = sum(v["credit"] for v in totals.values())

        return {
            "accounts": totals,
            "total_debit": total_debit,
            "total_credit": total_credit,
            "is_balanced": total_debit == total_credit,
        }


class ClosingService:
    def __init__(self, journal_repo, account_repo, journal_service: JournalService):
        self.journal_repo = journal_repo
        self.account_repo = account_repo
        self.journal_service = journal_service

    def close_temporary_accounts(self, fiscal_year: str, closing_date: date, user: str) -> JournalEntry:
        tb = TrialBalanceService(self.journal_repo, self.account_repo).compute(fiscal_year)

        lines = []
        net_profit = Decimal("0.00")

        for code, amounts in tb["accounts"].items():
            account = self.account_repo.get_by_code(code)
            if not account:
                continue

            if account.account_type == AccountType.REVENUE:
                balance = amounts["credit"] - amounts["debit"]
                if balance != 0:
                    lines.append(JournalLine(code, debit=balance, description="بستن حساب درآمد"))
                    net_profit += balance

            elif account.account_type == AccountType.EXPENSE:
                balance = amounts["debit"] - amounts["credit"]
                if balance != 0:
                    lines.append(JournalLine(code, credit=balance, description="بستن حساب هزینه"))
                    net_profit -= balance

        if net_profit > 0:
            lines.append(JournalLine("3-301", credit=net_profit, description="سود خالص سال"))
        elif net_profit < 0:
            lines.append(JournalLine("3-301", debit=abs(net_profit), description="زیان خالص سال"))

        closing_entry = JournalEntry(
            entry_date=closing_date,
            lines=lines,
            entry_type=JournalEntryType.CLOSING,
            description=f"سند اختتامیه سال مالی {fiscal_year}",
            fiscal_year=fiscal_year,
        )

        return self.journal_service.create_and_post(closing_entry, user=user)