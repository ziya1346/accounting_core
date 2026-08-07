from enum import Enum


class Currency(str, Enum):
    """ارزهای پشتیبانی‌شده در سیستم"""
    IRR = "IRR"   # ریال ایران
    IRT = "IRT"   # تومان ایران
    USD = "USD"
    EUR = "EUR"
    AED = "AED"
    TRY = "TRY"

    @property
    def decimal_digits(self) -> int:
        if self in (Currency.IRR, Currency.IRT):
            return 0
        return 2

    @property
    def name_fa(self) -> str:
        names = {
            Currency.IRR: "ریال ایران",
            Currency.IRT: "تومان ایران",
            Currency.USD: "دلار آمریکا",
            Currency.EUR: "یورو",
            Currency.AED: "درهم امارات",
            Currency.TRY: "لیر ترکیه",
        }
        return names.get(self, self.value)

    @classmethod
    def from_code(cls, code: str) -> "Currency":
        try:
            return cls(code.upper())
        except ValueError:
            raise ValueError(f"ارز ناشناخته: {code}")
