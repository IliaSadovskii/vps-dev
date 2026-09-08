"""Поиск папки задачи по рабочей копии.

Задача опознаётся по каталогу, а не по окружению: AoE не передаёт
переменные окружения обычным сессиям (`research/RISKS.md` п. 1). Одна
рабочая копия принадлежит ровно одной задаче, в ней лежит
`.orch/<task>/current.json`, который движок переписывает перед промптом.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


class NotInTask(Exception):
    """Команда вызвана не из рабочей копии задачи."""


def git_toplevel(start: Path | None = None) -> Path | None:
    """Корень рабочей копии git для каталога `start` (или текущего)."""
    cwd = Path(start) if start else Path.cwd()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    top = out.stdout.strip()
    return Path(top) if top else None


@dataclass(frozen=True)
class TaskDir:
    """Папка задачи `.orch/<task>/` и её текущее состояние."""

    root: Path          # корень рабочей копии
    path: Path          # .orch/<task>
    task_id: str
    current: dict

    @property
    def step(self) -> str:
        return self.current.get("step", "")

    @property
    def run(self) -> int:
        return int(self.current.get("run", 0))

    @property
    def gate_after(self) -> bool | list[str]:
        """Исходы, после которых задача встанет на владельце."""
        return self.current.get("gate_after", False)

    @property
    def ask_allowed(self) -> bool:
        return bool(self.current.get("ask", True))

    @property
    def artifacts(self) -> Path:
        return self.path / "artifacts"

    @property
    def signals(self) -> Path:
        return self.path / "signals"

    @property
    def chain_yaml(self) -> Path:
        return self.path / "chain.yml"


def find_task(start: Path | None = None) -> TaskDir:
    """Найти папку задачи от текущего каталога вверх.

    Порядок: `ORCH_DIR` из окружения (для тестов), потом корень рабочей
    копии git. Внутри — единственный каталог `.orch/<task>/` с
    `current.json`.
    """
    override = os.environ.get("ORCH_DIR")
    if override:
        path = Path(override)
        if not (path / "current.json").exists():
            raise NotInTask(f"ORCH_DIR={override}: нет current.json")
        return _load(path.parent.parent, path)

    root = git_toplevel(start)
    if root is None:
        raise NotInTask(
            "вызван не из рабочей копии git; команда orch работает "
            "только в рабочей копии задачи"
        )
    base = root / ".orch"
    if not base.is_dir():
        raise NotInTask(
            f"в {root} нет каталога .orch: это не рабочая копия задачи orch"
        )
    candidates = sorted(p for p in base.iterdir() if (p / "current.json").exists())
    if not candidates:
        raise NotInTask(f"в {base} нет задачи с current.json")
    if len(candidates) > 1:
        names = ", ".join(p.name for p in candidates)
        raise NotInTask(
            f"в {base} несколько задач ({names}); одна рабочая копия — одна задача"
        )
    return _load(root, candidates[0])


def _load(root: Path, path: Path) -> TaskDir:
    data = json.loads((path / "current.json").read_text(encoding="utf-8"))
    return TaskDir(
        root=root,
        path=path,
        task_id=str(data.get("task") or path.name),
        current=data,
    )
