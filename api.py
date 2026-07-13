import logging
import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytz
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

import auth
import db

logger = logging.getLogger(__name__)

MOSCOW = pytz.timezone("Europe/Moscow")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
BOT_USERNAME = os.environ.get("BOT_USERNAME", "")

WEB_DIR = Path(__file__).parent / "web"

app = FastAPI()


# ── Аутентификация ────────────────────────────────────────────────────────────

async def get_current_user(request: Request) -> int:
    uid = auth.read_session(request.cookies.get("session"))
    if uid is None:
        raise HTTPException(status_code=401, detail="Не авторизован")
    if not (ADMIN_ID and uid == ADMIN_ID) and not await db.is_allowed(uid):
        raise HTTPException(status_code=403, detail="Нет доступа")
    return uid


@app.get("/auth/telegram")
async def auth_telegram(request: Request):
    params = dict(request.query_params)
    uid = auth.verify_login_widget(params)
    if uid is None:
        raise HTTPException(status_code=401, detail="Невалидные данные Telegram")
    allowed = (ADMIN_ID and uid == ADMIN_ID) or await db.is_allowed(uid)
    if not allowed:
        return HTMLResponse(
            "<h3>Нет доступа</h3><p>Напиши боту в Telegram и попроси доступ у администратора.</p>",
            status_code=403,
        )
    await db.ensure_user(uid, params.get("username"), params.get("first_name"))
    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        "session", auth.issue_session(uid),
        max_age=auth.SESSION_TTL, httponly=True, secure=True, samesite="lax",
    )
    return response


@app.post("/auth/logout")
async def auth_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie("session")
    return response


# ── Страницы и статика ────────────────────────────────────────────────────────

# no-cache = браузер сверяет версию с сервером на каждый запрос (304, если не менялось).
# Без этого после деплоя браузер может держать старый app.js при новом index.html —
# и Vue падает в пустую страницу из-за рассинхрона.
_NO_CACHE = {"Cache-Control": "no-cache"}


@app.get("/")
async def index(request: Request):
    uid = auth.read_session(request.cookies.get("session"))
    if uid is None:
        return RedirectResponse("/login", status_code=302)
    return FileResponse(WEB_DIR / "index.html", headers=_NO_CACHE)


@app.get("/login")
async def login_page():
    html = (WEB_DIR / "login.html").read_text(encoding="utf-8")
    html = html.replace("__BOT_USERNAME__", BOT_USERNAME)
    return HTMLResponse(html, headers=_NO_CACHE)


@app.get("/app.js")
async def app_js():
    return FileResponse(WEB_DIR / "app.js", media_type="application/javascript", headers=_NO_CACHE)


@app.get("/style.css")
async def style_css():
    return FileResponse(WEB_DIR / "style.css", media_type="text/css", headers=_NO_CACHE)


# ── Периоды ───────────────────────────────────────────────────────────────────

def _month_range(month: str | None) -> tuple[datetime, datetime, str]:
    """month в формате YYYY-MM (по умолчанию — текущий). Возвращает (start, end, label)."""
    now = datetime.now(MOSCOW)
    if month:
        try:
            year, mon = int(month[:4]), int(month[5:7])
            datetime(year, mon, 1)
        except ValueError:
            raise HTTPException(status_code=400, detail="month должен быть в формате YYYY-MM")
    else:
        year, mon = now.year, now.month
    start = MOSCOW.localize(datetime(year, mon, 1))
    if mon == 12:
        end = MOSCOW.localize(datetime(year + 1, 1, 1))
    else:
        end = MOSCOW.localize(datetime(year, mon + 1, 1))
    return start, end, f"{year:04d}-{mon:02d}"


# ── API ───────────────────────────────────────────────────────────────────────

@app.get("/api/summary")
async def api_summary(month: str | None = None, uid: int = Depends(get_current_user)):
    start, end, label = _month_range(month)
    # Прошлый месяц — для сравнения
    prev_year, prev_mon = (start.year - 1, 12) if start.month == 1 else (start.year, start.month - 1)
    prev_start, prev_end, prev_label = _month_range(f"{prev_year:04d}-{prev_mon:02d}")

    totals = await db.get_totals(uid, start, end)
    expense_breakdown = await db.get_category_breakdown(uid, start, end, "expense")
    income_breakdown = await db.get_category_breakdown(uid, start, end, "income")
    budgets = await db.get_budget_progress(uid, start, end)
    prev_totals = await db.get_totals(uid, prev_start, prev_end)
    prev_expense = await db.get_category_breakdown(uid, prev_start, prev_end, "expense")
    top_expenses = await db.get_top_expenses(uid, start, end, 5)
    daily_expenses = await db.get_daily_totals(uid, start, end)

    # Прогноз до конца месяца — только для текущего месяца.
    # Разовые траты не экстраполируются: прогноз = темп обычных трат × дни + разовые как есть.
    now = datetime.now(MOSCOW)
    forecast = None
    if (start.year, start.month) == (now.year, now.month) and totals["expense"]:
        days_in_month = (end - start).days
        days_elapsed = now.day
        oneoff = float(totals["expense_oneoff"])
        regular = float(totals["expense"]) - oneoff
        forecast = {
            "days_elapsed": days_elapsed,
            "days_in_month": days_in_month,
            "expense_forecast": regular / days_elapsed * days_in_month + oneoff,
        }

    return {
        "forecast": forecast,
        "month": label,
        "totals": totals,
        "expense_breakdown": expense_breakdown,
        "income_breakdown": income_breakdown,
        "budgets": budgets,
        "prev": {
            "month": prev_label,
            "totals": prev_totals,
            "expense_by_category": {str(r["category_id"]): r["total"] for r in prev_expense},
        },
        "top_expenses": top_expenses,
        "daily_expenses": daily_expenses,
    }


