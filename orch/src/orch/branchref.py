"""Ссылка владельца → имя ветки.

Единственный способ дать оркестратору свободный текст без участия модели —
поле ввода сессии (`composer.read`). Поэтому ветку для задачи владелец не
выбирает из списка, а вставляет ссылкой: адрес ветки, адрес PR или просто
имя. Разбор здесь, а не в панели, чтобы его можно было проверить тестом.
"""

from __future__ import annotations

import re
import subprocess
from urllib.parse import unquote, urlparse

# https://github.com/o/r/tree/feature/x  и  .../pull/4
_TREE = re.compile(r"^/[^/]+/[^/]+/tree/(?P<branch>.+)$")
_PULL = re.compile(r"^/[^/]+/[^/]+/pulls?/(?P<number>\d+)")
# .../compare/main...feature/x
_COMPARE = re.compile(r"^/[^/]+/[^/]+/compare/(?:[^.]+\.\.\.)?(?P<branch>.+)$")


class BranchRefError(Exception):
    """Из ссылки не вышло имя ветки; текст объясняет владельцу, что не так."""


def parse(ref: str, project: str | None = None) -> str:
    """Имя ветки из того, что владелец вставил в поле ввода.

    Понимает адрес ветки, адрес PR (спрашивает у `gh`), адрес сравнения и
    просто имя ветки. Пустая строка или мусор — понятная ошибка.
    """
    ref = (ref or "").strip().strip("<>").rstrip("/")
    if not ref:
        raise BranchRefError("поле ввода пустое: вставьте ссылку на ветку или на PR")

    if "://" not in ref:
        if " " in ref:
            raise BranchRefError(
                f"«{ref[:60]}» не похоже на ветку: в имени ветки нет пробелов. "
                "Вставьте ссылку на ветку или на PR"
            )
        return ref

    path = unquote(urlparse(ref).path)

    match = _TREE.match(path)
    if match:
        return match.group("branch")

    match = _PULL.match(path)
    if match:
        return _branch_of_pr(ref, match.group("number"), project)

    match = _COMPARE.match(path)
    if match:
        return match.group("branch")

    raise BranchRefError(
        f"не понял, где здесь ветка: {ref[:80]}. Нужна ссылка вида "
        "…/tree/<ветка> или …/pull/<номер>, либо просто имя ветки"
    )


def _branch_of_pr(url: str, number: str, project: str | None) -> str:
    """Ветку PR знает только GitHub — спрашиваем `gh`, а не гадаем по номеру."""
    out = subprocess.run(
        ["gh", "pr", "view", url, "--json", "headRefName", "-q", ".headRefName"],
        cwd=project or None,
        capture_output=True,
        text=True,
        timeout=60,
    )
    branch = out.stdout.strip()
    if out.returncode != 0 or not branch:
        raise BranchRefError(
            f"не спросил у GitHub ветку PR #{number}: "
            f"{(out.stderr or '').strip()[:200] or 'gh промолчал'}"
        )
    return branch
