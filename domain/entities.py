"""
Domain Layer — لایه دامنه
هیچ وابستگی به فریم‌ورک، دیتابیس یا رابط کاربری ندارد (طبق Clean Architecture / DDD).
قوانین کسب‌وکار حسابداری اینجا نگهداری می‌شوند: سیستم دوبل، اصل تعهدی، کدینگ شناور.
پشتیبانی از Multi-Currency اضافه شده است.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from datetime import date
from typing import Optional
import uuid

from domain.value_objects.currency import Currency


class AccountNature(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class AccountType(str, Enum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"


class DomainError(Exception):
    pass


def two_decimals(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class Account:
    code: str
    name: str
    account_type: AccountType
    parent_code: Optional[str] = None
    is_postable: bool = True
    currency: str = "IRR"
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def nature(self) -> AccountNature:
        if self.account_type in (AccountType.ASSET, AccountType.EXPENSE):
            return AccountNature.DEBIT
        return AccountNature.CREDIT

    @property
    def level(self) -> int:
        return len(self.code.split("-"))

    def validate(self):
        if not self.code or not self.code.strip():
            raise DomainError("کد حساب نمی‌تواند خالی باشد")
        if not self.name or not self.name.strip():
            raise DomainError("نام حساب نمی‌تواند خالی باشد")


@dataclass
class JournalLine:
    account_code: str
    debit: Decimal = Decimal("0.00")
    credit: Decimal = Decimal("0.00")
    currency: Currency = Currency.IRR
    exchange_rate: Optional[Decimal] = None
    amount_in_base: Optional[Decimal] = None
    description: str = ""
    cost_center: Optional[str] = None
    project_code: Optional[str] = None

    def __post_init__(self):
        self.debit = two_decimals(self.debit)
        self.credit = two_decimals(self.credit)
        if self.debit < 0 or self.credit < 0:
            raise DomainError("مبالغ بدهکار/بستانکار نمی‌توانند منفی باشند")
        if self.debit > 0 and self.credit > 0:
            raise DomainError("یک ردیف سند نمی‌تواند همزمان بدهکار و بستانکار باشد")
        if self.debit == 0 and self.credit == 0:
            raise DomainError("یک ردیف سند باید مبلغ بدهکار یا بستانکار داشته باشد")


class JournalEntryStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class JournalEntryType(str, Enum):
    NORMAL = "NORMAL"
    OPENING = "OPENING"
    CLOSING = "CLOSING"
    ADJUSTMENT = "ADJUSTMENT"


@dataclass
class JournalEntry:
    entry_date: date
    lines: list[JournalLine] = field(default_factory=list)
    base_currency: Currency = Currency.IRR
    entry_type: JournalEntryType = JournalEntryType.NORMAL
    description: str = ""
    fiscal_year: Optional[str] = None
    branch_code: Optional[str] = None
    company_code: Optional[str] = None
    status: JournalEntryStatus = JournalEntryStatus.DRAFT
    number: Optional[int] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def total_debit(self) -> Decimal:
        return sum((l.debit for l in self.lines), Decimal("0.00"))

    @property
    def total_credit(self) -> Decimal:
        return sum((l.credit for l in self.lines), Decimal("0.00"))

    @property
    def total_debit_in_base(self) -> Decimal:
        total = Decimal("0.00")
        for line in self.lines:
            if line.debit > 0:
                amount = line.amount_in_base if line.amount_in_base is not None else line.debit
                total += amount
        return two_decimals(total)

    @property
    def total_credit_in_base(self) -> Decimal:
        total = Decimal("0.00")
        for line in self.lines:
            if line.credit > 0:
                amount = line.amount_in_base if line.amount_in_base is not None else line.credit
                total += amount
        return two_decimals(total)

    @property
    def is_balanced(self) -> bool:
        return self.total_debit_in_base == self.total_credit_in_base

    def validate(self):
        if len(self.lines) < 2:
            raise DomainError("سند حسابداری باید حداقل دو ردیف داشته باشد (اصل دوبل)")
        if self.total_debit_in_base == 0:
            raise DomainError("مجموع سند نمی‌تواند صفر باشد")
        if not self.is_balanced:
            raise DomainError(
                f"سند در تراز نیست (ارز پایه: {self.base_currency.value}) | "
                f"بدهکار={self.total_debit_in_base} | بستانکار={self.total_credit_in_base}"
            )

    def post(self):
        self.validate()
        if self.status != JournalEntryStatus.DRAFT:
            raise DomainError("فقط سند پیش‌نویس قابل ثبت است")
        self.status = JournalEntryStatus.POSTED

    def reverse(self) -> "JournalEntry":
        if self.status != JournalEntryStatus.POSTED:
            raise DomainError("فقط سند ثبت‌شده قابل برگشت است")
        reversed_lines = [
            JournalLine(
                account_code=l.account_code,
                debit=l.credit,
                credit=l.debit,
                currency=l.currency,
                exchange_rate=l.exchange_rate,
                amount_in_base=l.amount_in_base,
                description=f"برگشت: {l.description}",
                cost_center=l.cost_center,
                project_code=l.project_code,
            )
            for l in self.lines
        ]
        self.status = JournalEntryStatus.REVERSED
        return JournalEntry(
            entry_date=self.entry_date,
            lines=reversed_lines,
            base_currency=self.base_currency,
            entry_type=self.entry_type,
            description=f"سند برگشتی سند شماره {self.number}",
            fiscal_year=self.fiscal_year,
            branch_code=self.branch_code,
            company_code=self.company_code,
        )