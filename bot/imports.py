"""
Импорт банковских выписок: пользователь присылает файл → выбирает банк →
парсер (parsers/) разбирает его в список операций → каждая строка сверяется
с уже существующими записями (дедуп ±1 день по такой же сумме):
  0 похожих  → новая запись, с автокатегоризацией
  1 похожая, ручная  → помечаем её сверенной выпиской, дубликат не создаём
  1 похожая, тоже импортированная → пропускаем как дубликат
  несколько похожих → откладываем в очередь, спрашиваем пользователя
"""
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
    parser = parsers.get_parser(bank_code)
    if not parser:
        await query.edit_message_text("Банк не распознан.")
        return

    await query.edit_message_text(f"Разбираю файл ({parser.display_name})…")
    uid = update.effective_user.id
    try:
        tg_file = await context.bot.get_file(pending["file_id"])
        content = bytes(await tg_file.download_as_bytearray())
        parsed = parser.parse(content, pending["filename"] or "")
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
    imported = reconciled = duplicate = 0
    review_queue = []

    for row in parsed:
        candidates = await db.find_dedup_candidates(uid, row.type, row.amount, row.occurred_at)

        if not candidates:
            if row.type not in categories_cache:
                categories_cache[row.type] = await db.get_categories(uid, row.type)
            cats = categories_cache[row.type]
            guessed = await autocategorize.guess(uid, row.raw_description, row.type, cats)
            category = guessed or await db.find_category_by_name(uid, _FALLBACK_CATEGORY[row.type])
            import_hash = compute_import_hash(bank_code, row.occurred_at, row.amount, row.raw_description)
            tx_id = await db.add_imported_transaction(
                uid, category["id"] if category else None, row.type, row.amount,
                row.raw_description, row.occurred_at, bank_code, row.raw_description,
                batch_id, import_hash,
            )
            if tx_id:
                imported += 1
                if guessed and row.raw_description:
                    await db.remember_category(uid, row.raw_description, guessed["id"])
            else:
                duplicate += 1  # такая же строка уже импортирована раньше (совпал import_hash)
        elif len(candidates) == 1 and candidates[0]["source"] == "manual":
            await db.reconcile_transaction(uid, candidates[0]["id"], bank_code, row.raw_description)
            reconciled += 1
        elif len(candidates) == 1:
            duplicate += 1
        else:
            review_queue.append({"row": row, "candidates": candidates, "bank": bank_code, "batch_id": batch_id})

    await db.finalize_import_batch(
        batch_id, len(parsed), imported, reconciled, duplicate, len(review_queue)
    )

    lines = [f"Импорт из {bank_label} завершён — строк в файле: {len(parsed)}."]
    if imported:
        lines.append(f"✅ Новых записей: {imported}")
    if reconciled:
        lines.append(f"🔗 Сверено с ручными записями: {reconciled}")
    if duplicate:
        lines.append(f"♻️ Уже было импортировано раньше: {duplicate}")
    if review_queue:
        lines.append(f"❓ Похоже на дубли, нужно уточнить: {len(review_queue)}")
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
        src = "ручная" if c["source"] == "manual" else f"импорт {c['bank']}"
        label = f"{day} ({src})"
        lines.append(f"  • {label}")
        options.append((label, c["id"]))
    await message.reply_text("\n".join(lines), reply_markup=keyboards.import_review_keyboard(options))


async def handle_review_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    queue = context.chat_data.get("import_review") or []
    if not queue:
        await query.edit_message_text("Очередь уточнений уже закрыта.")
        return
    item = queue.pop(0)
    row = item["row"]
    uid = update.effective_user.id

    if query.data.startswith("impuse:"):
        tx_id = int(query.data.split(":", 1)[1])
        await db.reconcile_transaction(uid, tx_id, item["bank"], row.raw_description)
        await query.edit_message_text("Сверено с существующей записью.")
    elif query.data == "impnew":
        categories = await db.get_categories(uid, row.type)
        guessed = await autocategorize.guess(uid, row.raw_description, row.type, categories)
        category = guessed or await db.find_category_by_name(uid, _FALLBACK_CATEGORY[row.type])
        import_hash = compute_import_hash(item["bank"], row.occurred_at, row.amount, row.raw_description)
        await db.add_imported_transaction(
            uid, category["id"] if category else None, row.type, row.amount,
            row.raw_description, row.occurred_at, item["bank"], row.raw_description,
            item["batch_id"], import_hash,
        )
        await query.edit_message_text("Добавлено как новая запись.")
    else:  # impskip
        await query.edit_message_text("Пропущено.")

    if queue:
        await _present_review_item(query.message, context)
    else:
        context.chat_data.pop("import_review", None)
