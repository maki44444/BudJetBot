"""
Клиент к LLM через OpenAI-совместимый API. По умолчанию — OpenRouter,
где есть бесплатные модели. Провайдер и модель меняются переменными
окружения: AI_API_KEY, AI_BASE_URL, AI_MODEL.
Без AI_API_KEY все ИИ-функции тихо отключаются — бот работает как раньше.
"""
import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

AI_API_KEY = os.environ.get("AI_API_KEY", "")
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
AI_MODEL = os.environ.get("AI_MODEL", "meta-llama/llama-3.3-70b-instruct:free")


def enabled() -> bool:
    return bool(AI_API_KEY)


async def _chat(messages: list[dict], max_tokens: int = 400, timeout: float = 20.0) -> str | None:
    """Один запрос к модели; None при любой ошибке — вызывающий код делает fallback."""
    if not AI_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{AI_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {AI_API_KEY}",
                    "X-Title": "budget_bot",
                },
                json={
                    "model": AI_MODEL,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": 0,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return content.strip() if content else None
    except Exception:
        logger.warning("Запрос к ИИ (%s) не удался", AI_MODEL, exc_info=True)
        return None


async def guess_category(description: str, categories: list[dict]) -> int | None:
    """Угадывает категорию траты/дохода по описанию. Возвращает id категории или None."""
    listing = "\n".join(f"{c['id']} — {c['name']}" for c in categories)
    answer = await _chat(
        [
            {"role": "system", "content": (
                "Ты определяешь категорию личной траты или дохода по короткому описанию. "
                "Отвечай ТОЛЬКО числом — id категории из списка. "
                "Если уверенно определить нельзя, ответь 0."
            )},
            {"role": "user", "content": f"Категории:\n{listing}\n\nОписание: «{description}»"},
        ],
        max_tokens=10,
        timeout=12.0,
    )
    if not answer:
        return None
    match = re.search(r"\d+", answer)
    if not match:
        return None
    cat_id = int(match.group())
    return cat_id if any(c["id"] == cat_id for c in categories) else None


async def monthly_review(period_label: str, data: str) -> str | None:
    """Короткий человеческий разбор месяца по подготовленным агрегатам из БД."""
    return await _chat(
        [
            {"role": "system", "content": (
                "Ты — аналитик личного бюджета. По данным ниже напиши короткий разбор: "
                "3–5 наблюдений, каждое в одну-две фразы и с конкретными цифрами из данных. "
                "Пиши по-русски, дружелюбно и по делу. Не выдумывай цифры, которых нет в данных. "
                "Никаких общих финансовых советов («ведите бюджет», «откладывайте 10%»). "
                "Без Markdown-разметки — простой текст, каждое наблюдение с новой строки, можно эмодзи."
            )},
            {"role": "user", "content": f"Данные за {period_label}:\n\n{data}"},
        ],
        max_tokens=600,
        timeout=30.0,
    )
