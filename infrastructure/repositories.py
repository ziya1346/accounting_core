"""
Infrastructure Layer — لایه زیرساخت
پیاده‌سازی مخزن‌ها (Repositories) روی SQLite (برای نسخه تک‌کاربره طبق پرامپت).
برای نسخه سازمانی/سرور، همین اینترفیس‌ها روی PostgreSQL + SQLAlchemy پیاده می‌شوند
بدون نیاز به تغییر در Domain یا Application (اصل وارونگی وابستگی - DIP).
"""
from __future__ import annotations
import sqlite3
import json
from decimal import Decimal
from datetime import date, datetime
from typing import Optional

from domain.entities import (
    Account, AccountType, JournalEntry, JournalLine,
    JournalEntryStatus, JournalEntryType
)


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


class SchemaBuilder:
    @staticmethod
    def create_all(db_path: str):
        conn = _connect(db_path)
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id TEXT PRIMARY KEY,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            account_type TEXT NOT NULL,
            parent_code TEXT,
            is_postable INTEGER NOT NULL DEFAULT 1,
            currency TEXT NOT NULL DEFAULT 'IRR'
        );

        CREATE TABLE IF NOT EXISTS journal_entries (
            id TEXT PRIMARY KEY,
            number INTEGER,
            entry_date TEXT NOT NULL,
            entry_type TEXT NOT NULL,
            description TEXT,
            fiscal_year TEXT,
            branch_code TEXT,
            company_code TEXT,
            status TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS journal_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id TEXT NOT NULL,
            account_code TEXT NOT NULL,
            debit TEXT NOT NULL,
            credit TEXT NOT NULL,
            description TEXT,
            cost_center TEXT,
            project_code TEXT,
            FOREIGN KEY (entry_id) REFERENCES journal_entries(id)
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            user TEXT NOT NULL,
            action TEXT NOT NULL,
            entity_id TEXT,
            details TEXT
        );
        """)
        conn.commit()
        conn.close()


class SqliteAccountRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def add(self, account: Account):
        conn = _connect(self.db_path)
        conn.execute(
            "INSERT INTO accounts (id, code, name, account_type, parent_code, is_postable, currency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (account.id, account.code, account.name, account.account_type.value,
             account.parent_code, int(account.is_postable), account.currency),
        )
        conn.commit()
        conn.close()

    def get_by_code(self, code: str) -> Optional[Account]:
        conn = _connect(self.db_path)
        row = conn.execute("SELECT * FROM accounts WHERE code=?", (code,)).fetchone()
        conn.close()
        if not row:
            return None
        return Account(
            id=row[0], code=row[1], name=row[2],
            account_type=AccountType(row[3]), parent_code=row[4],
            is_postable=bool(row[5]), currency=row[6],
        )

    def all(self) -> list[Account]:
        conn = _connect(self.db_path)
        rows = conn.execute("SELECT * FROM accounts").fetchall()
        conn.close()
        return [
            Account(id=r[0], code=r[1], name=r[2], account_type=AccountType(r[3]),
                     parent_code=r[4], is_postable=bool(r[5]), currency=r[6])
            for r in rows
        ]


class SqliteJournalRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def next_number(self, fiscal_year: str) -> int:
        conn = _connect(self.db_path)
        row = conn.execute(
            "SELECT MAX(number) FROM journal_entries WHERE fiscal_year=?", (fiscal_year,)
        ).fetchone()
        conn.close()
        return (row[0] or 0) + 1

    def save(self, entry: JournalEntry):
        conn = _connect(self.db_path)
        conn.execute(
            "INSERT INTO journal_entries (id, number, entry_date, entry_type, description, "
            "fiscal_year, branch_code, company_code, status) VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET status=excluded.status, number=excluded.number",
            (entry.id, entry.number, entry.entry_date.isoformat(), entry.entry_type.value,
             entry.description, entry.fiscal_year, entry.branch_code, entry.company_code,
             entry.status.value),
        )
        # only insert lines the first time (avoid dupes on status-update saves)
        existing = conn.execute("SELECT COUNT(*) FROM journal_lines WHERE entry_id=?", (entry.id,)).fetchone()[0]
        if existing == 0:
            for line in entry.lines:
                conn.execute(
                    "INSERT INTO journal_lines (entry_id, account_code, debit, credit, description, "
                    "cost_center, project_code) VALUES (?,?,?,?,?,?,?)",
                    (entry.id, line.account_code, str(line.debit), str(line.credit),
                     line.description, line.cost_center, line.project_code),
                )
        conn.commit()
        conn.close()

    def get(self, entry_id: str) -> Optional[JournalEntry]:
        conn = _connect(self.db_path)
        row = conn.execute("SELECT * FROM journal_entries WHERE id=?", (entry_id,)).fetchone()
        if not row:
            conn.close()
            return None
        lines_rows = conn.execute("SELECT * FROM journal_lines WHERE entry_id=?", (entry_id,)).fetchall()
        conn.close()
        return self._row_to_entry(row, lines_rows)

    def all_posted(self, fiscal_year: str) -> list[JournalEntry]:
        conn = _connect(self.db_path)
        rows = conn.execute(
            "SELECT * FROM journal_entries WHERE fiscal_year=? AND status=?",
            (fiscal_year, JournalEntryStatus.POSTED.value),
        ).fetchall()
        entries = []
        for row in rows:
            lines_rows = conn.execute("SELECT * FROM journal_lines WHERE entry_id=?", (row[0],)).fetchall()
            entries.append(self._row_to_entry(row, lines_rows))
        conn.close()
        return entries

    @staticmethod
    def _row_to_entry(row, lines_rows) -> JournalEntry:
        lines = [
            JournalLine(
                account_code=lr[2], debit=Decimal(lr[3]), credit=Decimal(lr[4]),
                description=lr[5] or "", cost_center=lr[6], project_code=lr[7],
            ) for lr in lines_rows
        ]
        return JournalEntry(
            id=row[0], number=row[1],
            entry_date=date.fromisoformat(row[2]),
            entry_type=JournalEntryType(row[3]),
            description=row[4] or "", fiscal_year=row[5],
            branch_code=row[6], company_code=row[7],
            status=JournalEntryStatus(row[8]),
            lines=lines,
        )


class SqliteAuditLog:
    """پیاده‌سازی Audit Trail — ثبت غیرقابل‌تغییر تمام عملیات کاربران طبق استاندارد حسابرسی"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def record(self, user: str, action: str, entity_id: str, details: str):
        conn = _connect(self.db_path)
        conn.execute(
            "INSERT INTO audit_log (ts, user, action, entity_id, details) VALUES (?,?,?,?,?)",
            (datetime.now().isoformat(), user, action, entity_id, details),
        )
        conn.commit()
        conn.close()

    def all(self) -> list[dict]:
        conn = _connect(self.db_path)
        rows = conn.execute("SELECT * FROM audit_log ORDER BY id").fetchall()
        conn.close()
        return [
            {"id": r[0], "ts": r[1], "user": r[2], "action": r[3], "entity_id": r[4], "details": r[5]}
            for r in rows
        ]
