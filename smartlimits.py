"""
Умные лимиты: подбор стартовых значений по тратам и плавный ежемесячный пересчёт.

Оценка месячных трат по категории — темп за последние 90 дней (без разовых ⚡),
приведённый к месяцу. Автолимит следует за оценкой, но не быстрее ±10% в месяц.
"""

MIN_MONTHLY_EST = 500.0   # категории с оценкой ниже — шум, лимит не предлагаем
MAX_STEP = 0.10           # максимальный шаг автопересчёта за месяц
YOUNG_DATA_DAYS = 45      # пока учёту меньше — пересчёт без ограничения шага
                          # (первые оценки грубые, дать им быстро исправиться)


def nice_round(value: float) -> int:
    """Округляет к «красивому» числу: 17 483 → 17 500, 1 234 → 1 200."""
    if value >= 20000:
        step = 1000
    elif value >= 5000:
        step = 500
    elif value >= 1000:
        step = 100
    else:
        step = 50
    return int(round(value / step) * step)


def suggest_limits(rates: list[dict]) -> list[dict]:
    """Из оценок месячных трат делает предложения лимитов (значимые категории)."""
    suggestions = []
    for r in rates:
        if r["monthly_est"] < MIN_MONTHLY_EST:
            continue
        suggestions.append({**r, "suggested": nice_round(r["monthly_est"])})
    return suggestions


def next_auto_limit(current: float, target: float, snap: bool = False) -> int:
    """Следующее значение автолимита: тянется к target, но не быстрее ±10%.
    snap=True (учёт ведётся недавно) — сразу к target без ограничения шага."""
    if target <= 0:
        return nice_round(current)  # нет данных по категории — лимит не трогаем
    if snap:
        return nice_round(target)
    low = current * (1 - MAX_STEP)
    high = current * (1 + MAX_STEP)
    return nice_round(min(max(target, low), high))
