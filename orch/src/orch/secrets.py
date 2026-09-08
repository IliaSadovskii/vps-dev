"""Секреты машины: токен бота и привязанные чаты.

Лежат рядом с базой, а не в репозитории и не в настройках плагина: токен
даёт право нажимать кнопки задач, и его место — файл с правами `0600`
(`ASIDE-PLAN.md` §12).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .db import STATE_DIR

# Свой каталог, а не файл рядом с базой: странице настроек песочница
# systemd открывает на запись именно каталоги, а всю папку состояния ей
# отдавать нельзя — там база, и писатель у неё один (`PLAN.md` §2).
PATH = STATE_DIR / "secrets" / "secrets.json"


def read() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write(data: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    # Не `with_suffix`: он заменил бы `.json` на `.tmp` и вынес файл из-под
    # имени, на которое выдано разрешение.
    tmp = PATH.parent / (PATH.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(PATH)


def telegram() -> dict:
    return read().get("telegram") or {}


def set_telegram(**fields) -> dict:
    data = read()
    block = data.get("telegram") or {}
    block.update(fields)
    data["telegram"] = block
    write(data)
    return block


def forget_telegram() -> None:
    data = read()
    data.pop("telegram", None)
    write(data)
