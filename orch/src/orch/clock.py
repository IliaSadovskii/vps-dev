"""Время в одном месте: запись и чтение отметок.

Мы пишем UTC как `2026-09-06T12:00:00Z`; AoE отдаёт RFC3339 с долями секунды
и `+00:00`. Сравнивать такие строки как текст нельзя — только числами, через
`epoch`. Отметки, от которых зависит порядок событий внутри секунды
(`run.prompt_sent_at`), пишутся с долями: `now_precise`.
"""

from __future__ import annotations

import datetime
import time


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def now_precise() -> str:
    """Та же отметка, но с долями секунды.

    Конец хода сессии определяется как «вошла в Idle позже отправки промпта»
    (`aoe.Session.turn_ended`). Если промпт-подталкивание ушло в ту же
    секунду, в которой сессия уже стояла в Idle, отметка без долей делает
    старый Idle «новым», и заход закрывается как «нет сигнала», пока роль
    работает. Доли секунды это снимают.
    """
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def epoch(value: str | None) -> float | None:
    """RFC3339 в секунды эпохи. `...Z`, `+00:00` и доли секунды — всё одно.

    `time.mktime` тут неверен: он считает строку местным временем.
    """
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None
