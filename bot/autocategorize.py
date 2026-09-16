"""Общая автокатегоризация: сначала память прошлых выборов пользователя,
потом ИИ (если настроен). Используется быстрым вводом и импортом выписок."""
import ai
import db


async def guess_with_source(
    uid: int, description: str | None, type_: str, categories: list[dict]
) -> tuple[dict | None, str]:
    """Категория плюс откуда она взялась: 'memory', 'ai' или '' если не угадали.

    Источник важен при импорте: «Другое» от ИИ — это не ответ, а та же
    неизвестность, и такую запись надо отправить в разбор. А то же «Другое»
    из памяти — осознанный выбор пользователя, его трогать нельзя."""
    if not description:
        return None, ""
    category = await db.recall_category(uid, description, type_)
    if category is not None:
        return category, "memory"
    if not ai.enabled():
        return None, ""
    guessed_id = await ai.guess_category(description, categories)
    if not guessed_id:
        return None, ""
    return next((c for c in categories if c["id"] == guessed_id), None), "ai"


async def guess(uid: int, description: str | None, type_: str, categories: list[dict]) -> dict | None:
    """Возвращает угаданную категорию или None, если ни память, ни ИИ не дали ответа."""
    category, _ = await guess_with_source(uid, description, type_, categories)
    return category
