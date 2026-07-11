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

@app.get("/")
async def index(request: Request):
    uid = auth.read_session(request.cookies.get("session"))
    if uid is None:
        return RedirectResponse("/login", status_code=302)
    return FileResponse(WEB_DIR / "index.html")


@app.get("/login")
async def login_page():
    html = (WEB_DIR / "login.html").read_text(encoding="utf-8")
    html = html.replace("__BOT_USERNAME__", BOT_USERNAME)
    return HTMLResponse(html)


@app.get("/app.js")
async def app_js():
    return FileResponse(WEB_DIR / "app.js", media_type="application/javascript")


@app.get("/style.css")
async def style_css():
    return FileResponse(WEB_DIR / "style.css", media_type="text/css")


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
    daily_expenses = await db.get_daily_expenses(uid, start, end)

    return {
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
    return {"items": await db.get_daily_expenses(uid, start, end)}


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
    category_id: int


@app.patch("/api/transactions/{tx_id}")
async def api_update_transaction(tx_id: int, body: TxPatch, uid: int = Depends(get_current_user)):
    category = await db.get_category(body.category_id)
    if category is None or (category["telegram_id"] not in (None, uid)):
        raise HTTPException(status_code=400, detail="Категория не найдена")
    updated = await db.update_transaction_category(uid, tx_id, body.category_id)
    if not updated:
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
