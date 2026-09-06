#!/usr/bin/env python3
"""Спайк 1. `orch` из PATH запускается ролью Claude и ролью Codex в рабочей
копии и находит задачу по каталогу.

Проверяет главное решение `RISKS.md` п. 1: канал «роль → движок» — файл, а
идентификация задачи — по корню рабочей копии, не по окружению.
"""

from __future__ import annotations

import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from _common import (  # noqa: E402
    archive,
    create,
    drop_branch,
    main_guard,
    now_iso,
    prompt,
    replay_text,
    report,
    wait_turn,
    write_task_dir,
)

TASK = "T0"
MARK = "spike1-marker"

ASK = (
    "Запусти в терминале команду `orch whoami` и выведи её вывод дословно "
    "последним сообщением. Ничего не создавай, не правь и не коммить."
)


def one(agent: str, model: str, branch: str) -> tuple[bool, list[str]]:
    lines = []
    sid = None
    try:
        s = create(
            tool=agent,
            agent_name=agent,
            agent_model=model,
            title=f"orch spike1 {agent}",
            worktree_enabled=True,
            worktree_branch=branch,
            create_new_branch=True,
            idempotency_key=f"spike1/{agent}",
        )
        sid = s["id"]
        root = s.get("project_path")
        lines.append(f"{agent}: сессия {sid}, копия {root}, статус {s.get('status')}")
        if not root:
            return False, lines + [f"{agent}: нет project_path в ответе создания"]

        write_task_dir(
            root,
            TASK,
            {
                "task": TASK,
                "step": "spike",
                "run": 1,
                "session_id": sid,
                "state": "running",
                "reads": [f"{MARK}"],
            },
        )
        sent_at = now_iso()
        disp = prompt(sid, ASK)
        lines.append(f"{agent}: промпт {disp}")
        status = wait_turn(sid, sent_at, timeout=420)
        lines.append(f"{agent}: статус после хода {status}")
        text = replay_text(sid)
        got_task = f"задача: {TASK}" in text
        got_step = "шаг: spike" in text
        got_mark = MARK in text
        lines.append(
            f"{agent}: в транскрипте задача={got_task} шаг={got_step} reads={got_mark}"
        )
        return (got_task and got_step and got_mark), lines
    finally:
        if sid:
            archive(sid)


def run() -> int:
    ok_all = True
    lines: list[str] = []
    for agent, model, branch in (
        ("claude", "sonnet", "t0-spike1-claude"),
        ("codex", "gpt-5.6-sol", "t0-spike1-codex"),
    ):
        ok, out = one(agent, model, branch)
        ok_all = ok_all and ok
        lines += out
        drop_branch(branch)
    return report("1 (orch в сессии, claude и codex)", ok_all, lines)


if __name__ == "__main__":
    main_guard(run)
