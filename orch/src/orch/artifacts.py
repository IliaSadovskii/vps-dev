"""Проверка артефактов роли.

«Артефакт на месте» = файл существует, не пустой, первый заголовок `## Итог`
или `## Для владельца`. Больше движок в содержание не смотрит (`PLAN.md` §5).
Одна функция на движок и на команду `orch done`, чтобы отказ команды и отказ
перехода нельзя было развести.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .chain import ARTIFACT_HEADINGS


def first_heading(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("## "):
            return line.strip()
    return None


def check(path: Path) -> str | None:
    """`None`, если файл в порядке; иначе строка с причиной для роли."""
    if not path.exists():
        return f"нет файла {path}"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"не читается {path}: {exc}"
    if not text.strip():
        return f"файл {path} пуст"
    head = first_heading(text)
    if head is None:
        return (
            f"в {path} нет ни одного заголовка `## `; "
            f"файл начинается разделом {' или '.join(ARTIFACT_HEADINGS)}"
        )
    if head not in ARTIFACT_HEADINGS:
        return (
            f"первый заголовок {path} — {head!r}; "
            f"ожидался {' или '.join(ARTIFACT_HEADINGS)}"
        )
    return None


def check_all(base: Path, names: list[str]) -> list[str]:
    """Причины отказа по всем ожидаемым артефактам шага."""
    return [reason for name in names if (reason := check(base / name))]


def sha(path: Path) -> str | None:
    """Отпечаток файла: правил ли его владелец после сдачи (`PLAN.md` §5)."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
