"""Содержимое панелей плагина: чистые функции от состояния базы.

Панель — функция состояния, а не поток событий: каждый проход движка рисует
её заново, кнопки несут ревизию задачи, устаревшая кнопка отклоняется
(`PLAN.md` §8). Здесь нет ни одного вызова AoE и ни одной записи — только
чтение базы и складывание блоков.
"""

from __future__ import annotations

import json
import time
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


# ── главная панель ───────────────────────────────────────────────────────
def home_pane(db: Db, draft: dict | None = None, cost_warn: float = 5.0) -> dict:
    """Слот `home-pane` «Задачи»: что решить, что едет, что ждёт очереди."""
    if draft is not None:
        return new_task_pane(draft)

    blocks: list[dict] = []
    waiting = _sorted_waiting(db)
    running = db.tasks((RUNNING,))
    queued = db.tasks((QUEUED,))
    backlog = db.tasks((BACKLOG,))
    done = db.tasks((ST_DONE,))[-MAX_DONE:]
    lost = db.tasks((ABANDONED,))

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

    if running:
        blocks.append(
            {
                "kind": "section",
                "title": "Едут",
                "badges": [{"text": str(len(running))}],
                "children": [_running_row(db, t, cost_warn) for t in running[:MAX_TASKS]],
            }
        )
    if queued:
        blocks.append(
            {
                "kind": "section",
                "title": "Очередь",
                "badges": [{"text": str(len(queued))}],
                "children": [
                    {
                        "kind": "row",
                        "label": f"{t['id']} · {t['title']}",
                        "sublabel": "ждёт свободного места",
                        "tone": "neutral",
                    }
                    for t in queued[:MAX_TASKS]
                ],
            }
        )
    if backlog:
        blocks.append(
            {
                "kind": "section",
                "title": "Бэклог",
                "badges": [{"text": str(len(backlog))}],
                "collapsible": True,
                "collapsed": True,
                "children": [
                    {
                        "kind": "row",
                        "label": f"{t['id']} · {t['title']}",
                        "value": "Запустить",
                        "method": "orch.start",
                        "params": {"task": t["id"], "revision": t["revision"]},
                    }
                    for t in backlog[:MAX_TASKS]
                ],
            }
        )
    if lost:
        blocks.append(
            {
                "kind": "section",
                "title": "Брошены",
                "badges": [{"text": str(len(lost)), "tone": "danger"}],
                "children": [
                    {
                        "kind": "row",
                        "label": f"{t['id']} · {t['title']}",
                        "sublabel": "сессия исчезла",
                        "tone": "danger",
                    }
                    for t in lost[:MAX_TASKS]
                ],
            }
        )
    if done:
        blocks.append(
            {
                "kind": "section",
                "title": "Готово",
                "collapsible": True,
                "collapsed": True,
                "children": [
                    {
                        "kind": "row",
                        "label": f"{t['id']} · {t['title']}",
                        "value": _ago(t["closed_at"]),
                        "tone": "success",
                    }
                    for t in reversed(done)
                ],
            }
        )

    if not blocks:
        blocks.append({"kind": "note", "text": "Задач нет. Заведите первую."})

    blocks.append(
        {
            "kind": "action",
            "label": "Новая задача",
            "method": "orch.new_task",
            "variant": "primary",
            "icon": "plus",
        }
    )
    return {
        "title": "orch",
        "default_location": "right",
        "icon": "list-checks",
        "blocks": blocks,
        "footer": _footer(db, waiting, running),
    }


def _footer(db: Db, waiting: list, running: list) -> dict:
    if waiting:
        return {
            "text": "нужно ваше решение",
            "value": str(len(waiting)),
            "tone": "danger",
            "icon": "hand",
        }
    if running:
        return {"text": "едут", "value": str(len(running)), "tone": "info", "icon": "play"}
    return {"text": "тихо", "value": "0", "tone": "neutral"}


def _waiting_row(db: Db, task) -> dict:
    return {
        "kind": "row",
        "label": f"{task['id']} · {task['title']}",
        "sublabel": _reason_text(task["wait_reason"]),
        "value": _ago(_state_since(db, task)),
        "tone": "danger",
        "badges": [{"text": task["step"] or "—"}],
        "method": "orch.focus",
        "params": {"task": task["id"], "revision": task["revision"]},
    }


def _running_row(db: Db, task, cost_warn: float) -> dict:
    chain = _chain(task)
    step = None
    if chain and task["step"]:
        try:
            step = chain.step(task["step"])
        except ChainError:
            step = None
    badges = [{"text": task["step"] or "—"}]
    if step:
        badges.append({"text": f"{step.agent}/{step.model}"})
    cost = _last_cost(db, task["id"])
    if cost and cost >= cost_warn:
        badges.append({"text": f"${cost:.0f}", "tone": "warn", "tooltip": "дорогой ход"})
    return {
        "kind": "row",
        "label": f"{task['id']} · {task['title']}",
        "sublabel": f"идёт {_ago(_state_since(db, task))}",
        "tone": "info",
        "badges": badges,
    }


