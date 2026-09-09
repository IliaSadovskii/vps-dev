"""Имена, которые движок даёт вещам: титул задачи, ветка, титул сессии."""

from __future__ import annotations

import re
from pathlib import Path

# Корень групп без задачи (роль на всю машину): `orch/побочные`. Группа
# задачи и мастера строится от имени проекта — см. `group_of`.
GROUP_ROOT = "orch"


def project_name(project_path: str) -> str:
    """Имя проекта для группы — имя каталога репозитория, не ветки.

    Сайдбар с осью «по группе» сортирует группы по имени, поэтому проект
    стоит первым: задачи одного проекта встают рядом, а не перемешиваются с
    чужими по номеру.
    """
    return Path(project_path).name or "проект"


def group_of(project_path: str, task_id: str, title: str) -> str:
    """Группа сессий задачи: `vps-dev/T35 · Завести рядом с deep…`."""
    return f"{project_name(project_path)}/{task_id} · {title}"


def wizard_group(project_path: str) -> str:
    """Группа мастера: рядом с задачами своего проекта, а не в общей куче."""
    return f"{project_name(project_path)}/мастер"


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
    title = " ".join(words[:7])[:60].rstrip(" ,;:.—-")
    if len(words) > 7:
        # Титул рвался на полуслове («PR 4 уехал автономно без владельца;
        # привести»), и в панели это читалось как сообщение движка, а не как
        # обрезанное начало ТЗ. Обрываем по границе фразы и ставим многоточие.
        edge = max(title.rfind(ch) for ch in ";,:")
        if edge > len(title) // 2:
            title = title[:edge]
        title += "…"
    return title or "задача"


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


def session_title(task_id: str, step_id: str, run_n: int = 1, own_session: bool = False) -> str:
    """Титул сессии шага в сайдбаре: `T12 · plan`, на повторе — `T12 · plan 2`.

    Номер появляется со второго захода и только там, где у каждого захода
    своя сессия (`context: fresh`): в сайдбаре встают две строки одного шага,
    и без номера их не различить. Шаг, который возвращается в свою же сессию,
    остаётся одной строкой без номера — нумеровать нечего.
    """
    if own_session or run_n < 2:
        return f"{task_id} · {step_id}"
    return f"{task_id} · {step_id} {run_n}"
