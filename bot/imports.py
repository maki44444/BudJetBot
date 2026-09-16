"""
Импорт банковских выписок: пользователь присылает файл → выбирает банк →
парсер (parsers/) разбирает его в список операций → каждая строка проверяется:

  1. хэш строки уже есть в БД  → эта операция импортирована раньше, пропуск
  2. есть ровно одна ручная НЕ сверенная запись с той же суммой в ±1 день
     → помечаем её сверенной выпиской, дубликат не создаём
  3. таких ручных записей несколько → откладываем в очередь, спрашиваем
  4. иначе → новая запись с автокатегоризацией

Дубли между строками самой выписки ловит только хэш (шаг 1). Раньше на шаге 2
кандидатами были и импортированные записи, из-за чего две одинаковые покупки
за день схлопывались в одну и вторая молча терялась.
"""
import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

import db
import parsers
from parsers.dedup import compute_import_hash
from . import access, autocategorize, common, keyboards

logger = logging.getLogger(__name__)

_FALLBACK_CATEGORY = {"expense": "Другое", "income": "Прочий доход"}


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await access.check_access(update, context):
        return
    doc = update.message.document
    context.user_data["pending_import"] = {"file_id": doc.file_id, "filename": doc.file_name}
    await update.message.reply_text(
        f"Файл «{doc.file_name}» — из какого банка выписка?",
        reply_markup=keyboards.import_bank_keyboard(),
    )


async def handle_bank_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bank_code = query.data.split(":", 1)[1]
    pending = context.user_data.pop("pending_import", None)
    if not pending:
        await query.edit_message_text("Сессия истекла — пришли файл ещё раз.")
        return
    uid = update.effective_user.id
    settings = await db.get_user_settings(uid)
    parser = parsers.get_parser(bank_code, own_phones=db.parse_own_phones(settings.get("own_phones")))
    if not parser:
        await query.edit_message_text("Банк не распознан.")
        return

    await query.edit_message_text(f"Разбираю файл ({parser.display_name})…")
    try:
        tg_file = await context.bot.get_file(pending["file_id"])
        content = bytes(await tg_file.download_as_bytearray())
        # разбор синхронный и небыстрый (pdfplumber на десятках страниц) —
        # уводим в поток, иначе на это время встаёт весь бот
        parsed = await asyncio.to_thread(parser.parse, content, pending["filename"] or "")
    except NotImplementedError as e:
        await query.message.reply_text(str(e))
        return
    except Exception:
        logger.exception("Не удалось разобрать выписку %s для %s", bank_code, uid)
        await query.message.reply_text(
            "Не получилось разобрать файл — возможно, это не выписка "
            f"{parser.display_name}, либо формат отличается от ожидаемого."
        )
        return

    if not parsed:
        await query.message.reply_text("В файле не нашлось ни одной операции.")
        return

    await _process_batch(query.message, context, uid, bank_code, parser.display_name, parsed, pending["filename"])