# ── панель задачи в сессии ───────────────────────────────────────────────
def task_pane(
    db: Db,
    task,
    session_id: str,
    base_url: str,
    cost_warn: float = 5.0,
    comment: str | None = None,
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
                "kind": "row",
                "label": "путь",
                "sublabel": _trail(db, task, chain),
                "mono": True,
            }
        )

    if comment:
        blocks.append(
            {
                "kind": "note",
                "tone": "info",
                "text": f"Комментарий к следующему движению: «{comment[:300]}»",
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


def composer_action(task, draft_open: bool = False, clear_op: dict | None = None) -> dict:
    """Кнопка у поля ввода.

    Она же — единственный способ передать оркестратору свободный текст без
    участия модели, поэтому висит в каждой сессии, а не только в сессиях
    задач: в чужой сессии ею набирают текст новой задачи.
    """
    if draft_open:
        payload = {
            "label": "Взять этот текст в задачу",
            "method": "orch.move_with_text",
            "icon": "clipboard-paste",
            "tooltip": "Текст из поля станет постановкой новой задачи",
        }
    elif task is None:
        payload = {
            "label": "Новая задача с этим текстом",
            "method": "orch.new_task",
            "icon": "plus",
            "tooltip": "Открыть лист автономии и взять текст из поля ввода",
        }
    else:
        payload = {
            "label": "Двинуть с этим текстом",
            "method": "orch.move_with_text",
            "icon": "arrow-right",
            # Кнопка не двигает сама: у клика по кнопке панели черновика нет
            # (хост отдаёт его только кнопке у поля ввода), поэтому текст
            # сначала прикрепляется, а движение выбирается кнопкой в панели.
            "tooltip": "Прикрепить текст к следующему движению задачи",
            "disabled": task["status"] not in (WAITING, RUNNING),
        }
    # Очистка поля ввода живёт в той же полезной нагрузке, что и кнопка:
    # отдельная посылка тут же затирается обычной перерисовкой, и браузер
    # успевает увидеть только вторую. Хост применяет каждую операцию по её
    # `id` ровно один раз, поэтому висеть она может сколько угодно проходов.
    if clear_op:
        payload["draft_operation"] = clear_op
    return payload


# ── лист автономии новой задачи ──────────────────────────────────────────
def new_task_pane(draft: dict) -> dict:
    """Лист автономии перед запуском: переключатели на каждый шаг."""
    blocks: list[dict] = [
        {"kind": "heading", "text": "Новая задача"},
        {
            "kind": "note",
            "tone": "info" if draft.get("text") else "warn",
            "text": draft.get("text", "")[:400]
            or (
                "Текста нет. Напишите задачу в поле ввода и нажмите там "
                "«Двинуть с этим текстом» — текст попадёт сюда."
            ),
        },
        {
            "kind": "row",
            "label": "цепочка",
            "value": draft.get("chain", "deep"),
            "mono": True,
        },
        {
            "kind": "row",
            "label": "проект",
            "value": draft.get("project_path", "—"),
            "mono": True,
        },
        {"kind": "divider"},
        {"kind": "heading", "text": "Лист автономии"},
    ]
    for step, knobs in draft.get("sheet", {}).items():
        blocks.append(
            {
                "kind": "row",
                "label": step,
                "sublabel": "ворота после шага",
                "value": "ждать" if knobs.get("after") else "не ждать",
                "value_tone": "warn" if knobs.get("after") else "neutral",
                "method": "orch.sheet_toggle",
                "params": {"step": step, "knob": "after"},
            }
        )
        blocks.append(
            {
                "kind": "row",
                "label": "",
                "sublabel": "вопросы владельцу внутри шага",
                "value": "можно" if knobs.get("ask") else "нельзя",
                "value_tone": "info" if knobs.get("ask") else "neutral",
                "method": "orch.sheet_toggle",
                "params": {"step": step, "knob": "ask"},
            }
        )
    blocks += [
        {"kind": "divider"},
        {
            "kind": "columns",
            "children": [
                {
                    "kind": "action",
                    "label": "Запустить",
                    "method": "orch.launch",
                    "variant": "primary",
                    "disabled": not draft.get("text"),
                },
                {"kind": "action", "label": "В бэклог", "method": "orch.backlog",
                 "disabled": not draft.get("text")},
            ],
        },
        {"kind": "action", "label": "Отмена", "method": "orch.cancel_new"},
    ]
    return {
        "title": "orch",
        "default_location": "right",
        "icon": "plus",
        "blocks": blocks,
    }


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
    if reason == "no_worker":
        return f"У сессии шага {step} не поднялся агент. Ещё заход заведёт новую сессию."
    return f"Шаг {step} ждёт вас."


def _buttons(db: Db, task) -> list[dict]:
    reason = task["wait_reason"] or ""
    chain = _chain(task)
    actions: list[dict] = []
    for action in BUTTONS_BY_REASON.get(reason, ("again",)):
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
