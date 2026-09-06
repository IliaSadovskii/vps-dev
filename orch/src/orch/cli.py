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
from .chain import ChainError, load as load_chain
from .taskdir import NotInTask, TaskDir, find_task

INBOX = Path.home() / ".local" / "share" / "orch" / "inbox"
DB_PATH = Path.home() / ".local" / "share" / "orch" / "orch.db"


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
        "branch": args.branch,
        "base": args.base,
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


# ── команды владельца: чтение базы ───────────────────────────────────────
def _ro_db():
    """База только на чтение: единственный писатель — движок."""
    import sqlite3

    if not DB_PATH.exists():
        raise Refused(f"базы нет: {DB_PATH}. Движок ещё ни разу не запускался?")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_task_list(args: argparse.Namespace) -> int:
    conn = _ro_db()
    rows = list(conn.execute("SELECT * FROM task ORDER BY status, created_at"))
    if not rows:
        print("задач нет")
        return 0
    for row in rows:
        wait = f" — {row['wait_reason']}" if row["wait_reason"] else ""
        step = row["step"] or "—"
        print(f"{row['id']:>5}  {row['status']:<9} {step:<16} {row['title']}{wait}")
    return 0


def cmd_task_show(args: argparse.Namespace) -> int:
    conn = _ro_db()
    row = conn.execute("SELECT * FROM task WHERE id = ?", (args.task,)).fetchone()
    if row is None:
        raise Refused(f"нет задачи {args.task}")
    print(f"{row['id']}  {row['title']}")
    print(f"цепочка: {row['chain']}   статус: {row['status']}   шаг: {row['step'] or '—'}")
    if row["wait_reason"]:
        print(f"ждёт: {row['wait_reason']}")
    print(f"проект: {row['project_path']}")
    print(f"копия:  {row['worktree_path'] or '—'}   ветка: {row['branch'] or '—'}")
    print(f"ревизия: {row['revision']}")
    print("\nлист автономии:")
    for step, knobs in json.loads(row["human_sheet"]).items():
        print(f"  {step:<18} ворота {knobs.get('after')!s:<12} вопросы {knobs.get('ask')}")
    print("\nзаходы:")
    for run in conn.execute(
        "SELECT * FROM run WHERE task_id = ? ORDER BY id", (args.task,)
    ):
        outcome = run["outcome"]
        if not outcome:
            if not run["ended_at"]:
                outcome = "идёт"
            else:
                outcome = "сдан" if run["signalled"] else "нет сигнала"
        cost = f"  ${run['cost_usd']:.2f}" if run["cost_usd"] else ""
        dur = f"  {run['duration_s']:.0f} с" if run["duration_s"] else ""
        print(f"  {run['step']:<18} заход {run['n']}  {outcome}{dur}{cost}")
    print("\nдвижения:")
    for move in list(conn.execute(
        "SELECT * FROM move WHERE task_id = ? ORDER BY id DESC LIMIT 10", (args.task,)
    ))[::-1]:
        comment = f'  «{move["comment"]}»' if move["comment"] else ""
        print(
            f"  {move['at']}  {move['from_step'] or '—'} → {move['to_step'] or '—'}"
            f"  {move['actor']}/{move['trigger']}{comment}"
        )
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    conn = _ro_db()
    seen = 0

    def show(limit: int, after: int) -> int:
        nonlocal seen
        sql = "SELECT * FROM event WHERE seq > ?"
        params: list = [after]
        if args.task:
            sql += " AND task_id = ?"
            params.append(args.task)
        sql += " ORDER BY seq LIMIT ?"
        params.append(limit)
        last = after
        for row in conn.execute(sql, params):
            payload = row["payload"] or "{}"
            if payload == "{}":
                payload = ""
            print(f"{row['at']}  {row['task_id'] or '—':<5} {row['kind']:<20} {payload}")
            last = row["seq"]
        return last

    start = conn.execute("SELECT COALESCE(MAX(seq),0) - ? m FROM event", (args.tail,)).fetchone()["m"]
    seen = show(args.tail, max(0, start))
    if not args.follow:
        return 0
    try:
        while True:
            time.sleep(2)
            seen = show(200, seen) or seen
    except KeyboardInterrupt:
        return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """По шагам: заходов на задачу, доля «нет сигнала», медиана хода, вопросы."""
    conn = _ro_db()
    tasks = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM task ORDER BY created_at DESC LIMIT ?", (args.last,)
        )
    ]
    if not tasks:
        print("задач нет")
        return 0
    marks = ",".join("?" * len(tasks))
    rows = list(conn.execute(f"SELECT * FROM run WHERE task_id IN ({marks})", tasks))
    by_step: dict[str, list] = {}
    for run in rows:
        by_step.setdefault(run["step"], []).append(run)
    asks = {}
    for row in conn.execute(
        f"SELECT task_id, payload FROM event WHERE kind = 'stopped' AND task_id IN ({marks})",
        tasks,
    ):
        if '"ask"' in (row["payload"] or ""):
            asks[row["task_id"]] = asks.get(row["task_id"], 0) + 1

    print(f"{'шаг':<18} {'заходов/задачу':>15} {'нет сигнала':>12} {'медиана хода':>14}")
    for step, runs in sorted(by_step.items()):
        with_task = len({r["task_id"] for r in runs})
        per_task = len(runs) / max(1, with_task)
        silent = sum(1 for r in runs if r["ended_at"] and not r["signalled"])
        share = silent / max(1, len(runs))
        durations = sorted(r["duration_s"] for r in runs if r["duration_s"])
        median = durations[len(durations) // 2] if durations else 0
        print(f"{step:<18} {per_task:>15.1f} {share:>11.0%} {median:>13.0f}с")
    print(f"\nвопросов владельцу: {sum(asks.values())} на {len(tasks)} задач")
    return 0


def cmd_task_move(args: argparse.Namespace) -> int:
    """Кнопка из терминала. Заявка в `inbox/`: писатель базы один — движок."""
    conn = _ro_db()
    row = conn.execute("SELECT revision FROM task WHERE id = ?", (args.task,)).fetchone()
    if row is None:
        raise Refused(f"нет задачи {args.task}")
    request = {
        "id": uuid.uuid4().hex[:12],
        "kind": "button",
        "task": args.task,
        "revision": row["revision"],
        "action": args.action,
        "target": args.target,
        "comment": args.comment,
        "at": signals.now(),
    }
    INBOX.mkdir(parents=True, exist_ok=True)
    path = INBOX / f"{request['id']}.json"
    path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"кнопка «{args.action}» поставлена в очередь движку: {path}")
    return 0


