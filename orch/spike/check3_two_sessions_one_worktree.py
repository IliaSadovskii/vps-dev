#!/usr/bin/env python3
"""Спайк 3. Две сессии на одной ветке работают в одном каталоге.

Закрывает `RISKS.md` п. 6: первая сессия задачи создаёт worktree
(`create_new_branch: true`), следующие подключаются (`create_new_branch:
false`) и получают тот же `project_path`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from _common import (  # noqa: E402
    archive,
    key,
    create,
    drop_branch,
    main_guard,
    now_iso,
    prompt,
    replay_text,
    report,
    wait_turn,
)

BRANCH = "t0-spike3"


def run() -> int:
    lines: list[str] = []
    ids = []
    try:
        a = create(
            tool="claude",
            agent_name="claude",
            agent_model="haiku",
            title="orch spike3 первая",
            worktree_enabled=True,
            worktree_branch=BRANCH,
            create_new_branch=True,
            idempotency_key=key("spike3/a"),
        )
        ids.append(a["id"])
        b = create(
            tool="claude",
            agent_name="claude",
            agent_model="haiku",
            title="orch spike3 вторая",
            worktree_enabled=True,
            worktree_branch=BRANCH,
            create_new_branch=False,
            idempotency_key=key("spike3/b"),
        )
        ids.append(b["id"])
        pa, pb = a.get("project_path"), b.get("project_path")
        lines.append(f"первая {a['id']}: {pa}")
        lines.append(f"вторая {b['id']}: {pb}")
        same = bool(pa) and pa == pb
        lines.append(f"один каталог: {same}")

        # третий агент того же каталога (codex) — та же ветка
        c = create(
            tool="codex",
            agent_name="codex",
            agent_model="gpt-5.6-sol",
            title="orch spike3 codex",
            worktree_enabled=True,
            worktree_branch=BRANCH,
            create_new_branch=False,
            idempotency_key=key("spike3/c"),
        )
        ids.append(c["id"])
        pc = c.get("project_path")
        lines.append(f"codex {c['id']}: {pc}")
        same = same and pc == pa

        # файл, написанный первой сессией, виден второй
        marker = "spike3-shared-file"
        sent = now_iso()
        prompt(ids[0], f"Создай файл {marker}.txt со строкой ПРИВЕТ. Ничего не коммить.")
        wait_turn(ids[0], sent, timeout=300, poll=2)
        exists = (Path(pa) / f"{marker}.txt").exists() if pa else False
        lines.append(f"файл первой сессии на диске: {exists}")

        sent = now_iso()
        prompt(ids[1], f"Выведи содержимое файла {marker}.txt дословно, ничего не меняя.")
        wait_turn(ids[1], sent, timeout=300, poll=2)
        seen = "ПРИВЕТ" in replay_text(ids[1])
        lines.append(f"вторая сессия видит файл: {seen}")

        ok = same and exists and seen
        return report("3 (две сессии — один каталог)", ok, lines)
    finally:
        for sid in ids:
            archive(sid)
        drop_branch(BRANCH)


if __name__ == "__main__":
    main_guard(run)
