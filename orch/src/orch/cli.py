"""CLI `orch`: для ролей внутри сессии и для владельца.

Роли зовут `done`, `ask`, `note`, `whoami`, `push`, `task new`. База в
сессиях не открывается (`PLAN.md` §2, правило 1): команда пишет файлы в папке
задачи и заявки в `~/.local/share/orch/inbox/`. Все тексты по-русски: их
читают роли и владелец.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from . import artifacts, signals
from .chain import DONE, ChainError, load as load_chain
from .taskdir import NotInTask, TaskDir, find_task

INBOX = Path.home() / ".local" / "share" / "orch" / "inbox"


class Refused(Exception):
    """Команда отказала роли; текст — объяснение и подсказка."""


# ── команды ролей ────────────────────────────────────────────────────────
def cmd_whoami(args: argparse.Namespace) -> int:
    task = find_task()
    print(f"задача: {task.task_id}")
    print(f"шаг: {task.step}")
    print(f"заход: {task.run}")
    print(f"рабочая копия: {task.root}")
    print(f"папка задачи: {task.path}")
    if task.current.get("session_id"):
        print(f"сессия: {task.current['session_id']}")
    step = _step_or_none(task)
    if step:
        print(f"исходы: {', '.join(step.outcomes) if not step.single_next else '(один переход)'}")
        if step.artifact:
            print("артефакт: " + ", ".join(str(task.artifacts / a) for a in step.artifact))
    reads = task.current.get("reads") or []
    if reads:
        print("файлы для чтения:")
        for item in reads:
            print(f"  {item}")
    return 0


def cmd_done(args: argparse.Namespace) -> int:
    task = find_task()
    step = _step(task)
    outcome = args.outcome

    already = signals.done_path(task.signals, task.step, task.run)
    if already.exists():
        raise Refused(
            f"ход уже сдан: {already}. Второй раз сдавать не нужно — "
            "задачу двигает владелец кнопкой."
        )

    problems: list[str] = []
    if step.single_next is not None:
        if outcome:
            problems.append(
                f"у шага {step.id} один переход и исход не называется; "
                f"вызови `orch done` без аргумента (было: {outcome!r})"
            )
        outcome = None
    else:
        if not outcome:
            problems.append(
                f"шаг {step.id} требует исход. Допустимые: {', '.join(step.outcomes)}"
            )
        elif outcome not in step.next:
            problems.append(
                f"исход {outcome!r} для шага {step.id} не существует. "
                f"Допустимые: {', '.join(step.outcomes)}"
            )

    problems += artifacts.check_all(task.artifacts, step.artifact)

    if problems:
        raise Refused("\n".join(problems))

    path = signals.write_done(task.signals, task.step, task.run, outcome)
    named = f" с исходом {outcome}" if outcome else ""
    print(f"ход сдан{named}. Сигнал: {path}")
    print("Дальше двигает движок; правки владельца после остановки вноси в свой файл.")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    task = find_task()
    signals.write_aux(task.signals, "ask", task.step, task.run, args.text)
    print("вопрос записан, задача встала и ждёт владельца")
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    task = find_task()
    signals.write_aux(task.signals, "note", task.step, task.run, args.text)
    print("комментарий записан")
    return 0


def cmd_push(args: argparse.Namespace) -> int:
    """Пушит только ветку задачи, без `--force` (`PLAN.md` §6)."""
    task = find_task()
    branch = task.current.get("branch") or _git(task.root, "rev-parse", "--abbrev-ref", "HEAD")
    if not branch or branch == "HEAD":
        raise Refused("не понял, какая ветка у задачи; пуш отменён")
    if branch in ("main", "master"):
        raise Refused(f"ветка {branch}: orch push не пушит главную ветку")
    out = subprocess.run(
        ["git", "push", "--set-upstream", "origin", branch],
        cwd=str(task.root),
        capture_output=True,
        text=True,
        timeout=300,
    )
    sys.stdout.write(out.stdout)
    sys.stderr.write(out.stderr)
    return out.returncode


# ── команды владельца и ролей: заявка на задачу ──────────────────────────
def cmd_task_new(args: argparse.Namespace) -> int:
    """Заявка в `inbox/`; движок превращает её в задачу на следующем проходе."""
    project = Path(args.project).resolve() if args.project else _project_here()
    if not (project / ".git").exists():
        raise Refused(f"{project} — не корень репозитория")
    text = args.text.strip()
    if not text:
        raise Refused("текст задачи пуст")
    sheet_edits = {}
    for item in args.after or []:
        key, _, value = item.partition("=")
        sheet_edits[f"{key}.after"] = _flag(value)
    for item in args.ask or []:
        key, _, value = item.partition("=")
        sheet_edits[f"{key}.ask"] = _flag(value)
    request = {
        "id": uuid.uuid4().hex[:12],
        "chain": args.chain,
        "project_path": str(project),
        "text": text,
        "preset": args.preset,
        "sheet_edits": sheet_edits,
        "backlog": bool(args.backlog),
        "at": signals.now(),
    }
    INBOX.mkdir(parents=True, exist_ok=True)
    path = INBOX / f"{request['id']}.json"
    path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    where = "в бэклог" if args.backlog else "в очередь"
    print(f"заявка {where}: {path}")
    return 0


# ── вспомогательное ──────────────────────────────────────────────────────
def _flag(value: str) -> bool:
    v = value.strip().lower()
    if v in ("on", "true", "yes", "да", "1"):
        return True
    if v in ("off", "false", "no", "нет", "0"):
        return False
    raise Refused(f"значение {value!r}: ожидалось on или off")


def _step(task: TaskDir):
    step = _step_or_none(task)
    if step is None:
        raise Refused(
            f"в {task.chain_yaml} нет шага {task.step!r}; "
            "папка задачи рассинхронизирована с цепочкой"
        )
    return step


def _step_or_none(task: TaskDir):
    try:
        chain = load_chain(task.chain_yaml)
    except ChainError:
        return None
    try:
        return chain.step(task.step)
    except ChainError:
        return None


def _git(root: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True, timeout=30
    )
    return out.stdout.strip()


def _project_here() -> Path:
    from .taskdir import git_toplevel

    root = git_toplevel()
    if root is None:
        raise Refused("не понял, какой это проект: вызови с --project <корень>")
    return root


def _refusal_tail(task: TaskDir) -> str:
    """После второго отказа за заход команда велит остановиться (`PLAN.md` §6)."""
    n = signals.count(task.signals, "refused", task.step, task.run)
    if n < 2:
        return ""
    return (
        "\n\nДальше не повторяй: запиши в `## Не решено`, чего не хватает, "
        "и закончи ход без сигнала. Владелец увидит причину."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orch", description="оркестратор ролей")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("whoami", help="задача, шаг, заход, файлы")
    p.set_defaults(func=cmd_whoami)

    p = sub.add_parser("done", help="закончить ход (последнее действие роли)")
    p.add_argument("outcome", nargs="?", help="исход шага; у шага с одним переходом не нужен")
    p.set_defaults(func=cmd_done)

    p = sub.add_parser("ask", help="запасной канал вопроса владельцу")
    p.add_argument("text")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("note", help="запасной канал комментария")
    p.add_argument("text")
    p.set_defaults(func=cmd_note)

    p = sub.add_parser("push", help="запушить ветку задачи")
    p.set_defaults(func=cmd_push)

    p_task = sub.add_parser("task", help="задачи")
    task_sub = p_task.add_subparsers(dest="task_command", required=True)

    p = task_sub.add_parser("new", help="заявка на новую задачу")
    p.add_argument("text")
    p.add_argument("--chain", default="deep")
    p.add_argument("--project")
    p.add_argument("--preset")
    p.add_argument("--after", action="append", metavar="ШАГ=on|off")
    p.add_argument("--ask", action="append", metavar="ШАГ=on|off")
    p.add_argument("--backlog", action="store_true")
    p.set_defaults(func=cmd_task_new)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except NotInTask as exc:
        print(f"orch: {exc}", file=sys.stderr)
        return 1
    except Refused as exc:
        tail = ""
        try:
            task = find_task()
            signals.write_aux(task.signals, "refused", task.step, task.run, str(exc))
            tail = _refusal_tail(task)
        except (NotInTask, OSError):
            pass
        print(f"orch: {exc}{tail}", file=sys.stderr)
        return 1
    except ChainError as exc:
        print(f"orch: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
