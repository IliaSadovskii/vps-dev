#!/usr/bin/env python3
"""Спайк 6. Пропускает ли режим «только чтение» (`mode: plan`) команду
`orch done`.

Решает `RISKS.md` п. 12: если в plan-режиме роль может записать файл сигнала —
режим можно вернуть в цепочки; если нет — `mode: plan` остаётся отклонённым
линтером, а сдача хода в таком режиме потребует отдельного канала.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from _common import (  # noqa: E402
    archive,
    call,
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

BRANCH = "t0-spike6"
TASK = "T0P"
CHAIN = Path(__file__).resolve().parents[1] / "chains" / "smoke.yml"

ASK = (
    "В папке задачи `.orch/T0P/artifacts/` уже лежит файл `one.md`. "
    "Единственное, что нужно сделать: выполнить в терминале команду "
    "`orch done` из корня рабочей копии и показать её вывод дословно. "
    "Ничего не правь и не создавай."
)


def run() -> int:
    lines: list[str] = []
    sid = None
    try:
        s = create(
            tool="claude",
            agent_name="claude",
            agent_model="sonnet",
            title="orch spike6 plan",
            worktree_enabled=True,
            worktree_branch=BRANCH,
            create_new_branch=True,
            yolo_mode=False,
            idempotency_key="spike6/main",
        )
        sid = s["id"]
        root = s["project_path"]
        lines.append(f"сессия {sid}, копия {root}")

        path = write_task_dir(
            root,
            TASK,
            {"task": TASK, "step": "one", "run": 1, "session_id": sid, "state": "running"},
        )
        shutil.copy(CHAIN, path / "chain.yml")
        (path / "artifacts" / "one.md").write_text(
            "## Итог\nфайл заготовлен спайком\n", encoding="utf-8"
        )

        mode = call("POST", f"/api/sessions/{sid}/acp/mode", {"mode_id": "plan"})
        lines.append(f"режим plan выставлен: {mode if mode else 'ok'}")

        sent = now_iso()
        disp = prompt(sid, ASK)
        status = wait_turn(sid, sent, timeout=420, poll=3)
        lines.append(f"промпт {disp}, статус после хода {status}")

        signal = path / "signals" / "one-1.json"
        wrote = signal.exists()
        text = replay_text(sid, limit=300)
        lines.append(f"сигнал {signal} записан: {wrote}")
        if not wrote:
            tail = text[-600:].replace("\n", " ")
            lines.append(f"хвост транскрипта: {tail}")
        lines.append(
            "вывод: mode plan можно вернуть в цепочки"
            if wrote
            else "вывод: mode plan остаётся отклонённым линтером (RISKS.md п. 12)"
        )
        # Проверка информативна в обе стороны: ok = ответ получен.
        return report("6 (mode plan и orch done)", True, lines)
    finally:
        if sid:
            archive(sid)
        drop_branch(BRANCH)


if __name__ == "__main__":
    main_guard(run)
