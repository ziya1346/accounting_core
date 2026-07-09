"""
Domain Layer — لایه دامنه
هیچ وابستگی به فریم‌ورک، دیتابیس یا رابط کاربری ندارد (طبق Clean Architecture / DDD).
قوانین کسب‌وکار حسابداری اینجا نگهداری می‌شوند: سیستم دوبل، اصل تعهدی، کدینگ شناور.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from datetime import date
from typing import Optional
import uuid


class AccountNature(str, Enum):
    """ماهیت حساب: بدهکار یا بستانکار"""
    DEBIT = "DEBIT"      # دارایی، هزینه
    CREDIT = "CREDIT"    # بدهی، حقوق صاحبان سهام، درآمد


class AccountType(str, Enum):
    ASSET = "ASSET"                 # دارایی
    LIABILITY = "LIABILITY"         # بدهی
    EQUITY = "EQUITY"               # حقوق صاحبان سهام
    REVENUE = "REVENUE"             # درآمد
    EXPENSE = "EXPENSE"             # هزینه


class DomainError(Exception):
    """خطای نقض قانون کسب‌وکار (نه خطای فنی)"""
    pass


def two_decimals(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class Account:
    """
    حساب در دفتر کل — از کدینگ شناور پشتیبانی می‌کند:
    مثال: 1-101-01-001  (گروه-کل-معین-تفصیلی)
    """
    code: str
    name: str
    account_type: AccountType
    parent_code: Optional[str] = None
    is_postable: bool = True   # آیا سند مستقیم روی این حساب زده می‌شود یا فقط والد یک زیرمجموعه است
    currency: str = "IRR"
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def nature(self) -> AccountNature:
        if self.account_type in (AccountType.ASSET, AccountType.EXPENSE):
            return AccountNature.DEBIT
        return AccountNature.CREDIT

    @property
    def level(self) -> int:
        """سطح در کدینگ شناور بر اساس تعداد بخش‌های کد"""
        return len(self.code.split("-"))

    def validate(self):
        if not self.code or not self.code.strip():
            raise DomainError("کد حساب نمی‌تواند خالی باشد")
        if not self.name or not self.name.strip():
            raise DomainError("نام حساب نمی‌تواند خالی باشد")


@dataclass
class JournalLine:
    """یک ردیف (آرتیکل) از سند حسابداری"""
    account_code: str
    debit: Decimal = Decimal("0.00")
    credit: Decimal = Decimal("0.00")
    description: str = ""
    cost_center: Optional[str] = None   # مرکز هزینه
    project_code: Optional[str] = None  # پروژه

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
    DRAFT = "DRAFT"           # پیش‌نویس
    POSTED = "POSTED"         # ثبت‌شده در دفاتر
    REVERSED = "REVERSED"     # برگشت‌خورده


class JournalEntryType(str, Enum):
    NORMAL = "NORMAL"           # سند عادی
    OPENING = "OPENING"         # سند افتتاحیه
    CLOSING = "CLOSING"         # سند اختتامیه
    ADJUSTMENT = "ADJUSTMENT"   # سند تعدیلات


@dataclass
class JournalEntry:
    """
    سند حسابداری — قلب سیستم دوبل.
    قانون طلایی: مجموع بدهکار = مجموع بستانکار (در تراز باشد)
    """
    entry_date: date
    lines: list[JournalLine] = field(default_factory=list)
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
    def is_balanced(self) -> bool:
        return self.total_debit == self.total_credit

    def validate(self):
        """اصل تعهدی و سیستم دوبل: بدون تراز بودن، سند نامعتبر است"""
        if len(self.lines) < 2:
            raise DomainError("سند حسابداری باید حداقل دو ردیف داشته باشد (اصل دوبل)")
        if self.total_debit == 0:
            raise DomainError("مجموع سند نمی‌تواند صفر باشد")
        if not self.is_balanced:
            raise DomainError(
                f"سند در تراز نیست: بدهکار={self.total_debit} بستانکار={self.total_credit}"
            )

    def post(self):
        """ثبت قطعی سند در دفاتر — فقط پس از اعتبارسنجی کامل"""
        self.validate()
        if self.status != JournalEntryStatus.DRAFT:
            raise DomainError("فقط سند پیش‌نویس قابل ثبت است")
        self.status = JournalEntryStatus.POSTED

    def reverse(self) -> "JournalEntry":
        """سند برگشتی (Reversal) — برای اصلاح بدون حذف سند اصلی، طبق استاندارد حسابرسی"""
        if self.status != JournalEntryStatus.POSTED:
            raise DomainError("فقط سند ثبت‌شده قابل برگشت است")
        reversed_lines = [
            JournalLine(
                account_code=l.account_code,
                debit=l.credit,
                credit=l.debit,
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
            entry_type=self.entry_type,
            description=f"سند برگشتی سند شماره {self.number}",
            fiscal_year=self.fiscal_year,
            branch_code=self.branch_code,
            company_code=self.company_code,
        )
