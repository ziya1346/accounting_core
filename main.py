"""
برنامه حسابداری هوشمند — نسخه منوی تعاملی (بدون نیاز به دانش برنامه‌نویسی)
اجرا: python main.py
تبدیل به exe: pyinstaller --onefile --name HesabdariHoshmand main.py
"""
import os
import sys
from decimal import Decimal, InvalidOperation
from datetime import date

# اجازه بده وقتی به exe تبدیل شد هم مسیرهای داخلی درست پیدا شوند
BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0] if not getattr(sys, "frozen", False) else sys.executable))
sys.path.insert(0, BASE_DIR)

from domain.entities import Account, AccountType, JournalEntry, JournalLine, DomainError
from application.services import ChartOfAccountsService, JournalService, TrialBalanceService, ClosingService
from infrastructure.repositories import SchemaBuilder, SqliteAccountRepository, SqliteJournalRepository, SqliteAuditLog

# پایگاه داده کنار خودِ فایل اجرایی ساخته می‌شود (چه exe باشد چه اسکریپت پایتون)
DB_PATH = os.path.join(BASE_DIR, "hesabdari.db")


def bootstrap():
    is_new = not os.path.exists(DB_PATH)
    SchemaBuilder.create_all(DB_PATH)
    account_repo = SqliteAccountRepository(DB_PATH)
    journal_repo = SqliteJournalRepository(DB_PATH)
    audit_log = SqliteAuditLog(DB_PATH)
    coa_service = ChartOfAccountsService(account_repo)
    journal_service = JournalService(journal_repo, account_repo, audit_log)
    closing_service = ClosingService(journal_repo, account_repo, journal_service)

    if is_new:
        seed_default_chart_of_accounts(coa_service)
        print("✅ پایگاه داده جدید ساخته شد و کدینگ حساب‌های پیش‌فرض بارگذاری شد.\n")

    return account_repo, journal_repo, audit_log, coa_service, journal_service, closing_service


def seed_default_chart_of_accounts(coa_service: ChartOfAccountsService):
    defaults = [
        Account("1", "دارایی‌ها", AccountType.ASSET, is_postable=False),
        Account("1-101", "موجودی نقد و بانک", AccountType.ASSET, parent_code="1", is_postable=False),
        Account("1-101-01", "صندوق", AccountType.ASSET, parent_code="1-101"),
        Account("1-101-02", "بانک", AccountType.ASSET, parent_code="1-101"),
        Account("1-103", "حساب‌های دریافتنی (بدهکاران)", AccountType.ASSET, parent_code="1"),
        Account("2-201", "حساب‌های پرداختنی (بستانکاران)", AccountType.LIABILITY),
        Account("3-301", "سود (زیان) انباشته", AccountType.EQUITY),
        Account("4-401", "فروش کالا", AccountType.REVENUE),
        Account("5-501", "بهای تمام‌شده کالای فروش‌رفته", AccountType.EXPENSE),
        Account("5-502", "هزینه‌های عمومی و اداری", AccountType.EXPENSE),
    ]
    for a in defaults:
        try:
            coa_service.add_account(a)
        except DomainError:
            pass


def pause():
    input("\nبرای بازگشت به منو، Enter را بزنید...")


def read_decimal(prompt: str) -> Decimal:
    while True:
        raw = input(prompt).strip().replace(",", "")
        if raw == "":
            return Decimal("0")
        try:
            return Decimal(raw)
        except InvalidOperation:
            print("❌ عدد نامعتبر است. دوباره وارد کنید.")


def read_jalali_like_date(prompt: str) -> date:
    """تاریخ را به‌صورت YYYY-MM-DD می‌گیرد (می‌توانید سال شمسی مثل 1404-04-14 هم وارد کنید)"""
    raw = input(prompt).strip()
    if not raw:
        return date.today()
    y, m, d = raw.split("-")
    return date(int(y), int(m), int(d))


def menu_show_accounts(account_repo):
    print("\n=== کدینگ حساب‌ها ===")
    print(f"{'کد':<14}{'نام':<32}{'نوع':<12}{'قابل ثبت'}")
    for a in sorted(account_repo.all(), key=lambda x: x.code):
        print(f"{a.code:<14}{a.name:<32}{a.account_type.value:<12}{'بله' if a.is_postable else 'خیر'}")
    pause()


def menu_add_account(coa_service):
    print("\n=== افزودن حساب جدید ===")
    code = input("کد حساب (مثال 1-101-03): ").strip()
    name = input("نام حساب: ").strip()
    print("نوع حساب: 1) دارایی  2) بدهی  3) حقوق صاحبان سهام  4) درآمد  5) هزینه")
    type_map = {"1": AccountType.ASSET, "2": AccountType.LIABILITY, "3": AccountType.EQUITY,
                "4": AccountType.REVENUE, "5": AccountType.EXPENSE}
    t = type_map.get(input("انتخاب (1-5): ").strip())
    parent = input("کد حساب والد (اختیاری، Enter برای هیچ): ").strip() or None
    try:
        coa_service.add_account(Account(code, name, t, parent_code=parent))
        print("✅ حساب با موفقیت اضافه شد.")
    except DomainError as e:
        print(f"❌ خطا: {e}")
    pause()


