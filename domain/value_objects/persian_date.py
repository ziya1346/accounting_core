from __future__ import annotations
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PersianDate:
    """Value Object تاریخ شمسی — غیرقابل تغییر و deterministic"""
    year: int
    month: int
    day: int

    def __post_init__(self):
        if not (1 <= self.month <= 12):
            raise ValueError("ماه باید بین ۱ تا ۱۲ باشد")
        if not (1 <= self.day <= self.days_in_month()):
            raise ValueError(f"روز نامعتبر برای ماه {self.month}")

    @staticmethod
    def is_leap_year(year: int) -> bool:
        return ((year + 38) * 31) % 33 < 8

    def days_in_month(self) -> int:
        if self.month <= 6:
            return 31
        if self.month <= 11:
            return 30
        return 30 if self.is_leap_year(self.year) else 29

    @classmethod
    def create(cls, year: int, month: int, day: int) -> "PersianDate":
        return cls(year, month, day)

    def to_gregorian(self) -> date:
        jy = self.year - 979
        jm = self.month - 1
        jd = self.day - 1

        j_day_no = 365 * jy + (jy // 33) * 8 + ((jy % 33) + 3) // 4
        for i in range(jm):
            j_day_no += 31 if i < 6 else 30

        j_day_no += jd
        g_day_no = j_day_no + 79

        gy = 1600 + 400 * (g_day_no // 146097)
        g_day_no = g_day_no % 146097

        leap = True
        if g_day_no >= 36525:
            g_day_no -= 1
            gy += 100 * (g_day_no // 36524)
            g_day_no = g_day_no % 36524
            if g_day_no >= 365:
                g_day_no += 1
            else:
                leap = False

        gy += 4 * (g_day_no // 1461)
        g_day_no %= 1461

        if g_day_no >= 366:
            leap = False
            g_day_no -= 1
            gy += g_day_no // 365
            g_day_no = g_day_no % 365

        gd = g_day_no + 1
        sal_a = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        gm = 0
        while gm < 13 and gd > sal_a[gm]:
            gd -= sal_a[gm]
            gm += 1

        return date(gy, gm, gd)

    @classmethod
    def from_gregorian(cls, g_date: date) -> "PersianDate":
        gy, gm, gd = g_date.year, g_date.month, g_date.day
        g_day_no = 365 * (gy - 1600) + (gy - 1600) // 4 - (gy - 1600) // 100 + (gy - 1600) // 400

        for i in range(1, gm):
            g_day_no += [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][i]
        if gm > 2 and ((gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)):
            g_day_no += 1
        g_day_no += gd - 1

        j_day_no = g_day_no - 79
        j_np = j_day_no // 12053
        j_day_no %= 12053
        jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
        j_day_no %= 1461

        if j_day_no >= 366:
            jy += (j_day_no - 1) // 365
            j_day_no = (j_day_no - 1) % 365

        jm = 0
        while jm < 11 and j_day_no >= (31 if jm < 6 else 30):
            j_day_no -= 31 if jm < 6 else 30
            jm += 1
        jm += 1
        jd = j_day_no + 1

        return cls(jy, jm, jd)

    def __str__(self) -> str:
        return f"{self.year}/{self.month:02d}/{self.day:02d}"
