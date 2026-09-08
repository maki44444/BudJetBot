"""Хэш строки выписки — защита от повторного импорта одного и того же файла
на уровне БД (уникальный индекс transactions(telegram_id, import_hash)).

Хэш обязан различать РАЗНЫЕ операции и совпадать у ОДНОЙ И ТОЙ ЖЕ операции,
импортированной повторно. Поэтому:
  * если банк даёт номер операции (external_id) — хэш строится по нему,
    это самый надёжный ключ;
  * иначе берётся время с точностью до секунды, а не дата, плюс сумма
    и описание. Дата целиком склеивала бы две одинаковые покупки за день
    в одну, и вторая молча терялась бы.
"""
import hashlib
from datetime import datetime
from decimal import Decimal


def compute_import_hash(
    bank: str,
    occurred_at: datetime,
    amount: Decimal,
    raw_description: str,
    external_id: str | None = None,
) -> str:
    if external_id:
        key = f"{bank}|id:{external_id.strip()}"
    else:
        key = (
            f"{bank}|{occurred_at.isoformat()}|{amount}|{raw_description.strip().lower()}"
        )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