def menu_post_entry(journal_service, fiscal_year):
    print("\n=== ثبت سند حسابداری جدید ===")
    entry_date = read_jalali_like_date("تاریخ سند (YYYY-MM-DD، Enter=امروز): ")
    description = input("شرح سند: ").strip()
    lines = []
    print("ردیف‌های سند را وارد کنید (برای پایان، کد حساب را خالی بگذارید):")
    while True:
        code = input("  کد حساب: ").strip()
        if not code:
            break
        side = input("  بدهکار یا بستانکار؟ (بد/بس): ").strip()
        amount = read_decimal("  مبلغ: ")
        desc = input("  شرح ردیف: ").strip()
        if side == "بد":
            lines.append(JournalLine(code, debit=amount, description=desc))
        else:
            lines.append(JournalLine(code, credit=amount, description=desc))

    try:
        entry = JournalEntry(entry_date=entry_date, lines=lines, description=description, fiscal_year=fiscal_year)
        posted = journal_service.create_and_post(entry, user="کاربر-ویندوز")
        print(f"✅ سند شماره {posted.number} با موفقیت ثبت شد. (بدهکار={posted.total_debit} بستانکار={posted.total_credit})")
    except DomainError as e:
        print(f"❌ سند ثبت نشد: {e}")
    pause()


def menu_trial_balance(journal_repo, account_repo, fiscal_year):
    tb = TrialBalanceService(journal_repo, account_repo).compute(fiscal_year)
    print(f"\n=== تراز آزمایشی سال مالی {fiscal_year} ===")
    print(f"{'کد':<14}{'نام':<30}{'بدهکار':>16}{'بستانکار':>16}")
    for code, bal in sorted(tb["accounts"].items()):
        acc = account_repo.get_by_code(code)
        print(f"{code:<14}{acc.name:<30}{bal['debit']:>16}{bal['credit']:>16}")
    print("-" * 76)
    print(f"{'جمع کل':<44}{tb['total_debit']:>16}{tb['total_credit']:>16}")
    print("تراز است؟", "✅ بله" if tb["is_balanced"] else "❌ خیر — مشکل داده وجود دارد")
    pause()


def menu_close_year(closing_service, fiscal_year):
    d = read_jalali_like_date("تاریخ سند اختتامیه (YYYY-MM-DD): ")
    try:
        entry = closing_service.close_temporary_accounts(fiscal_year, d, user="کاربر-ویندوز")
        print(f"✅ سند اختتامیه شماره {entry.number} ثبت شد.")
        for l in entry.lines:
            side, amt = ("بد", l.debit) if l.debit else ("بس", l.credit)
            print(f"  {l.account_code:<12} {side}: {amt:>14}  {l.description}")
    except DomainError as e:
        print(f"❌ خطا: {e}")
    pause()


def menu_audit_log(audit_log):
    print("\n=== گزارش رهگیری عملیات (Audit Trail) ===")
    for rec in audit_log.all():
        print(f"[{rec['ts']}] {rec['user']} -> {rec['action']}: {rec['details']}")
    pause()


def main():
    print("=" * 60)
    print("      نرم‌افزار حسابداری هوشمند — نسخه دسکتاپ (فاز ۱)")
    print("=" * 60)
    account_repo, journal_repo, audit_log, coa_service, journal_service, closing_service = bootstrap()
    fiscal_year = input("سال مالی جاری را وارد کنید (مثال 1404): ").strip() or "1404"

    while True:
        print("\n----------------- منوی اصلی -----------------")
        print("1) نمایش کدینگ حساب‌ها")
        print("2) افزودن حساب جدید")
        print("3) ثبت سند حسابداری")
        print("4) نمایش تراز آزمایشی")
        print("5) صدور سند اختتامیه سال مالی")
        print("6) گزارش رهگیری عملیات (Audit Trail)")
        print("0) خروج")
        choice = input("انتخاب شما: ").strip()

        if choice == "1":
            menu_show_accounts(account_repo)
        elif choice == "2":
            menu_add_account(coa_service)
        elif choice == "3":
            menu_post_entry(journal_service, fiscal_year)
        elif choice == "4":
            menu_trial_balance(journal_repo, account_repo, fiscal_year)
        elif choice == "5":
            menu_close_year(closing_service, fiscal_year)
        elif choice == "6":
            menu_audit_log(audit_log)
        elif choice == "0":
            print("خدانگهدار 👋")
            break
        else:
            print("❌ گزینه نامعتبر است.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nخروج توسط کاربر.")
    except Exception as e:
        print(f"\n❌ خطای غیرمنتظره: {e}")
        input("Enter را بزنید تا خارج شوید...")
