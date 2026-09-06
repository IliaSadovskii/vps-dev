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


def recent(project: str, limit: int = 12) -> list[dict]:
    """Свежие ветки проекта: имя, когда трогали, номер PR если есть.

    Список нужен затем, что поле ввода в AoE делает две вещи сразу: Enter
    отправляет текст агенту, а оркестратору его отдаёт отдельная маленькая
    кнопка. Человек про кнопку не знает и жмёт Enter. Щелчок по строке
    этой двусмысленности не имеет.
    """
    out = subprocess.run(
        [
            "git", "for-each-ref", "--sort=-committerdate",
            f"--count={limit}",
            "--format=%(refname:short)%09%(committerdate:relative)%09%(contents:subject)",
            "refs/heads",
        ],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=30,
    )
    branches = []
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if not parts or not parts[0]:
            continue
        branches.append(
            {"branch": parts[0], "when": parts[1] if len(parts) > 1 else "",
             "subject": parts[2] if len(parts) > 2 else "", "pr": None}
        )
    for branch in branches:
        branch["pr"] = _pr_of.get(branch["branch"]) if (_pr_of := _pull_requests(project)) else None
    return branches


def _pull_requests(project: str) -> dict[str, int]:
    """Ветка → номер открытого PR. Нет `gh` или сети — пустая карта, не беда."""
    try:
        out = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--limit", "50",
             "--json", "number,headRefName"],
            cwd=project,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if out.returncode != 0:
            return {}
        import json

        return {p["headRefName"]: p["number"] for p in json.loads(out.stdout or "[]")}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