def cmd_inbox(args: argparse.Namespace) -> int:
    """Завести сессию Inbox проекта: заявка движку."""
    project = Path(args.project).resolve()
    request = {
        "id": uuid.uuid4().hex[:12],
        "kind": "inbox_session",
        "project_path": str(project),
        "at": signals.now(),
    }
    INBOX.mkdir(parents=True, exist_ok=True)
    (INBOX / f"{request['id']}.json").write_text(
        json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"сессия Inbox для {project} будет создана на следующем проходе")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Что должно работать, чтобы движок ехал."""
    import shutil
    import urllib.error
    import urllib.request

    ok = True

    def check(name: str, good: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and good
        print(f"  {'ok  ' if good else 'ПЛОХО'} {name}{'  ' + detail if detail else ''}")

    print("orch doctor:")
    check("база", DB_PATH.exists(), str(DB_PATH))
    check("inbox", INBOX.parent.is_dir(), str(INBOX))
    for name in ("orch", "orch-plugin"):
        path = shutil.which(name, path="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/snap/bin")
        check(f"{name} в PATH демона", bool(path), path or "нет симлинка в /usr/local/bin")
    try:
        with urllib.request.urlopen("http://127.0.0.1:8065/api/sessions?state=live", timeout=5) as r:
            live = len(json.loads(r.read().decode()).get("sessions", []))
        check("демон AoE", True, f"живых сессий {live}")
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        check("демон AoE", False, str(exc))
    from .chain import chains_dir

    for path in sorted(chains_dir().glob("*.yml")):
        try:
            load_chain(path)
            check(f"цепочка {path.stem}", True)
        except ChainError as exc:
            check(f"цепочка {path.stem}", False, str(exc))
    return 0 if ok else 1


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

    p = task_sub.add_parser("list", help="все задачи одной строкой")
    p.set_defaults(func=cmd_task_list)

    p = task_sub.add_parser("show", help="задача целиком: заходы, движения, лист")
    p.add_argument("task")
    p.set_defaults(func=cmd_task_show)

    p = task_sub.add_parser("move", help="нажать кнопку из терминала")
    p.add_argument("task")
    p.add_argument("action", choices=["accept", "back", "again", "start"])
    p.add_argument("--target", help="шаг для accept/back")
    p.add_argument("--comment", help="комментарий владельца адресату")
    p.set_defaults(func=cmd_task_move)

    p = task_sub.add_parser("new", help="заявка на новую задачу")
    p.add_argument("text")
    p.add_argument("--chain", default="deep")
    p.add_argument("--project")
    p.add_argument("--preset")
    p.add_argument("--after", action="append", metavar="ШАГ=on|off")
    p.add_argument("--ask", action="append", metavar="ШАГ=on|off")
    p.add_argument("--backlog", action="store_true")
    p.add_argument(
        "--branch",
        help="работать в этой ветке вместо новой: так задача садится на уже открытый PR",
    )
    p.add_argument(
        "--base",
        help="от чего ответвляться, если ветки ещё нет (по умолчанию origin/HEAD)",
    )
    p.set_defaults(func=cmd_task_new)

    p = sub.add_parser("log", help="журнал событий")
    p.add_argument("task", nargs="?")
    p.add_argument("--follow", action="store_true")
    p.add_argument("--tail", type=int, default=20)
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("stats", help="качество промптов по шагам")
    p.add_argument("--last", type=int, default=20)
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("inbox", help="сессия Inbox проекта")
    p.add_argument("project")
    p.set_defaults(func=cmd_inbox)

    p = sub.add_parser("doctor", help="проверить окружение")
    p.set_defaults(func=cmd_doctor)

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