async def _process_batch(message, context, uid, bank_code, bank_label, parsed, filename):
    batch_id = await db.create_import_batch(uid, bank_code, filename)
    categories_cache: dict[str, list[dict]] = {}
    imported = reconciled = duplicate = transfers = 0
    review_queue = []

    for seq, row in enumerate(parsed):
        import_hash = compute_import_hash(
            bank_code, row.occurred_at, row.amount, row.raw_description,
            row.external_id, row.type,
        )
        if await db.import_hash_exists(uid, import_hash):
            duplicate += 1
            continue

        candidates = await db.find_reconcile_candidates(uid, row.type, row.amount, row.occurred_at)

        if len(candidates) == 1:
            await db.reconcile_transaction(
                uid, candidates[0]["id"], bank_code, row.raw_description, import_hash,
            )
            reconciled += 1
        elif len(candidates) > 1:
            review_queue.append({
                "seq": seq, "row": row, "candidates": candidates,
                "bank": bank_code, "batch_id": batch_id, "hash": import_hash,
            })
        else:
            if row.type not in categories_cache:
                categories_cache[row.type] = await db.get_categories(uid, row.type)
            cats = categories_cache[row.type]
            # Переводы между своими счетами не участвуют ни в одной сводке,
            # поэтому категорию для них не угадываем: на реальных выписках это
            # 261 запрос к ИИ из 682 — впустую и прямиком в лимиты бесплатного API
            guessed = None
            if not row.is_transfer:
                guessed = await autocategorize.guess(uid, row.raw_description, row.type, cats)
            category = guessed or await db.find_category_by_name(uid, _FALLBACK_CATEGORY[row.type])
            tx_id = await db.add_imported_transaction(
                uid, category["id"] if category else None, row.type, row.amount,
                row.raw_description, row.occurred_at, bank_code, row.raw_description,
                batch_id, import_hash, row.is_transfer,
                # категорию не угадали — запись пойдёт в разбор группами (/sort)
                needs_category=not guessed and not row.is_transfer,
            )
            if tx_id:
                imported += 1
                if row.is_transfer:
                    transfers += 1
                elif guessed and row.raw_description:
                    await db.remember_category(uid, row.raw_description, guessed["id"])
            else:
                duplicate += 1

    await db.finalize_import_batch(
        batch_id, len(parsed), imported, reconciled, duplicate, len(review_queue)
    )

    lines = [f"Импорт из {bank_label} завершён — строк в файле: {len(parsed)}."]
    if imported:
        lines.append(f"✅ Новых записей: {imported}")
    if transfers:
        lines.append(f"🔁 Из них переводов между своими счетами: {transfers} (в тратах не учтены)")
    if reconciled:
        lines.append(f"🔗 Сверено с ручными записями: {reconciled}")
    if duplicate:
        lines.append(f"♻️ Уже было импортировано раньше: {duplicate}")
    if review_queue:
        lines.append(f"❓ Похоже на дубли, нужно уточнить: {len(review_queue)}")
    groups = await db.count_category_groups(uid)
    if groups:
        lines.append(f"\n🗂 Без категории: {groups} групп — разобрать: /sort")
    await message.reply_text("\n".join(lines), reply_markup=keyboards.main_keyboard())

    if review_queue:
        context.chat_data["import_review"] = review_queue
        await _present_review_item(message, context)


async def _present_review_item(message, context: ContextTypes.DEFAULT_TYPE):
    queue = context.chat_data.get("import_review") or []
    if not queue:
        context.chat_data.pop("import_review", None)
        return
    item = queue[0]
    row, candidates = item["row"], item["candidates"]
    sign = "+" if row.type == "income" else "-"
    lines = [
        "Не могу понять, добавлять ли эту запись из выписки — похоже, уже есть похожая:",
        f"{sign}{common.fmt_amount(row.amount)}₽ {row.raw_description} "
        f"({row.occurred_at.astimezone(common.MOSCOW).strftime('%d.%m.%Y')})",
        "",
        "Похожие записи у тебя уже есть:",
    ]
    options = []
    for c in candidates:
        day = c["occurred_at"].astimezone(common.MOSCOW).strftime("%d.%m.%Y")
        desc = f" {c['description']}" if c["description"] else ""
        label = f"{day}{desc}"[:60]
        lines.append(f"  • {label}")
        options.append((label, c["id"]))
    await message.reply_text(
        "\n".join(lines),
        reply_markup=keyboards.import_review_keyboard(item["batch_id"], item["seq"], options),
    )


async def handle_review_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split(":")
    action, batch_id, seq = parts[0], int(parts[1]), int(parts[2])
    queue = context.chat_data.get("import_review") or []

    # кнопка относится к строке, которая уже обработана: двойное нажатие,
    # тап по старому сообщению или вовсе по прошлому импорту. Без этой проверки
    # решение применилось бы к текущей голове очереди, то есть к чужой строке.
    if not queue or queue[0]["batch_id"] != batch_id or queue[0]["seq"] != seq:
        await query.answer("Эта кнопка уже неактуальна", show_alert=True)
        return
    await query.answer()

    item = queue.pop(0)
    row = item["row"]
    uid = update.effective_user.id

    if action == "impuse":
        tx_id = int(parts[3])
        await db.reconcile_transaction(uid, tx_id, item["bank"], row.raw_description, item["hash"])
        await query.edit_message_text("Сверено с существующей записью.")
    elif action == "impnew":
        categories = await db.get_categories(uid, row.type)
        guessed = await autocategorize.guess(uid, row.raw_description, row.type, categories)
        category = guessed or await db.find_category_by_name(uid, _FALLBACK_CATEGORY[row.type])
        new_id = await db.add_imported_transaction(
            uid, category["id"] if category else None, row.type, row.amount,
            row.raw_description, row.occurred_at, item["bank"], row.raw_description,
            item["batch_id"], item["hash"], row.is_transfer,
        )
        await query.edit_message_text(
            "Добавлено как новая запись." if new_id
            else "Такая операция уже импортирована — ничего не добавил."
        )
    else:  # impskip
        await query.edit_message_text("Пропущено.")

    if queue:
        await _present_review_item(query.message, context)
    else:
        context.chat_data.pop("import_review", None)
