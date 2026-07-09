"""
نرم‌افزار حسابداری هوشمند — رابط گرافیکی دسکتاپ (Tkinter)
اجرا: python gui.py
تبدیل به exe: pyinstaller --onefile --noconsole --name HesabdariHoshmand gui.py
"""
import os
import sys
from decimal import Decimal, InvalidOperation
from datetime import date

import tkinter as tk
from tkinter import ttk, messagebox

BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0] if not getattr(sys, "frozen", False) else sys.executable))
sys.path.insert(0, BASE_DIR)

from domain.entities import Account, AccountType, JournalEntry, JournalLine, DomainError
from application.services import ChartOfAccountsService, JournalService, TrialBalanceService, ClosingService
from infrastructure.repositories import (
    SchemaBuilder, SqliteAccountRepository, SqliteJournalRepository, SqliteAuditLog
)

DB_PATH = os.path.join(BASE_DIR, "hesabdari.db")

ACCOUNT_TYPE_LABELS = {
    AccountType.ASSET: "دارایی",
    AccountType.LIABILITY: "بدهی",
    AccountType.EQUITY: "حقوق صاحبان سهام",
    AccountType.REVENUE: "درآمد",
    AccountType.EXPENSE: "هزینه",
}
LABEL_TO_TYPE = {v: k for k, v in ACCOUNT_TYPE_LABELS.items()}

FONT_NORMAL = ("Tahoma", 10)
FONT_BOLD = ("Tahoma", 11, "bold")
FONT_HEADER = ("Tahoma", 15, "bold")
COLOR_BG = "#f4f6f8"
COLOR_PRIMARY = "#1f5c8b"
COLOR_SUCCESS = "#1e8449"
COLOR_DANGER = "#c0392b"


class AccountingApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("نرم‌افزار حسابداری هوشمند — فاز ۱")
        self.geometry("1050x680")
        self.configure(bg=COLOR_BG)
        self.minsize(900, 600)

        is_new = not os.path.exists(DB_PATH)
        SchemaBuilder.create_all(DB_PATH)
        self.account_repo = SqliteAccountRepository(DB_PATH)
        self.journal_repo = SqliteJournalRepository(DB_PATH)
        self.audit_log = SqliteAuditLog(DB_PATH)
        self.coa_service = ChartOfAccountsService(self.account_repo)
        self.journal_service = JournalService(self.journal_repo, self.account_repo, self.audit_log)
        self.closing_service = ClosingService(self.journal_repo, self.account_repo, self.journal_service)
        self.fiscal_year = tk.StringVar(value="1404")

        if is_new:
            self._seed_default_accounts()

        self.pending_lines: list[JournalLine] = []
        self._build_style()
        self._build_header()
        self._build_tabs()
        self._refresh_accounts_table()
        self._refresh_trial_balance()
        self._refresh_audit_table()

    # ---------- سرمایه‌گذاری اولیه ----------
    def _seed_default_accounts(self):
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
                self.coa_service.add_account(a)
            except DomainError:
                pass

    # ---------- ظاهر کلی ----------
    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", font=FONT_NORMAL, rowheight=26, background="white")
        style.configure("Treeview.Heading", font=FONT_BOLD, background=COLOR_PRIMARY, foreground="white")
        style.configure("TNotebook.Tab", font=FONT_BOLD, padding=(16, 8))
        style.configure("Primary.TButton", font=FONT_BOLD)
        style.configure("TLabel", font=FONT_NORMAL, background=COLOR_BG)

    def _build_header(self):
        header = tk.Frame(self, bg=COLOR_PRIMARY, height=64)
        header.pack(fill="x", side="top")
        tk.Label(header, text="نرم‌افزار حسابداری هوشمند", font=FONT_HEADER,
                 bg=COLOR_PRIMARY, fg="white").pack(side="right", padx=20, pady=12)

        fy_frame = tk.Frame(header, bg=COLOR_PRIMARY)
        fy_frame.pack(side="left", padx=20)
        tk.Label(fy_frame, text="سال مالی:", bg=COLOR_PRIMARY, fg="white", font=FONT_NORMAL).pack(side="right")
        fy_entry = ttk.Entry(fy_frame, textvariable=self.fiscal_year, width=8, justify="center")
        fy_entry.pack(side="right", padx=6)
        fy_entry.bind("<Return>", lambda e: self._refresh_trial_balance())

    def _build_tabs(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_accounts = tk.Frame(self.notebook, bg=COLOR_BG)
        self.tab_journal = tk.Frame(self.notebook, bg=COLOR_BG)
        self.tab_trial = tk.Frame(self.notebook, bg=COLOR_BG)
        self.tab_audit = tk.Frame(self.notebook, bg=COLOR_BG)

        self.notebook.add(self.tab_accounts, text="کدینگ حساب‌ها")
        self.notebook.add(self.tab_journal, text="ثبت سند حسابداری")
        self.notebook.add(self.tab_trial, text="تراز آزمایشی")
        self.notebook.add(self.tab_audit, text="رهگیری عملیات")

        self._build_accounts_tab()
        self._build_journal_tab()
        self._build_trial_tab()
        self._build_audit_tab()

    # ---------- تب ۱: کدینگ حساب‌ها ----------
    def _build_accounts_tab(self):
        form = tk.LabelFrame(self.tab_accounts, text="افزودن حساب جدید", font=FONT_BOLD,
                              bg=COLOR_BG, padx=10, pady=10)
        form.pack(fill="x", padx=10, pady=10)

        tk.Label(form, text="کد حساب:", bg=COLOR_BG).grid(row=0, column=5, padx=5, pady=5, sticky="e")
        self.acc_code_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.acc_code_var, width=16).grid(row=0, column=4, padx=5)

        tk.Label(form, text="نام حساب:", bg=COLOR_BG).grid(row=0, column=3, padx=5, sticky="e")
        self.acc_name_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.acc_name_var, width=28).grid(row=0, column=2, padx=5)

        tk.Label(form, text="نوع حساب:", bg=COLOR_BG).grid(row=0, column=1, padx=5, sticky="e")
        self.acc_type_var = tk.StringVar(value=ACCOUNT_TYPE_LABELS[AccountType.ASSET])
        ttk.Combobox(form, textvariable=self.acc_type_var, values=list(ACCOUNT_TYPE_LABELS.values()),
                     state="readonly", width=16).grid(row=0, column=0, padx=5)

        tk.Label(form, text="کد والد (اختیاری):", bg=COLOR_BG).grid(row=1, column=5, padx=5, pady=5, sticky="e")
        self.acc_parent_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.acc_parent_var, width=16).grid(row=1, column=4, padx=5)

        ttk.Button(form, text="➕ افزودن حساب", style="Primary.TButton",
                   command=self._on_add_account).grid(row=1, column=2, padx=5, pady=5, sticky="w")

        columns = ("code", "name", "type", "postable")
        self.accounts_tree = ttk.Treeview(self.tab_accounts, columns=columns, show="headings", height=18)
        self.accounts_tree.heading("code", text="کد حساب")
        self.accounts_tree.heading("name", text="نام حساب")
        self.accounts_tree.heading("type", text="نوع")
        self.accounts_tree.heading("postable", text="قابل ثبت سند")
        self.accounts_tree.column("code", width=120, anchor="center")
        self.accounts_tree.column("name", width=320, anchor="e")
        self.accounts_tree.column("type", width=150, anchor="center")
        self.accounts_tree.column("postable", width=100, anchor="center")
        self.accounts_tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _on_add_account(self):
        code = self.acc_code_var.get().strip()
        name = self.acc_name_var.get().strip()
        acc_type = LABEL_TO_TYPE.get(self.acc_type_var.get())
        parent = self.acc_parent_var.get().strip() or None
        try:
            self.coa_service.add_account(Account(code, name, acc_type, parent_code=parent))
            messagebox.showinfo("موفق", f"حساب «{name}» با کد {code} اضافه شد.")
            self.acc_code_var.set(""); self.acc_name_var.set(""); self.acc_parent_var.set("")
            self._refresh_accounts_table()
        except DomainError as e:
            messagebox.showerror("خطا", str(e))

    def _refresh_accounts_table(self):
        for row in self.accounts_tree.get_children():
            self.accounts_tree.delete(row)
        for acc in sorted(self.account_repo.all(), key=lambda a: a.code):
            self.accounts_tree.insert("", "end", values=(
                acc.code, acc.name, ACCOUNT_TYPE_LABELS[acc.account_type],
                "بله" if acc.is_postable else "خیر"
            ))

    # ---------- تب ۲: ثبت سند ----------
    def _build_journal_tab(self):
        top = tk.LabelFrame(self.tab_journal, text="اطلاعات سند", font=FONT_BOLD, bg=COLOR_BG, padx=10, pady=10)
        top.pack(fill="x", padx=10, pady=10)

        tk.Label(top, text="تاریخ (YYYY-MM-DD):", bg=COLOR_BG).grid(row=0, column=3, padx=5, sticky="e")
        self.je_date_var = tk.StringVar(value=str(date.today()))
        ttk.Entry(top, textvariable=self.je_date_var, width=14).grid(row=0, column=2, padx=5)

        tk.Label(top, text="شرح سند:", bg=COLOR_BG).grid(row=0, column=1, padx=5, sticky="e")
        self.je_desc_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.je_desc_var, width=40).grid(row=0, column=0, padx=5)

        line_form = tk.LabelFrame(self.tab_journal, text="افزودن ردیف سند", font=FONT_BOLD,
                                   bg=COLOR_BG, padx=10, pady=10)
        line_form.pack(fill="x", padx=10)

        tk.Label(line_form, text="کد حساب:", bg=COLOR_BG).grid(row=0, column=4, padx=5, sticky="e")
        self.line_code_var = tk.StringVar()
        ttk.Entry(line_form, textvariable=self.line_code_var, width=14).grid(row=0, column=3, padx=5)

        tk.Label(line_form, text="بدهکار:", bg=COLOR_BG).grid(row=0, column=2, padx=5, sticky="e")
        self.line_debit_var = tk.StringVar()
        ttk.Entry(line_form, textvariable=self.line_debit_var, width=14).grid(row=0, column=1, padx=5)

        tk.Label(line_form, text="بستانکار:", bg=COLOR_BG).grid(row=1, column=2, padx=5, sticky="e")
        self.line_credit_var = tk.StringVar()
        ttk.Entry(line_form, textvariable=self.line_credit_var, width=14).grid(row=1, column=1, padx=5)

        tk.Label(line_form, text="شرح ردیف:", bg=COLOR_BG).grid(row=1, column=4, padx=5, sticky="e")
        self.line_desc_var = tk.StringVar()
        ttk.Entry(line_form, textvariable=self.line_desc_var, width=30).grid(row=1, column=3, padx=5)

        ttk.Button(line_form, text="➕ افزودن ردیف", command=self._on_add_line).grid(row=0, column=0, rowspan=2, padx=10)

        columns = ("code", "debit", "credit", "desc")
        self.lines_tree = ttk.Treeview(self.tab_journal, columns=columns, show="headings", height=8)
        self.lines_tree.heading("code", text="کد حساب")
        self.lines_tree.heading("debit", text="بدهکار")
        self.lines_tree.heading("credit", text="بستانکار")
        self.lines_tree.heading("desc", text="شرح")
        for c, w in zip(columns, (100, 130, 130, 300)):
            self.lines_tree.column(c, width=w, anchor="center" if c != "desc" else "e")
        self.lines_tree.pack(fill="x", padx=10, pady=10)

        btns = tk.Frame(self.tab_journal, bg=COLOR_BG)
        btns.pack(fill="x", padx=10)
        ttk.Button(btns, text="🗑 حذف ردیف انتخاب‌شده", command=self._on_remove_line).pack(side="right", padx=5)
        ttk.Button(btns, text="✅ ثبت سند", style="Primary.TButton",
                   command=self._on_post_entry).pack(side="right", padx=5)
        ttk.Button(btns, text="↺ پاک کردن فرم", command=self._reset_journal_form).pack(side="right", padx=5)

        self.je_totals_label = tk.Label(self.tab_journal, text="جمع بدهکار: 0.00   |   جمع بستانکار: 0.00",
                                         font=FONT_BOLD, bg=COLOR_BG, fg=COLOR_PRIMARY)
        self.je_totals_label.pack(pady=6)

    def _on_add_line(self):
        code = self.line_code_var.get().strip()
        debit_raw = self.line_debit_var.get().strip().replace(",", "")
        credit_raw = self.line_credit_var.get().strip().replace(",", "")
        desc = self.line_desc_var.get().strip()
        if not code:
            messagebox.showerror("خطا", "کد حساب را وارد کنید."); return
        try:
            debit = Decimal(debit_raw) if debit_raw else Decimal("0")
            credit = Decimal(credit_raw) if credit_raw else Decimal("0")
        except InvalidOperation:
            messagebox.showerror("خطا", "مبلغ باید عدد باشد."); return
        try:
            line = JournalLine(code, debit=debit, credit=credit, description=desc)
        except DomainError as e:
            messagebox.showerror("خطا", str(e)); return

        self.pending_lines.append(line)
        self.lines_tree.insert("", "end", values=(code, f"{line.debit}", f"{line.credit}", desc))
        self.line_code_var.set(""); self.line_debit_var.set(""); self.line_credit_var.set(""); self.line_desc_var.set("")
        self._update_totals_label()

    def _on_remove_line(self):
        selected = self.lines_tree.selection()
        if not selected:
            return
        idx = self.lines_tree.index(selected[0])
        del self.pending_lines[idx]
        self.lines_tree.delete(selected[0])
        self._update_totals_label()

    def _update_totals_label(self):
        total_debit = sum((l.debit for l in self.pending_lines), Decimal("0.00"))
        total_credit = sum((l.credit for l in self.pending_lines), Decimal("0.00"))
        self.je_totals_label.config(text=f"جمع بدهکار: {total_debit}   |   جمع بستانکار: {total_credit}")

    def _reset_journal_form(self):
        self.pending_lines = []
        for row in self.lines_tree.get_children():
            self.lines_tree.delete(row)
        self.je_desc_var.set("")
        self._update_totals_label()

    def _on_post_entry(self):
        try:
            y, m, d = self.je_date_var.get().strip().split("-")
            entry_date = date(int(y), int(m), int(d))
        except Exception:
            messagebox.showerror("خطا", "تاریخ باید به فرمت YYYY-MM-DD باشد."); return

        if not self.pending_lines:
            messagebox.showerror("خطا", "حداقل دو ردیف سند اضافه کنید."); return

        entry = JournalEntry(
            entry_date=entry_date,
            lines=list(self.pending_lines),
            description=self.je_desc_var.get().strip(),
            fiscal_year=self.fiscal_year.get().strip(),
        )
        try:
            posted = self.journal_service.create_and_post(entry, user="کاربر-ویندوز")
            messagebox.showinfo("موفق", f"سند شماره {posted.number} ثبت شد.\n"
                                         f"بدهکار: {posted.total_debit}  بستانکار: {posted.total_credit}")
            self._reset_journal_form()
            self._refresh_trial_balance()
            self._refresh_audit_table()
        except DomainError as e:
            messagebox.showerror("سند ثبت نشد", str(e))

    # ---------- تب ۳: تراز آزمایشی ----------
    def _build_trial_tab(self):
        btns = tk.Frame(self.tab_trial, bg=COLOR_BG)
        btns.pack(fill="x", padx=10, pady=10)
        ttk.Button(btns, text="🔄 بروزرسانی تراز", style="Primary.TButton",
                   command=self._refresh_trial_balance).pack(side="right", padx=5)
        ttk.Button(btns, text="📕 صدور سند اختتامیه سال مالی", command=self._on_close_year).pack(side="right", padx=5)

        columns = ("code", "name", "debit", "credit")
        self.trial_tree = ttk.Treeview(self.tab_trial, columns=columns, show="headings", height=16)
        self.trial_tree.heading("code", text="کد حساب")
        self.trial_tree.heading("name", text="نام حساب")
        self.trial_tree.heading("debit", text="بدهکار")
        self.trial_tree.heading("credit", text="بستانکار")
        self.trial_tree.column("code", width=110, anchor="center")
        self.trial_tree.column("name", width=300, anchor="e")
        self.trial_tree.column("debit", width=150, anchor="center")
        self.trial_tree.column("credit", width=150, anchor="center")
        self.trial_tree.pack(fill="both", expand=True, padx=10)

        self.trial_status_label = tk.Label(self.tab_trial, text="", font=FONT_BOLD, bg=COLOR_BG)
        self.trial_status_label.pack(pady=10)

    def _refresh_trial_balance(self):
        for row in self.trial_tree.get_children():
            self.trial_tree.delete(row)
        fy = self.fiscal_year.get().strip()
        tb = TrialBalanceService(self.journal_repo, self.account_repo).compute(fy)
        for code, bal in sorted(tb["accounts"].items()):
            acc = self.account_repo.get_by_code(code)
            name = acc.name if acc else "؟"
            self.trial_tree.insert("", "end", values=(code, name, f"{bal['debit']}", f"{bal['credit']}"))
        self.trial_tree.insert("", "end", values=("", "جمع کل", f"{tb['total_debit']}", f"{tb['total_credit']}"))

        if tb["is_balanced"]:
            self.trial_status_label.config(text="✅ تراز است — بدهکار = بستانکار", fg=COLOR_SUCCESS)
        else:
            self.trial_status_label.config(text="❌ تراز نیست — بررسی داده لازم است", fg=COLOR_DANGER)

    def _on_close_year(self):
        fy = self.fiscal_year.get().strip()
        if not messagebox.askyesno("تأیید", f"آیا از صدور سند اختتامیه سال مالی {fy} مطمئن هستید؟"):
            return
        try:
            entry = self.closing_service.close_temporary_accounts(fy, date.today(), user="کاربر-ویندوز")
            details = "\n".join(
                f"{l.account_code}: {'بدهکار' if l.debit else 'بستانکار'} {l.debit or l.credit}"
                for l in entry.lines
            )
            messagebox.showinfo("سند اختتامیه ثبت شد", f"سند شماره {entry.number}:\n{details}")
            self._refresh_trial_balance()
            self._refresh_audit_table()
        except DomainError as e:
            messagebox.showerror("خطا", str(e))

    # ---------- تب ۴: رهگیری عملیات ----------
    def _build_audit_tab(self):
        ttk.Button(self.tab_audit, text="🔄 بروزرسانی", style="Primary.TButton",
                   command=self._refresh_audit_table).pack(anchor="e", padx=10, pady=10)

        columns = ("ts", "user", "action", "details")
        self.audit_tree = ttk.Treeview(self.tab_audit, columns=columns, show="headings", height=18)
        self.audit_tree.heading("ts", text="زمان")
        self.audit_tree.heading("user", text="کاربر")
        self.audit_tree.heading("action", text="عملیات")
        self.audit_tree.heading("details", text="جزئیات")
        self.audit_tree.column("ts", width=160, anchor="center")
        self.audit_tree.column("user", width=120, anchor="center")
        self.audit_tree.column("action", width=160, anchor="center")
        self.audit_tree.column("details", width=400, anchor="e")
        self.audit_tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _refresh_audit_table(self):
        for row in self.audit_tree.get_children():
            self.audit_tree.delete(row)
        for rec in self.audit_log.all():
            self.audit_tree.insert("", "end", values=(rec["ts"], rec["user"], rec["action"], rec["details"]))


if __name__ == "__main__":
    app = AccountingApp()
    app.mainloop()
