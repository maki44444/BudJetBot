"""Хэш строки выписки — защита от повторного импорта одного и того же файла
на уровне БД (уникальный индекс transactions(telegram_id, import_hash))."""
import hashlib
from datetime import datetime
from decimal import Decimal


def compute_import_hash(bank: str, occurred_at: datetime, amount: Decimal, raw_description: str) -> str:
    key = f"{bank}|{occurred_at.date().isoformat()}|{amount}|{raw_description.strip().lower()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
