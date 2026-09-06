"""Сигналы роли: файлы в `.orch/<task>/signals/`.

Единственный канал «роль → движок» (`research/RISKS.md` п. 1). Пишет их
команда `orch` из сессии; читает движок и только когда ход закончился, чтобы
роль, вызвавшая `orch done` и продолжившая править файлы, ничего не сломала.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

KINDS = ("done", "ask", "note", "refused")


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def done_path(signals: Path, step: str, run: int) -> Path:
    return signals / f"{step}-{run}.json"


def write(signals: Path, payload: dict, path: Path) -> Path:
    """Атомарная запись: временный файл рядом и переименование."""
    signals.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(signals), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def write_done(signals: Path, step: str, run: int, outcome: str | None) -> Path:
    return write(
        signals,
        {"kind": "done", "outcome": outcome, "step": step, "run": run, "at": now()},
        done_path(signals, step, run),
    )


def write_aux(signals: Path, kind: str, step: str, run: int, text: str) -> Path:
    """Сигнал, которых за заход может быть несколько: ask, note, refused."""
    n = 1 + count(signals, kind, step, run)
    path = signals / f"{step}-{run}-{kind}-{n}.json"
    return write(
        signals,
        {"kind": kind, "text": text, "step": step, "run": run, "at": now()},
        path,
    )


def count(signals: Path, kind: str, step: str, run: int) -> int:
    if not signals.is_dir():
        return 0
    return len(list(signals.glob(f"{step}-{run}-{kind}-*.json")))


def read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def latest(signals: Path, step: str, run: int, kinds: tuple[str, ...] = KINDS) -> dict | None:
    """Последний по времени сигнал захода — для строки «ответ orch» в панели."""
    if not signals.is_dir():
        return None
    best: dict | None = None
    for path in signals.glob(f"{step}-{run}*.json"):
        data = read(path)
        if not data or data.get("kind") not in kinds:
            continue
        if best is None or data.get("at", "") >= best.get("at", ""):
            best = data
    return best