@app.get("/api/daily")
async def api_daily(days: int = Query(7, ge=1, le=90), uid: int = Depends(get_current_user)):
    """Расходы по дням за последние N дней (скользящее окно от сегодня, МСК)."""
    now = datetime.now(MOSCOW)
    end = MOSCOW.localize(datetime(now.year, now.month, now.day)) + timedelta(days=1)
    start = end - timedelta(days=days)
    return {"items": await db.get_daily_totals(uid, start, end)}


@app.get("/api/transactions")
async def api_transactions(
    month: str | None = None,
    category_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    uid: int = Depends(get_current_user),
):
    start, end, label = _month_range(month)
    items, total = await db.get_transactions_page(uid, start, end, category_id, limit, offset)
    return {"month": label, "total": total, "items": items}


class TxPatch(BaseModel):
    category_id: int | None = None
    is_oneoff: bool | None = None


@app.patch("/api/transactions/{tx_id}")
async def api_update_transaction(tx_id: int, body: TxPatch, uid: int = Depends(get_current_user)):
    if body.category_id is None and body.is_oneoff is None:
        raise HTTPException(status_code=400, detail="Нечего менять")
    if body.category_id is not None:
        category = await db.get_category(body.category_id)
        if category is None or (category["telegram_id"] not in (None, uid)):
            raise HTTPException(status_code=400, detail="Категория не найдена")
        if not await db.update_transaction_category(uid, tx_id, body.category_id):
            raise HTTPException(status_code=404, detail="Запись не найдена")
    if body.is_oneoff is not None:
        if not await db.set_transaction_oneoff(uid, tx_id, body.is_oneoff):
            raise HTTPException(status_code=404, detail="Запись не найдена")
    return {"ok": True}


@app.delete("/api/transactions/{tx_id}")
async def api_delete_transaction(tx_id: int, uid: int = Depends(get_current_user)):
    deleted = await db.delete_transaction(uid, tx_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return {"ok": True}


@app.get("/api/categories")
async def api_categories(uid: int = Depends(get_current_user)):
    return {
        "expense": await db.get_categories(uid, "expense"),
        "income": await db.get_categories(uid, "income"),
    }


@app.get("/api/settings")
async def api_get_settings(uid: int = Depends(get_current_user)):
    return await db.get_user_settings(uid)


class SettingsPatch(BaseModel):
    oneoff_threshold: float | None = None
    reminder_enabled: bool | None = None


@app.patch("/api/settings")
async def api_patch_settings(body: SettingsPatch, uid: int = Depends(get_current_user)):
    if body.oneoff_threshold is None and body.reminder_enabled is None:
        raise HTTPException(status_code=400, detail="Нечего менять")
    if body.oneoff_threshold is not None and body.oneoff_threshold <= 0:
        raise HTTPException(status_code=400, detail="Порог должен быть больше нуля")
    await db.update_user_settings(
        uid,
        oneoff_threshold=Decimal(str(body.oneoff_threshold)) if body.oneoff_threshold is not None else None,
        reminder_enabled=body.reminder_enabled,
    )
    return {"ok": True}


class LimitBody(BaseModel):
    category_id: int
    amount: float


@app.post("/api/limits")
async def api_set_limit(body: LimitBody, uid: int = Depends(get_current_user)):
    category = await db.get_category(body.category_id)
    if category is None or (category["telegram_id"] not in (None, uid)):
        raise HTTPException(status_code=400, detail="Категория не найдена")
    if body.amount < 0:
        raise HTTPException(status_code=400, detail="Сумма должна быть 0 или больше")
    if body.amount == 0:
        await db.delete_budget(uid, body.category_id)
    else:
        await db.set_budget(uid, body.category_id, Decimal(str(body.amount)))
    return {"ok": True}
