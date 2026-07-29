"""Общая автокатегоризация: сначала память прошлых выборов пользователя,
потом ИИ (если настроен). Используется быстрым вводом и импортом выписок."""
import ai
import db


async def guess(uid: int, description: str | None, type_: str, categories: list[dict]) -> dict | None:
    """Возвращает угаданную категорию или None, если ни память, ни ИИ не дали ответа."""
    if not description:
        return None
    category = await db.recall_category(uid, description, type_)
    if category is not None:
        return category
    if not ai.enabled():
        return None
    guessed_id = await ai.guess_category(description, categories)
    if not guessed_id:
        return None
    return next((c for c in categories if c["id"] == guessed_id), None)
