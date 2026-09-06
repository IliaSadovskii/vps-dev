#!/usr/bin/env python3
"""Спайк 5. Вопрос `AskUserQuestion` висит, пока на него не ответят; ответ
через `POST /acp/elicitations/{nonce}` принимается и ход продолжается.

Закрывает `RISKS.md` п. 9 (автономный режим и вопросы) и подтверждает, что
движку не нужен таймер на человека (`PLAN.md` §2, правило 6).

Два режима, чтобы не держать прогон часами:
  `--start`  создать сессию, задать вопрос, дождаться `Waiting`;
  `--finish` проверить, что она всё ещё `Waiting` спустя время, ответить и
             дождаться конца хода.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from _common import (  # noqa: E402
    archive,
    key,
    call,
    create,
    drop_branch,
    main_guard,
    now_iso,
    prompt,
    replay_text,
    report,
    session,
    wait_turn,
)

BRANCH = "t0-spike5"
STATE = Path("/tmp/orch-spike5.json")
MARK = "СПАЙК5-ПРОДОЛЖИЛ"

ASK = (
    "Задай мне вопрос инструментом AskUserQuestion: «Какой цвет взять?» с "
    "вариантами «красный» и «синий». Дождись ответа. Как только получишь ответ, "
    f"ответь одной строкой: {MARK} <выбранный цвет>. Ничего не создавай и не правь."
)


def find_elicitation(sid: str) -> dict | None:
    """Найти висящий вопрос в сыром транскрипте: нужен nonce и ключи формы.

    Сырые события лежат под ключом `frames` (не `rows` и не `events`), а
    сам вопрос — в `event.ElicitationRequested.elicitation`.
    """
    data = call("GET", f"/api/sessions/{sid}/acp/replay?view=raw&limit=200")
    frames = data.get("frames", []) if isinstance(data, dict) else data
    pending = None
    for frame in frames:
        event = frame.get("event") or {}
        if "ElicitationRequested" in event:
            pending = event["ElicitationRequested"]["elicitation"]
        elif "ElicitationResolved" in event:
            pending = None
    return pending


def start() -> int:
    s = create(
        tool="claude",
        agent_name="claude",
        agent_model="sonnet",
        title="orch spike5 вопрос",
        worktree_enabled=True,
        worktree_branch=BRANCH,
        create_new_branch=True,
        idempotency_key=key("spike5/main"),
    )
    sid = s["id"]
    sent = now_iso()
    disp = prompt(sid, ASK)
    status = wait_turn(sid, sent, timeout=300, poll=3)
    STATE.write_text(
        json.dumps({"session": sid, "asked_at": time.time(), "sent": sent}),
        encoding="utf-8",
    )
    lines = [
        f"сессия {sid}, промпт {disp}",
        f"статус после хода: {status} (ожидается Waiting — висит вопрос)",
    ]
    return report("5 старт (вопрос задан)", status == "Waiting", lines)


def finish(min_wait_s: float = 600.0) -> int:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    sid = state["session"]
    lines: list[str] = []
    ok = True
    try:
        waited = time.time() - state["asked_at"]
        s = session(sid) or {}
        lines.append(f"провисел {waited / 60:.0f} мин, статус {s.get('status')}")
        still = s.get("status") == "Waiting"
        lines.append(f"вопрос никем не погашен: {still}")
        ok = ok and still and waited >= min_wait_s

        ev = find_elicitation(sid)
        if not ev:
            lines.append("не нашёл nonce вопроса в сыром транскрипте")
            return report("5 (вопрос ждёт, ответ через API)", False, lines)
        nonce = ev.get("nonce")
        questions = ev.get("questions") or []
        lines.append(
            f"nonce {nonce}, вопрос «{ev.get('message')}», "
            f"поля {[q.get('field_key') for q in questions]}"
        )
        answers = {}
        for q in questions:
            if q.get("kind") == "free_text":
                continue          # свободные поля оставляем пустыми
            options = q.get("options") or []
            if options:
                answers[q["field_key"]] = options[0]["value"]
        sent = now_iso()
        resp = call(
            "POST",
            f"/api/sessions/{sid}/acp/elicitations/{nonce}",
            {"action": "accept", "answers": answers},
        )
        lines.append(f"ответ принят: {resp if resp else '204'}")
        status = wait_turn(sid, sent, timeout=300, poll=3)
        went_on = status == "Idle" and MARK in replay_text(sid, limit=400)
        lines.append(f"ход продолжился после ответа: {went_on} (статус {status})")
        ok = ok and went_on
        return report("5 (вопрос ждёт, ответ через API)", ok, lines)
    finally:
        archive(sid)
        drop_branch(BRANCH)


def _dig(obj, key: str):
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], str):
            return obj[key]
        for v in obj.values():
            got = _dig(v, key)
            if got:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = _dig(v, key)
            if got:
                return got
    return None


def _form_keys(obj) -> list[str]:
    """Ключи формы вопроса: адаптер называет их `question_0..N`."""
    found: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k.startswith("question_") and not k.endswith("_custom"):
                    found.append(k)
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(obj)
    return sorted(set(found))


def run() -> int:
    if "--start" in sys.argv:
        return start()
    wait = 600.0
    for arg in sys.argv[1:]:
        if arg.startswith("--min-wait="):
            wait = float(arg.split("=", 1)[1])
    return finish(wait)


if __name__ == "__main__":
    main_guard(run)
