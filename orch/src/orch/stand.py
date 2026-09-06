"""Стенд задачи: свой блок портов и свои контейнеры.

Задача работает в отдельной копии репозитория, и её сервисы нельзя поднимать
на портах проекта: столкнутся с вашим постоянным стендом и друг с другом.
Номера выдаёт `ports` — единственный учёт портов машины (справка
`/var/lib/vps-dev/style/machine/ports.md`), а не движок: гадать номера тут
некому.

Наружу отдаём три действия: занять блок, поднять, погасить и вернуть блок.
Всё остальное — дело `ports` и `docker compose`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

PORTS = "ports"
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.yaml", "compose.yaml", "compose.yml")


def name_of(task) -> str:
    """Имя арендатора: `<проект>-<задача>`, например `listate-crm-t16`.

    По этому имени `ports free` находит блок, а дашборд рисует стенд внутри
    секции проекта, а не отдельной секцией рядом.
    """
    project = Path(task["project_path"]).name
    return f"{project}-{task['id'].lower()}"


def compose_file(root: Path | str) -> str | None:
    """Чем поднимать стенд. Нет файла — нечего и поднимать."""
    for name in COMPOSE_FILES:
        if (Path(root) / name).exists():
            return name
    return None


def _run(args: list[str], cwd: Path | str | None = None, timeout: float = 600.0):
    return subprocess.run(
        args, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=timeout
    )


def claim(task) -> tuple[str, str]:
    """Занять блок портов под задачу. Возвращает (имя, ошибка)."""
    name = name_of(task)
    project = Path(task["project_path"]).name
    out = _run([PORTS, "claim", "--like", project, name], timeout=60)
    if out.returncode != 0:
        # У проекта нет своего блока — берём набор портов из его compose.
        out = _run([PORTS, "claim", "--from-compose", name], cwd=task["worktree_path"], timeout=60)
    if out.returncode != 0:
        return name, (out.stdout + out.stderr).strip()[:400]
    return name, ""


def ports_of(name: str) -> dict[str, int]:
    """Порты блока: имя переменной → номер."""
    out = _run([PORTS, "env", name], timeout=30)
    if out.returncode != 0:
        return {}
    result: dict[str, int] = {}
    for line in out.stdout.splitlines():
        key, _, value = line.partition("=")
        if value.isdigit():
            result[key] = int(value)
    return result


def web_port(name: str) -> int | None:
    """Порт, на который человеку идти смотреть.

    Первый по номеру — он же `BASE_PORT`: блок раздаётся по порядку, а
    приложение в compose стоит первым сервисом. Точнее без догадок о проекте
    не скажешь, а ошибиться тут дёшево: соседние порты рядом в дашборде.
    """
    ports = {k: v for k, v in ports_of(name).items() if k != "BASE_PORT"}
    return min(ports.values()) if ports else None


def up(task, name: str) -> str:
    """Поднять стенд задачи. Пустая строка — получилось."""
    root = Path(task["worktree_path"] or "")
    file = compose_file(root)
    if not file:
        return f"в {root} нет docker-compose.yml — стенд поднимать нечем"
    out = _run(
        [PORTS, "run", name, "--", "docker", "compose", "up", "-d"], cwd=root, timeout=1800
    )
    return "" if out.returncode == 0 else (out.stdout + out.stderr).strip()[-400:]


def down(task, name: str) -> str:
    """Погасить стенд и вернуть блок.

    Гасим с `-v`: тома у стенда свои, и без этого они остаются на диске
    навсегда. Блок отдаём после остановки — `ports free` иначе откажет, и
    это правильно: отданный блок достался бы соседу вместе с контейнерами.
    """
    root = Path(task["worktree_path"] or "")
    errors = []
    if root.is_dir() and compose_file(root):
        out = _run(
            [PORTS, "run", name, "--", "docker", "compose", "down", "-v"],
            cwd=root,
            timeout=600,
        )
        if out.returncode != 0:
            errors.append((out.stdout + out.stderr).strip()[-300:])
    out = _run([PORTS, "free", name], timeout=60)
    if out.returncode != 0 and "нет закреплённого блока" not in (out.stdout + out.stderr):
        errors.append((out.stdout + out.stderr).strip()[-300:])
    return "; ".join(errors)
