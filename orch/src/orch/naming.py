"""Имена, которые движок даёт вещам: титул задачи, ветка, титул сессии."""

from __future__ import annotations

import re

# Корень групп оркестратора в сайдбаре: `orch/T12 · титул`, `orch/мастер`.
GROUP_ROOT = "orch"


def title_from(text: str) -> str:
    """Титул — первые слова текста, очищенные от разметки.

    Мастер пишет ТЗ размеченным markdown («**Цель.** …»), и без чистки
    строка задачи в панели начиналась со звёздочек и слова «Цель».
    """
    first = ""
    for line in text.strip().splitlines():
        line = re.sub(r"[*_`#>]+", "", line).strip()
        line = re.sub(r"^(цель|задача|результат)[.:]\s*", "", line, flags=re.I)
        if line:
            first = line
            break
    words = (first or "задача").split()
    return " ".join(words[:7])[:60] or "задача"


def slug(title: str) -> str:
    """Хвост имени ветки: `t12-<slug>`."""
    table = str.maketrans(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
        "abvgdeejzijklmnoprstufhccss'y'eua",
    )
    s = title.lower().translate(table)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    # Обрезаем сначала, чистим дефисы потом: наоборот обрезка снова оставляет
    # дефис на конце, и имя ветки в базе расходится с именем настоящей ветки
    # (`orch push` отвечает «src refspec does not match any»).
    return s[:32].strip("-") or "task"


def session_title(task_id: str, step_id: str) -> str:
    """Титул сессии шага в сайдбаре: `T12 · plan`."""
    return f"{task_id} · {step_id}"
