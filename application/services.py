"""
Application Layer — لایه اپلیکیشن (Use Cases)
هماهنگ‌کننده بین دامنه و زیرساخت. منطق کسب‌وکار خالص همچنان در Domain است؛
اینجا فقط جریان کار (workflow) پیاده می‌شود.
"""
from __future__ import annotations
from decimal import Decimal
from typing import Iterable
from domain.entities import (
    Account, AccountType, JournalEntry, JournalEntryStatus, DomainError
)


class ChartOfAccountsService:
    """مدیریت کدینگ شناور درخت حساب‌ها"""

    def __init__(self, repo):
        self.repo = repo

    def add_account(self, account: Account) -> Account:
        account.validate()
        if self.repo.get_by_code(account.code):
            raise DomainError(f"کد حساب {account.code} تکراری است")
        if account.parent_code and not self.repo.get_by_code(account.parent_code):
            raise DomainError(f"حساب والد {account.parent_code} یافت نشد")
        self.repo.add(account)
        return account

    def get_children(self, parent_code: str) -> list[Account]:
        return [a for a in self.repo.all() if a.parent_code == parent_code]


class JournalService:
    """ثبت اسناد حسابداری با رعایت کامل اصل دوبل و رهگیری (Audit Trail)"""

    def __init__(self, journal_repo, account_repo, audit_log):
        self.journal_repo = journal_repo
        self.account_repo = account_repo
        self.audit_log = audit_log

    def _validate_accounts_exist_and_postable(self, entry: JournalEntry):
        for line in entry.lines:
            acc = self.account_repo.get_by_code(line.account_code)
            if acc is None:
                raise DomainError(f"حساب {line.account_code} در کدینگ یافت نشد")
            if not acc.is_postable:
                raise DomainError(f"حساب {line.account_code} فقط والد است و قابل ثبت سند مستقیم نیست")

    def create_and_post(self, entry: JournalEntry, user: str) -> JournalEntry:
        self._validate_accounts_exist_and_postable(entry)
        entry.validate()
        entry.number = self.journal_repo.next_number(entry.fiscal_year)
        entry.post()
        self.journal_repo.save(entry)
        self.audit_log.record(
            user=user,
            action="POST_JOURNAL_ENTRY",
            entity_id=entry.id,
            details=f"سند شماره {entry.number} به مبلغ {entry.total_debit} ثبت شد",
        )
        return entry

    def reverse_entry(self, entry_id: str, user: str) -> JournalEntry:
        original = self.journal_repo.get(entry_id)
        if original is None:
            raise DomainError("سند یافت نشد")
        reversal = original.reverse()
        reversal.number = self.journal_repo.next_number(original.fiscal_year)
        reversal.post()
        self.journal_repo.save(original)   # update status = REVERSED
        self.journal_repo.save(reversal)
        self.audit_log.record(
            user=user,
            action="REVERSE_JOURNAL_ENTRY",
            entity_id=original.id,
            details=f"سند {original.number} برگشت خورد با سند جدید {reversal.number}",
        )
        return reversal


class TrialBalanceService:
    """
    تراز آزمایشی (چهار ستونی / هشت ستونی) — قانون طلایی حسابداری:
    مجموع بدهکار کل حساب‌ها همیشه باید برابر مجموع بستانکار باشد.
    """

    def __init__(self, journal_repo, account_repo):
        self.journal_repo = journal_repo
        self.account_repo = account_repo

    def compute(self, fiscal_year: str) -> dict:
        balances: dict[str, dict] = {}
        for entry in self.journal_repo.all_posted(fiscal_year):
            for line in entry.lines:
                b = balances.setdefault(line.account_code, {"debit": Decimal("0.00"), "credit": Decimal("0.00")})
                b["debit"] += line.debit
                b["credit"] += line.credit

        total_debit = sum((b["debit"] for b in balances.values()), Decimal("0.00"))
        total_credit = sum((b["credit"] for b in balances.values()), Decimal("0.00"))

        return {
            "accounts": balances,
            "total_debit": total_debit,
            "total_credit": total_credit,
            "is_balanced": total_debit == total_credit,
        }


class ClosingService:
    """بستن حساب‌های موقت (درآمد/هزینه) در پایان سال مالی به سود و زیان انباشته"""

    CLOSING_ACCOUNT_CODE = "3-301"  # سود (زیان) انباشته

    def __init__(self, journal_repo, account_repo, journal_service: JournalService):
        self.journal_repo = journal_repo
        self.account_repo = account_repo
        self.journal_service = journal_service

    def close_temporary_accounts(self, fiscal_year: str, closing_date, user: str) -> JournalEntry:
        from domain.entities import JournalLine, JournalEntryType
        trial = TrialBalanceService(self.journal_repo, self.account_repo).compute(fiscal_year)
        lines = []
        net = Decimal("0.00")
        for code, bal in trial["accounts"].items():
            acc = self.account_repo.get_by_code(code)
            if acc.account_type not in (AccountType.REVENUE, AccountType.EXPENSE):
                continue
            net_balance = bal["credit"] - bal["debit"] if acc.account_type == AccountType.REVENUE \
                else bal["debit"] - bal["credit"]
            if net_balance == 0:
                continue
            if acc.account_type == AccountType.REVENUE:
                lines.append(JournalLine(account_code=code, debit=net_balance, description="بستن حساب درآمد"))
                net += net_balance
            else:
                lines.append(JournalLine(account_code=code, credit=net_balance, description="بستن حساب هزینه"))
                net -= net_balance

        if net > 0:
            lines.append(JournalLine(account_code=self.CLOSING_ACCOUNT_CODE, credit=net, description="سود خالص دوره"))
        elif net < 0:
            lines.append(JournalLine(account_code=self.CLOSING_ACCOUNT_CODE, debit=-net, description="زیان خالص دوره"))

        entry = JournalEntry(
            entry_date=closing_date,
            lines=lines,
            entry_type=JournalEntryType.CLOSING,
            description=f"سند اختتامیه سال مالی {fiscal_year}",
            fiscal_year=fiscal_year,
        )
        return self.journal_service.create_and_post(entry, user)
