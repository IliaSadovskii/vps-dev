#!/usr/bin/env python3
"""Прогон всех проверок спайка. Каждая печатает `ok` или `FAIL`.

    python3 orch/spike/run_all.py            # 1,2,3,4,6 и финал 5, если он начат
    python3 orch/spike/run_all.py --start-5  # задать вопрос спайка 5 и выйти

Проверка 5 разнесена во времени: вопрос висит, пока идут остальные, потом
`check5_question_waits.py` отвечает на него и проверяет, что ход продолжился.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKS = [
    ("1", "check1_orch_in_session.py", []),
    ("2", "check2_status_and_prompt.py", []),
    ("3", "check3_two_sessions_one_worktree.py", []),
    ("4", "check4_plugin_pane.py", []),
    ("5", "check5_question_waits.py", []),
    ("6", "check6_plan_mode.py", []),
]


def run(script: str, args: list[str]) -> tuple[int, str]:
    out = subprocess.run(
        [sys.executable, str(HERE / script), *args],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    return out.returncode, out.stdout + out.stderr


def main() -> int:
    if "--start-5" in sys.argv:
        code, text = run("check5_question_waits.py", ["--start"])
        print(text)
        return code
    only = [a for a in sys.argv[1:] if a.isdigit()]
    results = []
    for num, script, args in CHECKS:
        if only and num not in only:
            continue
        code, text = run(script, args)
        print(text.rstrip())
        results.append((num, code == 0))
    print("\n--- итог спайка ---")
    for num, ok in results:
        print(f"  проверка {num}: {'ok' if ok else 'FAIL'}")
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())
