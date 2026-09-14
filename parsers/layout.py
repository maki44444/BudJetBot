"""
Разбор PDF по координатам слов.

Выписки вёрстаются таблицей, и длинное описание переносится на следующие
строки. В плоском тексте (extract_text) такой перенос неотличим от подписи
в подвале страницы — а приклеить подпись к описанию нельзя: там встречается
ФИО владельца, и операция ошибочно сойдёт за перевод самому себе.

Настоящее продолжение описания начинается ровно с левого края своей колонки,
подпись и колонтитул — с других позиций. Поэтому строки собираются из слов
вместе с координатой x0, и продолжение опознаётся по ней.
"""

# слова одной строки отличаются по вертикали максимум на пару пунктов
LINE_TOLERANCE = 3.0


def group_lines(page, tolerance: float = LINE_TOLERANCE) -> list[list[dict]]:
    """Слова страницы, сгруппированные в строки сверху вниз.
    Внутри строки слова идут слева направо, у каждого есть x0."""
    words = page.extract_words()
    if not words:
        return []

    lines: list[list[dict]] = []
    current: list[dict] = []
    base = None
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if base is None or abs(word["top"] - base) <= tolerance:
            if base is None:
                base = word["top"]
            current.append(word)
        else:
            lines.append(sorted(current, key=lambda w: w["x0"]))
            current, base = [word], word["top"]
    if current:
        lines.append(sorted(current, key=lambda w: w["x0"]))
    return lines


def line_text(words: list[dict]) -> str:
    return " ".join(w["text"] for w in words)
