"""CLI `orch`: для ролей внутри сессии и для владельца.

Роли зовут `done`, `note`, `whoami`, `push`, `task new`. База в
сессиях не открывается (`PLAN.md` §2, правило 1): команда пишет файлы в папке
задачи и заявки в `~/.local/share/orch/inbox/`. Все тексты по-русски: их
читают роли и владелец.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from . import artifacts, signals
from .aoe import hooks_dir
from .chain import (
    ChainError,
    catalog,
    chains_dir,
    load as load_chain,
    names as chain_names,
    path_of as chain_path,
)
from .branchref import recent
from .db import DB_PATH, INBOX
from .taskdir import NotInTask, TaskDir, find_task, git_toplevel
from .workspace import remove_worktree


class Refused(Exception):
    """Команда отказала роли; текст — объяснение и подсказка."""


def _refuse_if_agent(what: str) -> None:
    """Кнопки владельца — не роли. `AOE_ARTIFACT_DIR` ставит сам общий ACP-раннер
    AoE (`runner.rs`) в среду процесса при запуске — один на все провайдеры
    (Claude, Codex, OpenCode), не только Claude Code: `CLAUDECODE` для
    мультипровайдерного оркестратора не годится, он значащий только у Claude.
    `AOE_INSTANCE_ID` тоже не подходит — он живёт в среде tmux-панели, а не в
    среде самого агента (проверено на собственном окружении). Голый терминал
    владельца на машине ни одну из переменных AoE не несёт; панель ходит в
    движок напрямую и этой проверки вообще не видит (T26, 2026-09-09 — роль
    сама вызвала `orch gate back`, приняв пересказ требования владельца за
    согласие на переход)."""
    if os.environ.get("AOE_ARTIFACT_DIR"):
        raise Refused(
            f"{what} — решение владельца, не роли: нажмите кнопку в панели "
            "или наберите команду в своём терминале, не в среде агента."
        )


# ── команды ролей ────────────────────────────────────────────────────────
# Глаголы, которыми побочная роль может предложить владельцу решение:
# движок обязан уметь исполнить каждый (`ASIDE-PLAN.md` §4).
VERBS = {"continue", "restart", "back", "back_clean", "say", "stop", "patch"}


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
    # Роль дословно пересказывала владельцу эту строку («ход сдан исходом
    # choice») — служебные слова так и доезжали до чата (прогоны T19).
    print(
        "Последнее сообщение хода пиши владельцу, а не про меня: ни «ход сдан», "
        "ни имени исхода, ни слова «сигнал» — он их не знает."
    )
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
# Папка задачи не в git и живёт ровно столько, сколько её рабочая копия:
# ссылка на неё из ТЗ другой задачи протухает молча, и роль идёт искать
# файл, которого нет (прогон T24).
ORCH_LINK = re.compile(r"\.orch/(T\d+)/")


def check_text(text: str, task_id: str | None = None) -> None:
    чужие = {m for m in ORCH_LINK.findall(text or "") if m != task_id}
    if not чужие:
        return
    raise Refused(
        "текст задачи ссылается на папку другой задачи: "
        + ", ".join(f".orch/{t}/" for t in sorted(чужие))
        + ". Эта папка не в git и исчезает вместе с рабочей копией — "
        "перенесите нужное в текст задачи целиком."
    )


def cmd_task_new(args: argparse.Namespace) -> int:
    """Заявка в `inbox/`; движок превращает её в задачу на следующем проходе."""
    project = Path(args.project).resolve() if args.project else _project_here()
    if not (project / ".git").exists():
        raise Refused(f"{project} — не корень репозитория")
    text = args.text.strip()
    if not text:
        raise Refused("текст задачи пуст")
    check_text(text)
    sheet_edits = {}
    for item in args.after or []:
        key, _, value = item.partition("=")
        sheet_edits[f"{key}.after"] = _flag(value)
    for item in args.ask or []:
        key, _, value = item.partition("=")
        sheet_edits[f"{key}.ask"] = _flag(value)
    # Заявку могла завести роль изнутри задачи — тогда владелец должен
    # видеть в панели, что писал не он. Папка `.orch/<T>` могла остаться в
    # проекте от прошлой задачи, поэтому мало найти её: задача должна быть
    # жива и работать именно в этой копии, иначе мастер, запущенный в корне
    # проекта, подписался бы чужим номером.
    author = _author_here(project)
    request = {
        "id": uuid.uuid4().hex[:12],
        "author": author,
        "chain": args.chain,
        "project_path": str(project),
        "text": text,
        "branch": args.branch,
        "base": args.base,
        "preset": args.preset,
        "sheet_edits": sheet_edits,
        # По умолчанию заявка ложится в бэклог: в работу задача уходит
        # только рукой владельца (кнопка «В работу» или явный `--start`).
        "backlog": not bool(getattr(args, "start", False)),
        "stand": bool(getattr(args, "stand", False)),
        "notify": bool(getattr(args, "notify", False)),
        "at": signals.now(),
    }
    INBOX.mkdir(parents=True, exist_ok=True)
    path = INBOX / f"{request['id']}.json"
    path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    where = "в очередь" if getattr(args, "start", False) else "в бэклог"
    print(f"заявка {where}: {path}")
    return 0


def cmd_task_start(args: argparse.Namespace) -> int:
    """Заявка из бэклога едет сама: тот же номер, та же ветка, та же строка."""
    text = None
    if args.text:
        text = (sys.stdin.read() if args.text == "-" else args.text).strip()
        if not text:
            raise Refused("текст задачи пуст")
        check_text(text, args.task)
    sheet_edits = {}
    for item in args.after or []:
        key, _, value = item.partition("=")
        sheet_edits[f"{key}.after"] = _flag(value)
    for item in args.ask or []:
        key, _, value = item.partition("=")
        sheet_edits[f"{key}.ask"] = _flag(value)
    request = {
        "id": uuid.uuid4().hex[:12],
        "kind": "start",
        "task": args.task,
        "chain": args.chain,
        "preset": args.preset,
        "text": text,
        "branch": args.branch,
        "base": args.base,
        "sheet_edits": sheet_edits,
        # Неназванное остаётся тем, что записано в заявке: `None`, а не `False`.
        "stand": True if args.stand else None,
        "notify": True if args.notify else None,
        "at": signals.now(),
    }
    INBOX.mkdir(parents=True, exist_ok=True)
    path = INBOX / f"{request['id']}.json"
    path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"заявка {args.task} отпущена в работу: {path}")
    return 0


# ── команды владельца: чтение базы ───────────────────────────────────────
def _author_here(project: Path) -> str | None:
    """Номер живой задачи, которой принадлежит эта рабочая копия, или None."""
    try:
        task_id = find_task().task_id
    except NotInTask:
        return None
    try:
        conn = _ro_db()
    except Refused:
        return None
    row = conn.execute(
        "SELECT worktree_path, status FROM task WHERE id = ?", (task_id,)
    ).fetchone()
    if row is None or row["status"] not in ("running", "waiting", "queued"):
        return None
    if not row["worktree_path"]:
        return None
    return task_id if Path(row["worktree_path"]).resolve() == project else None


def _ro_db():
    """База только на чтение: единственный писатель — движок."""
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

    def show(limit: int, after: int) -> int:
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
    """Кнопка из терминала. Заявка в `inbox/`: писатель базы один — движок.

    `accept`/`back`/`again` — те же решения владельца, что и `orch gate`, тем
    же путём в обход панели: роли сюда так же нельзя (`_refuse_if_agent`).
    """
    if args.action in ("accept", "back", "again"):
        _refuse_if_agent(f"«orch task move … {args.action}»")
    conn = _ro_db()
    row = conn.execute("SELECT revision FROM task WHERE id = ?", (args.task,)).fetchone()
    if row is None:
        raise Refused(f"нет задачи {args.task}")
    action = args.action
    if action == "back" and getattr(args, "clean", False):
        action = "back_clean"
    request = {
        "id": uuid.uuid4().hex[:12],
        "kind": "button",
        "task": args.task,
        "revision": row["revision"],
        "action": action,
        "target": args.target,
        "comment": args.comment,
        "at": signals.now(),
    }
    INBOX.mkdir(parents=True, exist_ok=True)
    path = INBOX / f"{request['id']}.json"
    path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"кнопка «{action}» поставлена в очередь движку: {path}")
    return 0


def cmd_wizard(args: argparse.Namespace) -> int:
    """Открыть мастера задачи в проекте: заявка движку."""
    project = Path(args.project).resolve()
    request = {
        "id": uuid.uuid4().hex[:12],
        "kind": "wizard",
        "project_path": str(project),
        "task": getattr(args, "task", None),
        "at": signals.now(),
    }
    INBOX.mkdir(parents=True, exist_ok=True)
    (INBOX / f"{request['id']}.json").write_text(
        json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"мастер задачи для {project} откроется на следующем проходе")
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    """Решение владельца, сказанное словами роли.

    Панель — не единственный путь: владелец правит план в чате и там же
    говорит «принято» или «вернись на разведку». Роль передаёт это сюда
    (`UX-PLAN.md`). Работает только когда задача действительно стоит на
    воротах: обычной фразой в разговоре задачу не сдвинуть.

    Саму команду роль вызвать не может: `orch gate` исполняет решение
    владельца, а не догадку о нём (см. `_refuse_if_agent`).
    """
    _refuse_if_agent("«orch gate»")
    task = find_task()
    conn = _ro_db()
    row = conn.execute(
        "SELECT id, revision, status, wait_reason, step FROM task WHERE id = ?",
        (task.task_id,),
    ).fetchone()
    if row is None:
        raise Refused(f"нет задачи {task.task_id}")
    if row["status"] != "waiting":
        raise Refused(
            f"{task.task_id} сейчас не ждёт владельца (статус {row['status']}). "
            "Ход заканчивают вызовом `orch done <исход>`, а не `orch gate`."
        )
    action = args.action
    if action == "back" and not args.target:
        raise Refused("для «back» назовите шаг: orch gate back <шаг>")
    if action == "back" and getattr(args, "clean", False):
        action = "back_clean"
    request = {
        "id": uuid.uuid4().hex[:12],
        "kind": "button",
        "task": row["id"],
        "revision": row["revision"],
        "action": action,
        "target": args.target,
        "comment": args.comment,
        "at": signals.now(),
    }
    INBOX.mkdir(parents=True, exist_ok=True)
    (INBOX / f"{request['id']}.json").write_text(
        json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    where = f" на {args.target}" if args.target else ""
    print(f"решение владельца принято: {action}{where}. Задача поедет на следующем проходе.")
    return 0


def cmd_chains(args: argparse.Namespace) -> int:
    """Какие цепочки есть — мастеру, чтобы показать владельцу выбор."""
    for item in catalog():
        if item.get("error"):
            print(f"{item['name']}: не читается — {item['error']}")
            continue
        mark = " (правлена владельцем на странице настроек)" if item.get("custom") else ""
        print(f"{item['name']}{mark}: {item['description'] or 'без описания'}")
        print("  шаги:")
        for edge in item.get("edges") or []:
            print(f"    {_edge_line(edge)}")
        print(f"  ворота по умолчанию: {', '.join(item['gates']) or 'нет'}")
        print(f"  пресеты: {', '.join(item['presets']) or 'нет'}")
    return 0


def _edge_line(edge: dict) -> str:
    """Шаг со всеми его выходами: цепочка — граф, а не список.

    Печатать шаги через стрелку в порядке файла нельзя: с тех пор как ревью
    возвращает работу автору, порядок в файле и порядок хода — разные вещи.
    """
    nxt = edge["next"]
    if list(nxt) == ["*"]:
        targets = nxt["*"]
    else:
        targets = ", ".join(f"{target} ({outcome})" for outcome, target in nxt.items())
    parts = [f"{edge['step']:<15} → {targets}"]
    after = edge["after"]
    if after is True:
        parts.append("ворота: после любого хода")
    elif after:
        parts.append("ворота: после исхода " + ", ".join(after))
    if not edge["ask"]:
        parts.append("без вопросов")
    context = {
        "own": "заход в своей же сессии",
        "continue": "заход в сессии прошлого шага",
    }.get(edge.get("context", "fresh"))
    if context:
        parts.append(context)
    if edge["max_runs"] != 3:
        parts.append(f"заходов не больше {edge['max_runs']}")
    return "   ·   ".join(parts)


def cmd_branches(args: argparse.Namespace) -> int:
    """Свежие ветки проекта с пометкой, какие заняты работой.

    Занята — та, в которой прямо сейчас идёт задача: очередь и бэклог
    рабочую копию не держат.
    """
    project = Path(args.project).resolve() if args.project else _project_here()
    conn = _ro_db()
    busy = {
        row["branch"]: row["id"]
        for row in conn.execute(
            "SELECT id, branch FROM task WHERE status IN "
            "('running','waiting') AND branch IS NOT NULL"
        )
    }
    for item in recent(str(project)):
        mark = f"  занята задачей {busy[item['branch']]}" if item["branch"] in busy else ""
        pr = f"  PR #{item['pr']}" if item.get("pr") else ""
        print(f"{item['branch']}  {item.get('when','')}  {item.get('subject','')[:60]}{pr}{mark}")
    return 0


def cmd_task_autonomy(args: argparse.Namespace) -> int:
    """Переставить автономию уже заведённой задачи: пресет или отдельные ручки.

    Лист автономии правится и переключателями в панели, но по одному шагу;
    когда владелец говорит «не трогай меня до PR», это восемь щелчков.
    """
    edits = {}
    for item in args.after or []:
        key, _, value = item.partition("=")
        edits[f"{key}.after"] = _flag(value)
    for item in args.ask or []:
        key, _, value = item.partition("=")
        edits[f"{key}.ask"] = _flag(value)
    if not args.preset and not edits:
        raise Refused("нечего менять: назовите --preset или --after/--ask")
    request = {
        "id": uuid.uuid4().hex[:12],
        "kind": "autonomy",
        "task": args.task,
        "preset": args.preset,
        "sheet_edits": edits,
        "at": signals.now(),
    }
    INBOX.mkdir(parents=True, exist_ok=True)
    (INBOX / f"{request['id']}.json").write_text(
        json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"автономия {args.task} переставлена: движок применит ближайшим проходом")
    return 0


def cmd_task_edit(args: argparse.Namespace) -> int:
    """Переписать ТЗ заявки. Текст из аргумента или со стандартного ввода."""
    text = args.text
    if text == "-":
        text = sys.stdin.read()
    text = (text or "").strip()
    if not text:
        raise Refused("текст пуст")
    check_text(text, args.task)
    request = {
        "id": uuid.uuid4().hex[:12],
        "kind": "edit_text",
        "task": args.task,
        "text": text,
        "at": signals.now(),
    }
    INBOX.mkdir(parents=True, exist_ok=True)
    (INBOX / f"{request['id']}.json").write_text(
        json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"новое ТЗ {args.task} поставлено в очередь движку")
    return 0


def cmd_stand(args: argparse.Namespace) -> int:
    """Роль «Стенд» сообщает, чем кончилось: адрес или причина."""
    task = find_task()
    request = {
        "id": uuid.uuid4().hex[:12],
        "kind": "stand",
        "task": task.task_id,
        "at": signals.now(),
    }
    if args.action == "gone":
        request["gone"] = True
        message = f"стенд задачи {task.task_id} убран"
    elif args.action == "ready":
        if not args.port:
            raise Refused("назовите порт: orch stand ready 8020")
        request["port"] = int(args.port)
        message = f"стенд задачи {task.task_id} на порту {args.port}"
    else:
        if not args.reason:
            raise Refused('скажите, что мешает: orch stand failed "нет .env.example"')
        request["error"] = args.reason
        message = f"стенд задачи {task.task_id} не поднялся"
    INBOX.mkdir(parents=True, exist_ok=True)
    (INBOX / f"{request['id']}.json").write_text(
        json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{message}: владелец увидит это в панели задачи")
    return 0


def cmd_aside(args: argparse.Namespace) -> int:
    """Побочная роль говорит с движком: находка или конец хода.

    Опознаётся ход по `--id`, который движок напечатал в промпте: своей
    рабочей копии у побочной роли может не быть вовсе, а окружение AoE
    обычным сессиям не передаёт (`research/RISKS.md` п. 1).
    """
    run_id = str(args.id or "").strip().lstrip("Aa")
    if not run_id.isdigit():
        raise Refused("назовите свой ход: --id A17 (номер напечатан в промпте)")
    if not (args.pass_token or "").strip():
        raise Refused("нужен пропуск хода: --pass <из промпта>")
    request = {
        "id": uuid.uuid4().hex[:12],
        "kind": "aside",
        "run": int(run_id),
        "token": args.pass_token.strip(),
        "action": args.action,
        "at": signals.now(),
    }
    if args.action == "note":
        if not args.title:
            raise Refused('находке нужен заголовок: --title "ревью читало не тот файл"')
        options = []
        for item in args.option or []:
            verb, _, label = item.partition(":")
            verb, target = (verb.split("=", 1) + [None])[:2] if "=" in verb else (verb, None)
            if verb not in VERBS:
                raise Refused(f"вариант {verb!r} движок исполнить не сможет; можно: {', '.join(sorted(VERBS))}")
            options.append({"verb": verb, "target": target, "label": label.strip() or verb})
        request.update(
            severity="hold" if args.hold else "log",
            title=args.title,
            body=args.body or "",
            options=options,
        )
        message = "задача встанет на владельце" if args.hold else "находка ляжет в сводку"
    else:
        request["outcome"] = args.outcome
        message = "ход закрыт"
    INBOX.mkdir(parents=True, exist_ok=True)
    (INBOX / f"{request['id']}.json").write_text(
        json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{message}: движок разберёт заявку ближайшим проходом")
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    """Скелет чужого хода: что роль делала, коротко.

    Транскрипт агента лежит на диске целиком, но читать его подряд дорого:
    сотни тысяч знаков, из которых половина — вывод инструментов. Команда
    собирает из него обзор: вызовы с целями и исходами, ошибки, тронутые
    файлы, вопросы владельцу, финальное сообщение.
    """
    from . import digest as dg

    # `_ro_db` отдаёт голое соединение sqlite3, а не `Db`: `.conn` у него нет.
    conn = _ro_db()
    row = conn.execute(
        "SELECT r.*, t.worktree_path, t.project_path FROM run r JOIN task t ON t.id = r.task_id "
        "WHERE r.task_id = ? AND r.step = ? ORDER BY r.n DESC LIMIT 1"
        if args.run is None else
        "SELECT r.*, t.worktree_path, t.project_path FROM run r JOIN task t ON t.id = r.task_id "
        "WHERE r.task_id = ? AND r.step = ? AND r.n = ?",
        (args.task, args.step) if args.run is None else (args.task, args.step, args.run),
    ).fetchone()
    if row is None:
        raise Refused(f"у {args.task} нет захода {args.step}" + (f"/{args.run}" if args.run else ""))
    root = row["worktree_path"] or row["project_path"]
    data = dg.digest(
        root,
        since=row["started_at"],
        until=row["ended_at"],
        session=(row["acp_session_id"] if "acp_session_id" in row.keys() else None),
        max_tools=args.tools,
    )
    if not data["turns"]:
        print("транскрипта за это окно нет")
        return 0
    print(dg.render(data))
    return 0


def cmd_gc(args: argparse.Namespace) -> int:
    """Сироты на диске: рабочие копии, которым не соответствует живая задача.

    Копию задачи убирает движок — при архиве и сразу, если задача брошена.
    Но сессии удаляют руками, базу пересоздают, движок падает; тогда каталог
    остаётся навсегда. Команда показывает такие каталоги и, с `--yes`,
    убирает. Ветки не трогает никогда: в них работа.
    """
    conn = _ro_db()
    alive = {
        row["worktree_path"]
        for row in conn.execute(
            "SELECT worktree_path FROM task WHERE worktree_path IS NOT NULL "
            "AND archived_at IS NULL"
        )
    }
    projects = {
        row["project_path"]
        for row in conn.execute("SELECT DISTINCT project_path FROM task")
        if row["project_path"]
    }
    orphans: list[tuple[str, Path]] = []
    for project in sorted(projects):
        # Смотрим обе папки: свою (`<repo>-orch`) и ту, куда копии клал сам
        # AoE (`<repo>-worktrees`) — там остаются копии ночных прогонов, а в
        # них `node_modules` и `vendor` на сотни мегабайт.
        for base in (
            Path(project).parent / f"{Path(project).name}-orch",
            Path(project).parent / f"{Path(project).name}-worktrees",
        ):
            if not base.is_dir():
                continue
            for path in sorted(base.rglob(".git")):
                copy = path.parent
                if str(copy) in alive or str(copy.resolve()) in alive:
                    continue
                orphans.append((project, copy))
    if not orphans:
        print("сирот нет: все рабочие копии принадлежат живым задачам")
        return 0
    for project, copy in orphans:
        size = sum(f.stat().st_size for f in copy.rglob("*") if f.is_file()) // 1024 // 1024
        print(f"{copy}  ~{size} МиБ  (проект {project})")
    if not args.yes:
        print("\nэто показ; чтобы убрать — `orch gc --yes`. Ветки не трогаются.")
        return 0
    for project, copy in orphans:
        error = remove_worktree(project, copy)
        print(f"{copy}: {'убрана' if not error else 'осталась — ' + error[:120]}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Что должно работать, чтобы движок ехал."""
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
    # Флаг «срочно» едет к хосту файлом в его каталоге — договорённость из
    # исходников AoE, не из документации. Проверяем, что каталог пишется.
    hooks = hooks_dir()
    try:
        hooks.mkdir(parents=True, exist_ok=True)
        probe = hooks / ".orch-doctor"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        check("каталог флагов AoE", True, str(hooks))
    except OSError as exc:
        check("каталог флагов AoE", False, f"{hooks}: {exc}")
    for name in chain_names():
        path = chain_path(name)
        note = "правленая владельцем" if path.parent != chains_dir() else ""
        try:
            load_chain(path)
            check(f"цепочка {name}", True, note)
        except ChainError as exc:
            check(f"цепочка {name}", False, str(exc))
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

    p = sub.add_parser("note", help="запасной канал комментария")
    p.add_argument("text")
    p.set_defaults(func=cmd_note)

    p = sub.add_parser(
        "gate",
        help="решение владельца, сказанное словами в чате (только на воротах)",
    )
    p.add_argument("action", choices=["accept", "back", "again"])
    p.add_argument("target", nargs="?", help="шаг для «back»")
    p.add_argument(
        "--clean",
        action="store_true",
        help="вернуть начисто: забыть заходы и артефакты всего, что было после этого шага",
    )
    p.add_argument("--comment", help="что владелец просил передать адресату")
    p.set_defaults(func=cmd_gate)

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
    p.add_argument("action", choices=["accept", "back", "again", "start", "close"])
    p.add_argument("--target", help="шаг для accept/back")
    p.add_argument(
        "--clean",
        action="store_true",
        help="вернуть начисто: забыть заходы и артефакты всего, что было после этого шага",
    )
    p.add_argument("--comment", help="комментарий владельца адресату")
    p.set_defaults(func=cmd_task_move)

    p = task_sub.add_parser("new", help="заявка на новую задачу")
    p.add_argument("text")
    p.add_argument("--chain", default="deep")
    p.add_argument("--project")
    p.add_argument("--preset")
    p.add_argument("--after", action="append", metavar="ШАГ=on|off")
    p.add_argument("--ask", action="append", metavar="ШАГ=on|off")
    p.add_argument(
        "--start",
        action="store_true",
        help="сразу в очередь: задача поедет, как освободится место (по умолчанию — бэклог)",
    )
    # Флаг остаётся ради ролей и старых записок: бэклог теперь и так по
    # умолчанию, так что вреда от него нет.
    p.add_argument("--backlog", action="store_true", help=argparse.SUPPRESS)
    p.add_argument(
        "--stand",
        action="store_true",
        help="владелец придёт смотреть работу: поднять стенд задачи к первым воротам",
    )
    p.add_argument("--branch", help="ветка задачи; по умолчанию новая от базовой")
    p.add_argument("--base", help="от какой ветки ответвляться")
    p.add_argument(
        "--notify",
        action="store_true",
        help="звать владельца в Telegram, когда задача встанет на воротах",
    )
    p.set_defaults(func=cmd_task_new)

    p = task_sub.add_parser(
        "start", help="отпустить заявку из бэклога в работу (тем же номером)"
    )
    p.add_argument("task", metavar="T12")
    p.add_argument("--chain", help="цепочка; по умолчанию та, что записана в заявке")
    p.add_argument("--preset", help="пресет автономии; без него лист заявки остаётся как был")
    p.add_argument("--text", help="переписанное ТЗ; «-» — со стандартного ввода")
    p.add_argument("--branch", help="ветка задачи; по умолчанию ветка заявки")
    p.add_argument("--base", help="от какой ветки ответвляться")
    p.add_argument("--after", action="append", metavar="шаг=да|нет", help="ворота после шага")
    p.add_argument("--ask", action="append", metavar="шаг=да|нет", help="спрашивать ли на шаге")
    p.add_argument("--stand", action="store_true", help="поднять стенд задачи")
    p.add_argument(
        "--notify", action="store_true",
        help="звать владельца в Telegram, когда задача встанет на воротах",
    )
    p.set_defaults(func=cmd_task_start)

    p = task_sub.add_parser("edit", help="переписать ТЗ заявки в бэклоге")
    p.add_argument("task")
    p.add_argument("--text", required=True, help="новый текст; «-» — со стандартного ввода")
    p.set_defaults(func=cmd_task_edit)

    p = sub.add_parser("log", help="журнал событий")
    p.add_argument("task", nargs="?")
    p.add_argument("--follow", action="store_true")
    p.add_argument("--tail", type=int, default=20)
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("stats", help="качество промптов по шагам")
    p.add_argument("--last", type=int, default=20)
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("wizard", help="открыть мастера задачи в проекте")
    p.add_argument("project")
    p.set_defaults(func=cmd_wizard)

    p = sub.add_parser("chains", help="какие цепочки есть")
    p.set_defaults(func=cmd_chains)

    p = sub.add_parser("branches", help="ветки проекта и кто их занял")
    p.add_argument("--project")
    p.set_defaults(func=cmd_branches)

    p = sub.add_parser(
        "stand",
        help="роль «Стенд»: сообщить адрес поднятого окружения или причину отказа",
    )
    p.add_argument("action", choices=["ready", "failed", "gone"])
    p.add_argument("port", nargs="?", type=int, help="порт для «ready»")
    p.add_argument("--reason", help="одной строкой, что мешает (для «failed»)")
    p.set_defaults(func=cmd_stand)

    p = sub.add_parser(
        "aside",
        help="побочная роль: записать находку владельцу или закончить ход",
    )
    p.add_argument("action", choices=["note", "done"])
    p.add_argument("--id", required=True, help="номер вашего хода из промпта, например A17")
    p.add_argument(
        "--pass", dest="pass_token", required=True,
        help="пропуск хода из промпта: без него движок команду не примет",
    )
    p.add_argument("--title", help="находка одной строкой")
    p.add_argument("--body", help="подробности, до двадцати строк")
    p.add_argument("--hold", action="store_true", help="остановить задачу и позвать владельца")
    p.add_argument(
        "--option",
        action="append",
        metavar="ГЛАГОЛ[=ЦЕЛЬ]:ПОДПИСЬ",
        help='вариант ответа, например back=plan:"вернуть на план"',
    )
    p.add_argument("--outcome", help="чем кончился ход (для «done»)")
    p.set_defaults(func=cmd_aside)

    p = sub.add_parser(
        "autonomy", help="переставить ворота и вопросы у заведённой задачи"
    )
    p.add_argument("task")
    p.add_argument("--preset", help="имя пресета цепочки, например auto")
    p.add_argument("--after", action="append", metavar="ШАГ=on|off", help="ворота шага")
    p.add_argument("--ask", action="append", metavar="ШАГ=on|off", help="вопросы шага")
    p.set_defaults(func=cmd_task_autonomy)

    p = sub.add_parser("digest", help="скелет чужого хода: что роль делала, коротко")
    p.add_argument("task")
    p.add_argument("step")
    p.add_argument("run", nargs="?", type=int, help="номер захода; по умолчанию последний")
    p.add_argument("--tools", type=int, default=120, help="сколько вызовов показывать")
    p.set_defaults(func=cmd_digest)

    p = sub.add_parser("gc", help="рабочие копии, которым не соответствует живая задача")
    p.add_argument("--yes", action="store_true", help="убрать найденное, а не только показать")
    p.set_defaults(func=cmd_gc)

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
