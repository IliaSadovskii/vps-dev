#!/usr/bin/env python3
"""Спайк 2. Конец хода виден в `GET /api/sessions`; промпт доставляется и в
`Idle`, и в сессию без живого воркера.

Закрывает `RISKS.md` п. 2 (опрос вместо WebSocket) и п. 4 (восстановление:
«нет воркера → послать промпт, он будит»).
"""

from __future__ import annotations

import sys
import time

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

BRANCH = "t0-spike2"


def run() -> int:
    lines: list[str] = []
    ok = True
    sid = None
    try:
        s = create(
            tool="claude",
            agent_name="claude",
            agent_model="haiku",
            title="orch spike2",
            worktree_enabled=True,
            worktree_branch=BRANCH,
            create_new_branch=True,
            idempotency_key=key("spike2/main"),
        )
        sid = s["id"]
        lines.append(f"создана {sid}, статус {s.get('status')}, копия {s.get('project_path')}")

        # (а) обычный ход: конец хода виден в списке сессий
        sent = now_iso()
        t0 = time.time()
        disp = prompt(sid, "Ответь одним словом: ЕДИНИЦА. Ничего не делай больше.")
        st = wait_turn(sid, sent, timeout=300, poll=2)
        lines.append(f"а) промпт {disp}, конец хода {st} за {time.time() - t0:.0f} с")
        first_ok = st == "Idle" and "ЕДИНИЦА" in replay_text(sid)
        lines.append(f"а) ответ в транскрипте: {first_ok}")
        ok = ok and first_ok

        # (б) промпт в Idle-сессию
        sent = now_iso()
        disp2 = prompt(sid, "Ответь одним словом: ДВОЙКА.")
        st2 = wait_turn(sid, sent, timeout=300, poll=2)
        second_ok = st2 == "Idle" and "ДВОЙКА" in replay_text(sid)
        lines.append(f"б) промпт в Idle: {disp2}, статус {st2}, ответ {second_ok}")
        ok = ok and second_ok

        # (в) промпт в сессию без живого воркера
        call("POST", f"/api/sessions/{sid}/stop", {})
        time.sleep(3)
        before = session(sid) or {}
        lines.append(
            f"в) после stop: статус {before.get('status')}, "
            f"воркер {before.get('acp_worker_state')}, dormant {before.get('dormant')}"
        )
        sent = now_iso()
        try:
            disp3 = prompt(sid, "Ответь одним словом: ТРОЙКА.")
        except Exception as exc:  # noqa: BLE001
            disp3 = {"error": str(exc)}
        st3 = wait_turn(sid, sent, timeout=300, poll=2)
        third_ok = "ТРОЙКА" in replay_text(sid)
        lines.append(f"в) промпт без воркера: {disp3}, статус {st3}, ответ {third_ok}")
        ok = ok and third_ok
        return report("2 (статус хода и доставка промпта)", ok, lines)
    finally:
        if sid:
            archive(sid)
        drop_branch(BRANCH)


if __name__ == "__main__":
    main_guard(run)
