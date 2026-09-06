"""Содержимое панелей плагина: чистые функции от состояния базы.

Панель — функция состояния, а не поток событий: каждый проход движка рисует
её заново, кнопки несут ревизию задачи, устаревшая кнопка отклоняется
(`PLAN.md` §8). Здесь нет ни одного вызова AoE и ни одной записи — только
чтение базы и складывание блоков.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .chain import DONE, Chain, ChainError, parse as parse_chain
from .db import ABANDONED, BACKLOG, Db, QUEUED, RUNNING, WAITING, epoch
from .db import DONE as ST_DONE
from .engine import WAIT_REASONS

# Сколько строк показываем, чтобы панель влезала в 64 КиБ и читалась с телефона.
MAX_TASKS = 30
MAX_DONE = 10
MAX_EVENTS = 10
MAX_COMMENTS = 3

# Адрес машины в частной сети владельца: веб-сервис отдаётся на том же номере
# порта, что слушает на 127.0.0.1 (`/var/lib/vps-dev/style/machine/ports.md`).
HOST = "dev-hel1-3.taila4db50.ts.net"

# Кнопки по причине остановки: что предлагать владельцу, когда задача встала.
BUTTONS_BY_REASON = {
    "gate": ("accept", "back"),
    "no_signal": ("again", "accept_as_is", "back"),
    "max_runs": ("again", "accept_as_is", "back"),
    "artifact": ("again", "back"),
    "bad_outcome": ("again", "accept_as_is", "back"),
    "error": ("again", "back"),
    "ask": (),
    "no_worker": ("again",),
    "branch_busy": ("again", "back"),
    "abandoned": (),
    "chain_broken": (),
    "path_mismatch": (),
}

BUTTON_LABELS = {
    "accept": "Принять",
    "accept_as_is": "Принять как есть",
    "again": "Ещё заход",
    "back": "Вернуть на",
    "start": "Запустить",
}

# Причины, где «принять как есть» — это выбор исхода владельцем: роль либо не
# назвала исход, либо назвала тот, что ведёт по кругу (`PLAN.md` §5 п. 4, 7).
PICK_OUTCOME_REASONS = ("no_signal", "max_runs", "bad_outcome")


# ── главная панель ───────────────────────────────────────────────────────
def home_pane(db: Db, projects: list[str] | None = None, cost_warn: float = 5.0) -> dict:
    """Слот `home-pane` «Задачи»: витрина, а не пульт.

    Три секции: что решить, что лежит в бэклоге, что закрыто. Едущих задач и
    очереди тут нет нарочно — про них рассказывает сайдбар (цвет строки,
    бейдж шага, счётчик у группы), и второй список тех же строк только
    отнимал место (`UX-PLAN.md`).
    """
    blocks: list[dict] = []
    waiting = _sorted_waiting(db)
    backlog = db.tasks((BACKLOG,))
    закрытые = db.tasks((ST_DONE,))
    done = [t for t in закрытые if t["wait_reason"] != "closed_by_owner"][-MAX_DONE:]
    снятые = [t for t in закрытые if t["wait_reason"] == "closed_by_owner"][-MAX_DONE:]

    if waiting:
        blocks.append(
            {
                "kind": "section",
                "title": "Ждут вас",
                "badges": [{"text": str(len(waiting)), "tone": "danger"}],
                "children": [_waiting_row(db, t) for t in waiting[:MAX_TASKS]],
            }
        )
        first = waiting[0]
        blocks.append(
            {
                "kind": "callout",
                "tone": "danger",
                "icon": "hand",
                "title": f"{first['id']}: {_reason_text(first['wait_reason'])}",
                "detail": _what_to_decide(db, first),
                "actions": _buttons(db, first),
            }
        )

    if backlog:
        children: list[dict] = []
        for t in backlog[:MAX_TASKS]:
            children.append(
                {
                    "kind": "row",
                    "label": f"{t['id']} · {t['title']}",
                    "sublabel": _who_filed(t),
                    "value": t["branch"] or "",
                    "mono": True,
                }
            )
            # Текст задачи виден целиком: заявку мог написать не владелец, и
            # прежде чем её запускать, надо прочитать, что в ней стоит.
            children.append(
                {
                    "kind": "note",
                    "text": (t["text"] or "").strip()[:800] or "текста нет",
                }
            )
            # Кнопки отдельно, а строка не кликается: раньше нажатие по
            # строке запускало задачу без спроса, и случайный тык уводил в
            # работу, которую владелец не заказывал.
            children.append(
                {
                    "kind": "columns",
                    "children": [
                        {
                            "kind": "action",
                            "label": "В работу",
                            "method": "orch.wizard",
                            "variant": "primary",
                            "tooltip": "мастер спросит цепочку, ветку и автономию в чате",
                            "params": {"task": t["id"], "revision": t["revision"]},
                        },
                        {
                            "kind": "action",
                            "label": "Править ТЗ",
                            "method": "orch.wizard",
                            "tooltip": "переписать текст заявки в разговоре с мастером",
                            "params": {
                                "task": t["id"],
                                "revision": t["revision"],
                                "mode": "text",
                            },
                        },
                        {
                            "kind": "action",
                            "label": "Удалить",
                            "method": "orch.close",
                            "tooltip": "снять заявку и освободить её ветку",
                            "params": {"task": t["id"], "revision": t["revision"]},
                        },
                    ],
                }
            )
        blocks.append(
            {
                "kind": "section",
                "title": "Бэклог",
                "badges": [{"text": str(len(backlog))}],
                "children": children,
            }
        )

    if done:
        blocks.append(
            {
                "kind": "section",
                "title": "Готово",
                "badges": [{"text": str(len(done)), "tone": "success"}],
                "collapsible": True,
                "collapsed": True,
                "children": [
                    {
                        "kind": "row",
                        "label": f"{t['id']} · {t['title']}",
                        "sublabel": "доведена до конца",
                        "value": f"{_ago(t['closed_at'])} назад",
                        "tone": "success",
                    }
                    for t in reversed(done)
                ],
            }
        )
    if снятые:
        blocks.append(
            {
                "kind": "section",
                "title": "Снято",
                "badges": [{"text": str(len(снятые))}],
                "collapsible": True,
                "collapsed": True,
                "children": [
                    {
                        "kind": "row",
                        "label": f"{t['id']} · {t['title']}",
                        "sublabel": "закрыта, работа не делалась",
                        "value": f"{_ago(t['closed_at'])} назад",
                        "tone": "neutral",
                    }
                    for t in reversed(снятые)
                ],
            }
        )

    if not blocks:
        blocks.append({"kind": "note", "text": "Задач нет. Заведите первую."})

    blocks += _new_task_blocks(projects or [])
    return {
        "title": "orch",
        "default_location": "right",
        "icon": "list-checks",
        "blocks": blocks,
        "footer": _footer(db, waiting),
    }


def _new_task_blocks(projects: list[str]) -> list[dict]:
    """Заведение задачи: строка на проект плюс «другой проект».

    Клик по общей панели приходит без сессии, а мастеру нужен проект, поэтому
    проект выбирается сразу строкой. Список — все репозитории каталога
    проектов, а не только те, где уже шла работа: иначе в новом проекте
    задачу нельзя было бы завести, не открыв там сессию руками.
    """
    rows = [
        {
            "kind": "row",
            "label": Path(p).name,
            "sublabel": p,
            "value": "завести",
            "mono": True,
            "method": "orch.wizard",
            "params": {"project": p},
        }
        for p in projects[:MAX_TASKS]
    ]
    rows.append(
        {
            "kind": "row",
            "label": "другой проект",
            "sublabel": "мастер спросит путь в чате",
            "value": "завести",
            "method": "orch.wizard",
            "params": {},
        }
    )
    rows.append(
        {
            "kind": "note",
            "text": "То же самое без панели: в обычной «New session» напишите "
            "orch в поле Group или в названии сессии — она сама станет "
            "мастером. Из открытой сессии проекта — Ctrl+K, «orch: новая "
            "задача».",
        }
    )
    return [
        {
            "kind": "section",
            "title": "Новая задача",
            "icon": "plus",
            "badges": [{"text": str(len(projects))}],
            "collapsible": True,
            "collapsed": len(projects) > 6,
            "children": rows,
        }
    ]


def _footer(db: Db, waiting: list) -> dict:
    if waiting:
        return {
            "text": "нужно ваше решение",
            "value": str(len(waiting)),
            "tone": "danger",
            "icon": "hand",
        }
    running = len(db.tasks((RUNNING,))) + len(db.tasks((QUEUED,)))
    if running:
        return {"text": "едут", "value": str(running), "tone": "info", "icon": "play"}
    return {"text": "тихо", "value": "0", "tone": "neutral"}


def _who_filed(task) -> str:
    """Кто завёл заявку: роль сама или владелец.

    Роли имеют право заводить задачи в бэклог (`PLAN.md` §6), и в панели
    такая заявка выглядит как своя. Владелец должен видеть, что писал не он.
    """
    author = task["author"] if "author" in task.keys() else None
    if author:
        return f"завела роль задачи {author} — вы это не писали"
    return "завели вы"


def _waiting_row(db: Db, task) -> dict:
    return {
        "kind": "row",
        "label": f"{task['id']} · {task['title']}",
        "sublabel": _reason_text(task["wait_reason"]),
        "value": _ago(_state_since(db, task)),
        "tone": "danger",
        "badges": [{"text": task["step"] or "—"}],
    }


# ── панель задачи в сессии ───────────────────────────────────────────────
def task_pane(
    db: Db,
    task,
    session_id: str,
    base_url: str,
    cost_warn: float = 5.0,
) -> dict:
    chain = _chain(task)
    blocks: list[dict] = [
        {
            "kind": "row",
            "label": task["title"],
            "sublabel": f"{task['id']} · цепочка {task['chain']}",
            "value": task["status"],
            "value_tone": _tone(task["status"]),
        }
    ]

    if chain:
        blocks.append(
            {
                "kind": "section",
                "title": "Путь задачи",
                "value": _trail(db, task, chain),
                "children": _trail_rows(db, task, chain, base_url),
            }
        )

    if task["status"] == WAITING:
        blocks.append(
            {
                "kind": "callout",
                "tone": "danger",
                "icon": "hand",
                "title": _reason_text(task["wait_reason"]),
                "detail": _what_to_decide(db, task),
                "actions": _buttons(db, task),
            }
        )
    elif task["status"] == RUNNING:
        run = db.open_run(task["id"])
        if run:
            blocks.append(
                {
                    "kind": "row",
                    "label": f"шаг {run['step']}, заход {run['n']}",
                    "sublabel": f"сессия {run['session_id'] or '—'}",
                    "value": _ago(run["started_at"]),
                    "tone": "info",
                }
            )

    answer = _last_orch_answer(db, task)
    if answer:
        blocks.append(
            {
                "kind": "note",
                "tone": "warn",
                "text": f"последний ответ orch: {answer[:400]}",
            }
        )

    cost = _last_cost(db, task["id"])
    if cost and cost >= cost_warn:
        blocks.append(
            {
                "kind": "note",
                "tone": "warn",
                "text": f"прошлый ход стоил ${cost:.2f} — дороже порога ${cost_warn:.0f}",
            }
        )

    blocks.append(_stand_row(db, task))

    wizard = task["wizard_session"] if "wizard_session" in task.keys() else None
    if wizard:
        # Разговор, в котором задачу заводили: сама сессия в архиве, но
        # прочитать постановку и переписку с мастером бывает нужно.
        blocks.append(
            {
                "kind": "row",
                "label": "постановка",
                "sublabel": "разговор с мастером, где задачу заводили",
                "value": "открыть",
                "href": f"{base_url}/session/{wizard}",
            }
        )

    links = _artifact_links(db, task, chain, session_id, base_url)
    if links:
        blocks.append({"kind": "section", "title": "Файлы ролей", "children": links})

    if chain:
        blocks.append(
            {
                "kind": "section",
                "title": "Лист автономии",
                "collapsible": True,
                "collapsed": True,
                "children": _sheet_rows(db, task, chain),
            }
        )

    comments = [
        m for m in db.moves(task["id"], limit=20) if m["comment"]
    ][:MAX_COMMENTS]
    if comments:
        blocks.append(
            {
                "kind": "section",
                "title": "Комментарии",
                "collapsible": True,
                "children": [
                    {
                        "kind": "comment",
                        "author": "вы",
                        "body": m["comment"],
                        "path": f"{m['from_step'] or '—'} → {m['to_step'] or '—'}",
                    }
                    for m in comments
                ],
            }
        )

    blocks.append(
        {
            "kind": "section",
            "title": "Журнал",
            "collapsible": True,
            "collapsed": True,
            "scroll": True,
            "children": [
                {
                    "kind": "row",
                    "label": e["kind"],
                    "sublabel": (e["payload"] or "")[:120],
                    "value": _ago(e["at"]),
                    "mono": True,
                }
                for e in db.events(task["id"], limit=MAX_EVENTS)
            ],
        }
    )
    return {
        "title": f"orch · {task['id']}",
        "default_location": "right",
        "icon": "list-checks",
        "blocks": blocks,
    }


# ── строка сессии в сайдбаре ─────────────────────────────────────────────
# Хост сам подсвечивает строку, когда сессия `Waiting`/`Error` или на ней
# флаг `urgent` (движок его ставит на каждой остановке). Подсветка говорит
# «посмотри сюда», а бейдж — зачем: ворота, вопрос, какой шаг из скольких.
def row_badge(db: Db, task, session_id: str, chain: Chain | None = None) -> dict:
    """Слот `row-badge`: пометка на строке **этой** сессии, а не задачи.

    У задачи много сессий — по одной на заход, и все они висят в сайдбаре.
    Пометка «ворота» на строке позапрошлого шага соврала бы: этот заход
    давно закончен и своим исходом. Поэтому бейдж строится по заходу,
    которому принадлежит сессия, и только текущий заход говорит о задаче.
    """
    run = db.conn.execute(
        "SELECT * FROM run WHERE task_id = ? AND session_id = ? ORDER BY id DESC LIMIT 1",
        (task["id"], session_id),
    ).fetchone()
    if run is None:
        return {"text": task["id"], "tone": "neutral"}
    if run["ended_at"] and run["step"] != task["step"]:
        outcome = run["outcome"] or ("сдан" if run["signalled"] else "без сигнала")
        return {
            "text": f"{run['step']} → {outcome}",
            "tone": "neutral",
            "tooltip": f"{task['id']} · заход {run['n']} закончен",
        }
    status = task["status"]
    if status == WAITING:
        reason = task["wait_reason"] or ""
        text = {
            "gate": "ворота",
            "ask": "вопрос",
            "no_signal": "нет сигнала",
            "max_runs": "предел заходов",
            "artifact": "нет файла",
            "bad_outcome": "чужой исход",
            "error": "ошибка",
            "no_worker": "агент не поднялся",
        }.get(reason, "ждёт вас")
        return {
            "text": f"{text} · {run['step']}",
            "tone": "danger",
            "icon": "hand",
            "tooltip": _what_to_decide(db, task),
        }
    if status == ST_DONE:
        return {"text": "готово", "tone": "success", "icon": "check"}
    if status == ABANDONED:
        return {"text": "сессия потеряна", "tone": "danger"}
    if status == QUEUED:
        return {"text": "в очереди", "tone": "neutral"}
    place = ""
    n, total = step_place(task, chain)
    if n and total:
        place = f" {n}/{total}"
    return {
        "text": f"{run['step']}{place}",
        "tone": "info",
        "tooltip": f"{task['id']} · {task['title']}",
    }


def step_place(task, chain: Chain | None) -> tuple[int | None, int | None]:
    """Который шаг из скольких — для бейджа. Нет цепочки — нет счёта."""
    if not chain or not task["step"]:
        return None, None
    ids = [s.id for s in chain.steps]
    if task["step"] not in ids:
        return None, None
    return ids.index(task["step"]) + 1, len(ids)


# ── вспомогательное ──────────────────────────────────────────────────────
def _chain(task) -> Chain | None:
    try:
        return parse_chain(task["chain_yaml"], source=f"задача {task['id']}")
    except ChainError:
        return None


def _sorted_waiting(db: Db) -> list:
    """Старшие сверху: кто ждёт дольше, тот первый (`PLAN.md` §13, вопрос 23)."""
    tasks = db.tasks((WAITING,))
    return sorted(tasks, key=lambda t: _state_since(db, t) or t["created_at"])


def _state_since(db: Db, task) -> str | None:
    """Когда задача вошла в нынешнее состояние — по заходам, без новых полей."""
    if task["status"] == RUNNING:
        run = db.open_run(task["id"])
        if run:
            return run["started_at"]
    row = db.conn.execute(
        "SELECT ended_at FROM run WHERE task_id = ? AND ended_at IS NOT NULL "
        "ORDER BY id DESC LIMIT 1",
        (task["id"],),
    ).fetchone()
    return (row["ended_at"] if row else None) or task["created_at"]


def _reason_text(reason: str | None) -> str:
    return WAIT_REASONS.get(reason or "", reason or "ждёт")


def _what_to_decide(db: Db, task) -> str:
    """Строка «что решить» — то, ради чего владелец открыл панель."""
    reason = task["wait_reason"]
    step = task["step"] or "—"
    last = db.last_run_of_step(task["id"], step) if task["step"] else None
    if reason == "gate":
        outcome = last["outcome"] if last else None
        # У шага с одним переходом исхода нет — не показывать «исходом None».
        how = f" исходом «{outcome}»" if outcome else ""
        return (
            f"Шаг {step} закончил ход{how}. Принять и ехать дальше "
            f"или вернуть назад с комментарием."
        )
    if reason == "no_signal":
        answer = _last_orch_answer(db, task)
        tail = f" Последнее, что сказала команда: {answer[:200]}" if answer else ""
        return f"Шаг {step} закончил ход, не сдав его.{tail}"
    if reason == "max_runs":
        return f"Шаг {step} израсходовал все заходы. Дать ещё, принять как есть или вернуть."
    if reason == "ask":
        return f"Роль на шаге {step} задала вопрос — ответьте ей в чате этой сессии."
    if reason == "artifact":
        return f"Шаг {step} сдал ход, но его файла нет или он не той формы."
    if reason == "bad_outcome":
        return f"Шаг {step} назвал исход, которого нет в цепочке."
    if reason == "error":
        return f"Сессия шага {step} в ошибке."
    if reason == "branch_busy":
        return _branch_busy_text(db, task)
    if reason == "no_worker":
        return f"У сессии шага {step} не поднялся агент. Ещё заход заведёт новую сессию."
    return f"Шаг {step} ждёт вас."


def _stand_row(db: Db, task) -> dict:
    """Стенд задачи: ссылка, «поднимается» или кнопка.

    Поднимает окружение роль «Стенд», а не движок: у каждого проекта свой
    способ, и знает его проект, а не оркестратор (`UX-PLAN.md`).
    """
    stand = task["stand"] if "stand" in task.keys() else None
    port = task["stand_port"] if "stand_port" in task.keys() else None
    session = task["stand_session"] if "stand_session" in task.keys() else None
    if stand and port:
        return {
            "kind": "row",
            "label": "стенд",
            "sublabel": f"{stand} · погаснет, когда задача закроется",
            "value": str(port),
            "value_tone": "success",
            "mono": True,
            "href": f"https://{HOST}:{port}/",
        }
    if session:
        failed = _last_stand_error(db, task)
        if failed:
            return {
                "kind": "row",
                "label": "стенд",
                "sublabel": failed[:200],
                "value": "не поднялся",
                "value_tone": "danger",
            }
        return {
            "kind": "row",
            "label": "стенд",
            "sublabel": "роль «Стенд» поднимает окружение — смотрите её сессию",
            "value": "поднимается",
            "value_tone": "warn",
        }
    return {
        "kind": "action",
        "label": "Поднять стенд",
        "method": "orch.stand",
        "icon": "play",
        "tooltip": "роль поднимет окружение задачи на своих портах",
        "params": {"task": task["id"], "revision": task["revision"]},
    }


def _last_stand_error(db: Db, task) -> str | None:
    """Последнее слово про стенд: сорвалось или ещё поднимается."""
    for event in db.events(task["id"], limit=20):
        if event["kind"] == "stand_ready":
            return None
        if event["kind"] == "stand_failed":
            try:
                return json.loads(event["payload"] or "{}").get("error") or "не поднялся"
            except json.JSONDecodeError:
                return "не поднялся"
    return None


def _branch_busy_text(db: Db, task) -> str:
    """Кто держит ветку и что с этим делать — из журнала, без догадок."""
    branch = task["branch"] or "—"
    for event in db.events(task["id"], limit=20):
        if event["kind"] not in (
            "branch_held", "branch_dirty", "branch_in_project", "branch_release_failed"
        ):
            continue
        try:
            payload = json.loads(event["payload"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        path = payload.get("path", "?")
        if event["kind"] == "branch_held":
            return (
                f"Ветку {branch} уже держит задача {payload.get('by')} "
                f"({path}). Закройте ту задачу или заведите эту на другой ветке."
            )
        if event["kind"] == "branch_dirty":
            return (
                f"Ветка {branch} вычекана в {path}, и там есть несохранённая "
                "работа — сама я её не трону. Разберитесь с ней и нажмите "
                "«Ещё заход»."
            )
        if event["kind"] == "branch_in_project":
            return (
                f"Ветка {branch} вычекана в самом проекте ({path}). "
                "Переключите его на другую ветку и нажмите «Ещё заход»."
            )
        return f"Не смогла освободить ветку {branch}: {path}."
    return f"Ветку {branch} держит другая рабочая копия."


def _buttons(db: Db, task) -> list[dict]:
    reason = task["wait_reason"] or ""
    chain = _chain(task)
    actions: list[dict] = []
    for action in BUTTONS_BY_REASON.get(reason, ("again",)):
        if action == "accept_as_is" and reason in PICK_OUTCOME_REASONS:
            # Не «повторить прошлый исход», а «выберите, каким считать ход»:
            # прошлый исход у предела заходов как раз и ведёт по кругу.
            for outcome, target in _outcomes_of(chain, task).items():
                actions.append(
                    {
                        "kind": "action",
                        "label": f"Принять как «{outcome}» → {target}",
                        "method": "orch.accept_as_is",
                        "params": {
                            "task": task["id"],
                            "revision": task["revision"],
                            "target": outcome,
                        },
                    }
                )
            continue
        if action == "back":
            if not chain or not task["step"]:
                continue
            try:
                moves = chain.step(task["step"]).human_moves
            except ChainError:
                moves = []
            for target in moves:
                actions.append(
                    {
                        "kind": "action",
                        "label": f"Вернуть на {target}",
                        "method": "orch.back",
                        "params": {
                            "task": task["id"],
                            "revision": task["revision"],
                            "target": target,
                        },
                    }
                )
            continue
        actions.append(
            {
                "kind": "action",
                "label": BUTTON_LABELS.get(action, action),
                "method": f"orch.{action}",
                "variant": "primary" if action in ("accept", "again") else None,
                "params": {"task": task["id"], "revision": task["revision"]},
            }
        )
    return [{k: v for k, v in a.items() if v is not None} for a in actions]


def _trail_rows(db: Db, task, chain: Chain, base_url: str) -> list[dict]:
    """Путь по шагам строками, каждая — ссылка на сессию своего захода.

    Пока сайдбар веба сворачивает сессии одной ветки в одну строку, это
    единственная дорога владельца к сессии прошлого шага из интерфейса.
    """
    rows = []
    for run in db.conn.execute(
        "SELECT * FROM run WHERE task_id = ? ORDER BY id", (task["id"],)
    ):
        outcome = run["outcome"] or (
            "идёт" if not run["ended_at"] else ("сдан" if run["signalled"] else "нет сигнала")
        )
        row = {
            "kind": "row",
            "label": run["step"],
            "sublabel": f"заход {run['n']}",
            "value": outcome,
            "value_tone": "success" if run["signalled"] else "warn",
            "selected": run["step"] == task["step"] and not run["ended_at"],
        }
        if run["session_id"]:
            row["href"] = f"{base_url}/session/{run['session_id']}"
            row["tooltip"] = "открыть сессию этого захода"
        rows.append(row)
    return rows or [{"kind": "note", "text": "заходов ещё не было"}]


def _outcomes_of(chain: Chain | None, task) -> dict[str, str]:
    if not chain or not task["step"]:
        return {}
    try:
        step = chain.step(task["step"])
    except ChainError:
        return {}
    if step.single_next is not None:
        return {"дальше": step.single_next}
    return dict(step.next)


def _trail(db: Db, task, chain: Chain) -> str:
    steps = [
        m["to_step"]
        for m in reversed(db.moves(task["id"], limit=40))
        if m["to_step"] and m["to_step"] != DONE
    ]
    out: list[str] = []
    seen: set[str] = set()
    for s in steps:
        if out and out[-1].lstrip("⟲ ") == s:
            continue
        out.append(f"⟲ {s}" if s in seen else s)
        seen.add(s)
    return " → ".join(out) or (task["step"] or "—")


def _sheet_rows(db: Db, task, chain: Chain) -> list[dict]:
    """Переключатели листа — только для ещё не пройденных шагов."""
    sheet = json.loads(task["human_sheet"] or "{}")
    passed = {r["step"] for r in db.conn.execute(
        "SELECT DISTINCT step FROM run WHERE task_id = ? AND ended_at IS NOT NULL",
        (task["id"],),
    )}
    rows = []
    for step in chain.steps:
        knobs = sheet.get(step.id, {})
        done_already = step.id in passed and step.id != task["step"]
        after = knobs.get("after", step.human_after)
        ask = knobs.get("ask", step.human_ask)
        rows.append(
            {
                "kind": "row",
                "label": step.id,
                "sublabel": "пройден" if done_already else "ворота / вопросы",
                "value": f"{'ждать' if after else 'не ждать'} · {'можно' if ask else 'нельзя'}",
                "tone": "neutral" if done_already else "info",
                **(
                    {}
                    if done_already
                    else {
                        "method": "orch.sheet_step",
                        "params": {
                            "task": task["id"],
                            "revision": task["revision"],
                            "step": step.id,
                        },
                    }
                ),
            }
        )
    return rows


def _artifact_links(db: Db, task, chain: Chain | None, session_id: str, base: str) -> list[dict]:
    if not chain:
        return []
    rows = []
    for step in chain.steps:
        for name in step.artifact:
            path = f".orch/{task['id']}/artifacts/{name}"
            rows.append(
                {
                    "kind": "row",
                    "label": name,
                    "sublabel": step.id,
                    "href": f"{base}/api/sessions/{session_id}/file?path={path}",
                    "mono": True,
                }
            )
    return rows


def _last_orch_answer(db: Db, task) -> str | None:
    for event in db.events(task["id"], limit=20):
        if event["kind"] != "no_signal":
            continue
        try:
            payload = json.loads(event["payload"] or "{}")
        except json.JSONDecodeError:
            continue
        if payload.get("last"):
            return payload["last"]
    return None


def _last_cost(db: Db, task_id: str) -> float | None:
    row = db.conn.execute(
        "SELECT cost_usd FROM run WHERE task_id = ? AND cost_usd IS NOT NULL "
        "ORDER BY id DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    return row["cost_usd"] if row else None


def _tone(status: str) -> str:
    return {
        RUNNING: "info",
        WAITING: "danger",
        ST_DONE: "success",
        ABANDONED: "danger",
    }.get(status, "neutral")


def _ago(stamp: str | None) -> str:
    """«12 мин», «3 ч», «2 дн» — сколько прошло. Без секунд: их никто не читает."""
    if not stamp:
        return ""
    started = epoch(stamp)
    if started is None:
        return ""
    delta = max(0.0, time.time() - started)
    if delta < 90:
        return f"{int(delta)} с"
    if delta < 5400:
        return f"{int(delta // 60)} мин"
    if delta < 172800:
        return f"{int(delta // 3600)} ч"
    return f"{int(delta // 86400)} дн"
