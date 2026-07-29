"""
Парсер выписки Альфа-Банка. Ждёт файл-пример реальной выписки от пользователя —
точный формат колонок (Excel/CSV/PDF из приложения Альфа-Банка) пока неизвестен.
"""
from .base import BankStatementParser, ParsedTransaction


class AlfaBankParser(BankStatementParser):
    bank_code = "alfa"
    display_name = "Альфа-Банк"
    supported_extensions = (".xlsx", ".csv", ".pdf")

    def parse(self, content: bytes, filename: str) -> list[ParsedTransaction]:
        raise NotImplementedError(
            "Парсер Альфа-Банка ещё не готов — нужен файл-пример реальной выписки."
        )
