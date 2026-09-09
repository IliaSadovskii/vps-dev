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

from .chain import Chain, ChainError, parse as parse_chain
from .db import ABANDONED, BACKLOG, CLOSED, Db, QUEUED, RUNNING, WAIT_REASONS, WAITING, epoch
from .db import DONE as ST_DONE

# Сколько строк показываем, чтобы панель влезала в 64 КиБ и читалась с телефона.
MAX_TASKS = 30
MAX_EVENTS = 10
MAX_COMMENTS = 3

# Статус задачи словами владельца, а не кодом из базы.
STATUS_TEXT = {
    BACKLOG: "в бэклоге",
    QUEUED: "в очереди",
    RUNNING: "едет",
    WAITING: "ждёт вас",
    ST_DONE: "готово",
    CLOSED: "снята",
    ABANDONED: "брошена",
}

# Строка журнала по-русски: владелец открывает журнал, когда что-то пошло не
# так, и код события ему не помощник. Чего нет в карте — показывается кодом.
EVENT_TEXT = {
    "created": "задача заведена",
    "released": "заявка отпущена в работу",
    "aside_closed": "побочная роль закончила с задачей",
    "started": "поехала",
    "prompt_sent": "промпт отправлен роли",
    "gate": "ворота: ждёт решения",
    "button": "кнопка владельца",
    "button_from_cli": "решение из терминала",
    "done": "доведена до конца",
    "closed": "снята владельцем",
    "stopped": "остановлена",
    "no_signal": "ход без сигнала",
    "auto_continue": "попросили закончить ход",
    "error_retry": "сессия в ошибке, попросили продолжить",
    "worker_wake": "будим воркер",
    "wake_gave_up": "воркер не проснулся",
    "question_refused": "вопрос отклонён листом автономии",
    "answered": "владелец ответил в чате",
    "bad_outcome": "исход не из списка",
    "artifact_missing": "файла роли нет или он не той формы",
    "worktree_created": "рабочая копия создана",
    "worktree_failed": "рабочая копия не создалась",
    "branch_held": "ветку держит другая задача",
    "branch_dirty": "в копии ветки есть работа",
    "branch_released": "ветка освобождена",
    "model_not_applied": "модель не встала",
    "session_create_failed": "сессия не создалась",
    "prompt_failed": "промпт не ушёл",
    "run_closed_by_owner": "заход закрыт кнопкой",
    "sheet_edited": "лист автономии изменён",
    "stand_started": "роль поднимает стенд",
    "stand_ready": "стенд поднят",
    "stand_failed": "стенд не поднялся",
    "teardown_started": "роль убирает стенд",
    "teardown_done": "стенд убран",
    "teardown_forced": "стенд добит движком",
    "archived": "сессии в архиве",
    "engine_error": "ошибка движка",
}

# Адрес машины в частной сети владельца: веб-сервис отдаётся на том же номере
# порта, что слушает на 127.0.0.1 (`/var/lib/vps-dev/style/machine/ports.md`).
HOST = "dev-hel1-3.taila4db50.ts.net"

# Файловый менеджер машины (`vps-dev-files.service`, корень — `/`): им и
# открываются файлы ролей. Маршрут AoE `/api/sessions/{id}/file` — служебный,
# он отдаёт JSON; соседний `/artifacts/` отдаёт `text/markdown` без charset и
# ломает кириллицу.
FILES_PORT = 8067


def public(url: str) -> str:
    """Ссылка, по которой владелец откроет это со своего устройства.

    Движок ходит в AoE на `127.0.0.1`, но панель читают снаружи машины, и
    петлевой адрес там не открывается. Номер порта тот же, меняются схема и
    имя хоста.
    """
    from urllib.parse import urlsplit

    parts = urlsplit(url if "//" in url else f"//{url}", scheme="http")
    if parts.hostname not in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
        return url
    port = f":{parts.port}" if parts.port else ""
    tail = url.split(parts.netloc, 1)[1] if parts.netloc in url else ""
    return f"https://{HOST}{port}{tail}"

# Кнопки по причине остановки: что предлагать владельцу, когда задача встала.
BUTTONS_BY_REASON = {
    "gate": ("accept", "back"),
    "no_signal": ("again", "accept_as_is", "back"),
    "max_runs": ("again", "accept_as_is", "back"),
    "loops": ("again", "accept_as_is", "back"),
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

    Секции: что решить, что стоит в очереди и не поехало, что лежит
    в бэклоге, где завести новую. Едущих задач тут нет нарочно — про них
    рассказывает сайдбар (цвет строки, бейдж шага, счётчик у группы);
    готовых и снятых тоже нет: список
    прошлого на обзоре ничего не решает, а место на телефоне отнимает
    (`UX-PLAN.md`). Историю смотрят `orch task list` и сайдбар с архивом.
    """
    blocks: list[dict] = []
    waiting = _sorted_waiting(db)
    backlog = db.tasks((BACKLOG,))

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

    queued = db.tasks((QUEUED,))
    if queued:
        # Задача, ждущая места или занятой ветки, сессии ещё не имеет, а
        # значит её нет и в сайдбаре: не покажи её тут — и она пропадёт из
        # виду совсем (так однажды потерялась заявка на весь вечер).
        rows: list[dict] = []
        for t in queued[:MAX_TASKS]:
            held = _branch_holder(db, t)
            rows.append(
                {
                    "kind": "row",
                    "label": f"{t['id']} · {t['title']}",
                    "sublabel": (
                        f"ждёт ветку: в ней работает {held}" if held else "ждёт свободного места"
                    ),
                    "value": t["branch"] or "",
                    "mono": True,
                }
            )
            rows.append(
                {
                    "kind": "columns",
                    "children": [
                        {
                            "kind": "action",
                            "label": "Снять",
                            "method": "orch.close",
                            "tooltip": "убрать из очереди: задача не поедет",
                            "params": {"task": t["id"], "revision": t["revision"]},
                        }
                    ],
                }
            )
        blocks.append(
            {
                "kind": "section",
                "title": "В очереди",
                "badges": [{"text": str(len(queued))}],
                "children": rows,
            }
        )

    if backlog:
        children: list[dict] = []
        for t in backlog[:MAX_TASKS]:
            # Бэклог — копилка идей, и строк в нём может быть много, поэтому
            # текст заявки не вываливается целиком: первые слова в подписи,
            # весь текст — подсказкой. Заявку мог написать не владелец, и это
            # сказано первым словом подписи.
            text = " ".join((t["text"] or "").split())
            children.append(
                {
                    "kind": "row",
                    "label": f"{t['id']} · {t['title']}",
                    "sublabel": f"{_who_filed(t)} · {text[:140]}" if text else _who_filed(t),
                    "tooltip": text[:800] or "текста нет",
                    "value": t["branch"] or "",
                    "mono": True,
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

    if not blocks:
        blocks.append(
            {"kind": "note", "text": "Ничего не ждёт вашего решения, бэклог пуст."}
        )

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
            "text": "Мастер спросит, что делать; скажите «в бэклог» — запишет "
            "идею без вопросов. То же без панели: в обычной «New session» "
            "напишите orch в поле Group или в названии сессии, либо из "
            "сессии проекта — Ctrl+K, «orch: новая задача».",
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


def _branch_holder(db: Db, task) -> str | None:
    """Кто держит ветку задачи из очереди: одна копия — одна работа."""
    if not task["branch"]:
        return None
    row = db.conn.execute(
        "SELECT id FROM task WHERE branch = ? AND id != ? "
        "AND status IN ('running','waiting') LIMIT 1",
        (task["branch"], task["id"]),
    ).fetchone()
    return row["id"] if row else None


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
    """Слот `pane` в сессии задачи: состояние и решения (`UX-PLAN.md`).

    Сверху то, ради чего панель открывают: что решить и кнопки. Ниже —
    как задача сюда пришла (путь по заходам со ссылками на их сессии), где
    её смотреть (стенд), что почитать (файлы ролей, только существующие),
    что подкрутить (лист автономии). Журнал последним и свёрнутым: он для
    разбора, когда что-то пошло не так.
    """
    chain = _chain(task)
    blocks: list[dict] = [
        {
            "kind": "row",
            "label": task["title"],
            "sublabel": f"{task['id']} · {task['chain']} · ветка {task['branch'] or '—'}",
            "value": STATUS_TEXT.get(task["status"], task["status"]),
            "value_tone": _tone(task["status"]),
            "tooltip": task["worktree_path"] or task["project_path"],
        }
    ]

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
            who = ""
            if chain and chain.has(run["step"]):
                step = chain.step(run["step"])
                who = f"{step.agent} · {step.model}"
            blocks.append(
                {
                    "kind": "row",
                    "label": f"шаг {run['step']}, заход {run['n']}",
                    "sublabel": who or "идёт",
                    "value": _ago(run["started_at"]),
                    "tone": "info",
                }
            )

    if chain:
        blocks.append(
            {
                "kind": "section",
                "title": "Путь задачи",
                "value": " → ".join(db.path_steps(task["id"])) or (task["step"] or "—"),
                "children": _trail_rows(db, task, chain, base_url),
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

    blocks.append(_notify_row(task))
    clash = _clash_note(db, task)
    if clash:
        blocks.append(clash)
    blocks.extend(_note_blocks(db, task))
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
                "href": public(f"{base_url}/session/{wizard}"),
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
                    "label": EVENT_TEXT.get(e["kind"], e["kind"]),
                    "sublabel": _payload_text(e["payload"]),
                    "value": _ago(e["at"]),
                    "tooltip": e["kind"],
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
        # Прошедший шаг молчит: его исход виден в панели задачи и в пути, а в
        # сайдбаре каждая такая строка стоила второй строки высоты — на задаче
        # из восьми шагов это половина экрана ни о чём.
        return {}
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
    if status == CLOSED:
        return {"text": "снята", "tone": "neutral"}
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


def aside_row_badge(роль: str, повод: str = "", идёт: bool = False) -> dict:
    """Слот `row-badge` на строке побочной роли: чем она тут занята.

    Строка роли стоит в сайдбаре среди строк шагов задачи, и без бейджа её
    не отличить от шага: у шага там «review-fixes 7/8», а у роли — пусто.
    """
    if идёт and повод:
        return {"text": повод.lower(), "tone": "info", "tooltip": f"{роль}: идёт ход"}
    return {"text": роль.lower(), "tone": "neutral", "tooltip": f"{роль}: разговор и сводка"}


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


def _cycle_runs(db: Db, task, step: str) -> list:
    """Заходы шага на этом круге — так же, как их считает движок.

    Круг начинается с последнего движения владельца: вернув работу назад, он
    начинает заново, и предел считается от этого места.
    """
    runs = [r for r in db.runs_of_step(task["id"], step) if not r["void_at"]]
    row = db.conn.execute(
        "SELECT at FROM move WHERE task_id = ? AND actor = 'human' ORDER BY id DESC LIMIT 1",
        (task["id"],),
    ).fetchone()
    if row is None:
        return runs
    return [r for r in runs if (r["started_at"] or "") > row["at"]]


def _recent_runs(db: Db, task, сколько: int = 4) -> str:
    """«Как сюда пришли»: последние ходы с исходами, старые слева.

    Без этого владелец видит только «предел заходов» и не знает, что было
    до: какой шаг чем кончился и почему задача оказалась там, где стоит.
    """
    rows = list(db.conn.execute(
        "SELECT step, n, outcome, signalled FROM run WHERE task_id = ? AND void_at IS NULL "
        "ORDER BY id DESC LIMIT ?",
        (task["id"], сколько),
    ))
    if not rows:
        return ""
    куски = [
        f"{r['step']} {r['n']} → {r['outcome'] or ('сдан' if r['signalled'] else 'без сигнала')}"
        for r in reversed(rows)
    ]
    return "Как сюда пришли: " + " · ".join(куски) + "."


def _what_to_decide(db: Db, task) -> str:
    """Строка «что решить» — то, ради чего владелец открыл панель."""
    reason = task["wait_reason"]
    step = task["step"] or "—"
    if reason == "gate":
        # Имя исхода («choice», «ok») — словарь движка, владельцу оно ничего
        # не говорит: что решать, он читает в сообщении роли.
        return (
            f"{_recent_runs(db, task)} ".lstrip() +
            f"Шаг {step} закончил ход и ждёт вас. Что решать — в последнем "
            f"сообщении роли в чате. Там же можно спорить и просить правку: "
            f"роль перепишет свой файл на месте, задача никуда не уедет. "
            f"Кнопка двигает задачу молча; чтобы адресат услышал «почему», "
            f"скажите это роли словами — она передаст."
        )
    if reason == "no_signal":
        answer = _last_orch_answer(db, task)
        tail = f" Последнее, что сказала команда: {answer[:200]}" if answer else ""
        return f"Шаг {step} закончил ход, не сдав его.{tail}"
    if reason == "max_runs":
        сколько = len(_cycle_runs(db, task, step))
        разы = {1: "один раз", 2: "дважды", 3: "трижды"}.get(сколько, f"{сколько} раз")
        return (
            f"Цепочка ведёт на шаг {step}, но на этом круге он уже сходил "
            f"{разы} — больше предел не даёт. {_recent_runs(db, task)} "
            "«Ещё заход» — дать ему заход сверх предела и ехать дальше; "
            "«Принять как есть» — считать сделанное готовым и уйти по цепочке "
            "вперёд; «Вернуть на …» — переиграть с названного шага."
        )
    if reason == "loops":
        return (
            f"Задача третий раз возвращается назад без вашего участия и сейчас "
            f"снова идёт на шаг {step}. {_recent_runs(db, task, 6)} "
            "«Ещё заход» — пусть попробуют ещё круг; «Принять как есть» — "
            "считать сделанное готовым и ехать вперёд; «Вернуть на …» — "
            "переиграть с названного шага."
        )
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


def _notify_row(task) -> dict:
    """Звать ли владельца в Telegram, когда эта задача встанет на воротах."""
    on = bool(task["notify_gates"])
    return {
        "kind": "row",
        "label": "Ворота в Telegram",
        "sublabel": "звать вас в мессенджер, когда задача встанет"
        if on else "задача ждёт молча, решения — в этой панели",
        "value": "звать" if on else "молча",
        "value_tone": "accent" if on else "muted",
        "method": "orch.notify_gates",
        "params": {"task": task["id"], "revision": task["revision"], "on": not on},
    }


def _clash_note(db: Db, task) -> dict | None:
    """Соседняя задача правит те же файлы — сказать до того, как рванёт."""
    for event in db.events(task["id"], limit=30):
        if event["kind"] != "watch_file_clash":
            continue
        payload = json.loads(event["payload"] or "{}")
        files = ", ".join(payload.get("files") or [])
        return {
            "kind": "note",
            "tone": "warn",
            "text": f"задача {payload.get('with')} правит те же файлы: {files}",
        }
    return None


def _note_blocks(db: Db, task) -> list[dict]:
    """Находки побочных ролей, ждущие решения (`ASIDE-PLAN.md` §9).

    Панель — второй канал наравне с Telegram: без привязанного бота роль
    остановила бы задачу, а сказать было бы негде.
    """
    out: list[dict] = []
    мелочь: list[dict] = []
    for note in db.notes(task_id=task["id"]):
        if note["state"] not in ("open", "sent"):
            continue
        if note["severity"] == "log":
            # Мелочь не занимает пол-экрана: строкой, без кнопок. Владельцу
            # она придёт сводкой в конце прогона.
            мелочь.append({
                "kind": "row",
                "label": note["title"],
                "sublabel": (note["body"] or "")[:200],
                "value": "к сведению",
                "value_tone": "muted",
            })
            continue
        options = json.loads(note["options"] or "[]")
        buttons = [{"label": "Ничего не делать", "method": "orch.note",
                    "params": {"note": note["id"], "verb": "continue", "target": ""}}]
        for option in options:
            buttons.append(
                {
                    "label": option.get("label") or option.get("verb"),
                    "method": "orch.note",
                    "params": {
                        "note": note["id"],
                        "verb": option.get("verb"),
                        "target": option.get("target") or "",
                    },
                }
            )
        out.append(
            {
                "kind": "callout",
                "tone": "danger" if note["severity"] == "hold" else "warn",
                "icon": "hand" if note["severity"] == "hold" else "info",
                "title": note["title"],
                "detail": (note["body"] or "")[:1200],
                "actions": buttons,
            }
        )
    if мелочь:
        out.append({
            "kind": "section",
            "title": f"Замечания наладчика ({len(мелочь)})",
            "children": мелочь,
        })
    return out


def _stand_row(db: Db, task) -> dict:
    """Стенд задачи: ссылка, «поднимается» или кнопка.

    Поднимает окружение роль «Стенд», а не движок: у каждого проекта свой
    способ, и знает его проект, а не оркестратор (`UX-PLAN.md`).
    """
    stand = task["stand"] if "stand" in task.keys() else None
    port = task["stand_port"] if "stand_port" in task.keys() else None
    row = db.conn.execute(
        "SELECT r.session_id FROM aside a JOIN aside_run r ON r.aside_id = a.id "
        "WHERE a.name = 'stand' AND a.scope_key = ? AND a.status = 'live' "
        "AND r.ended_at IS NULL ORDER BY r.id DESC LIMIT 1",
        (task["id"],),
    ).fetchone()
    session = row["session_id"] if row else None
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
    failed = _last_stand_error(db, task)
    return {
        "kind": "action",
        "label": "Поднять стенд снова" if failed else "Поднять стенд",
        "method": "orch.stand",
        "icon": "play",
        "tooltip": (
            f"прошлый раз не вышло: {failed[:160]}"
            if failed
            else "роль поднимет окружение задачи на своих портах"
        ),
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
            outcomes = _outcomes_of(chain, task)
            targets = list(outcomes.values())
            for outcome, target in outcomes.items():
                # Имя исхода владельцу ничего не говорит и появляется только
                # там, где без него две кнопки стали бы одинаковыми.
                same = targets.count(target) > 1
                where = f"{step_title(target)}" + (f" ({outcome})" if same else "")
                actions.append(
                    {
                        "kind": "action",
                        "label": f"Считать ход законченным → {where}",
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
                # Две кнопки на шаг: «с памятью» — шаг продолжит свою прошлую
                # сессию, а файлы нижних шагов останутся на месте; «начисто» —
                # всё, что задача сделала после этого шага, забывается
                # (`forget_after`). Выбор владельца, а не движка: он один
                # знает, правка это или переигранное решение.
                for clean in (False, True):
                    actions.append(
                        {
                            "kind": "action",
                            "label": (
                                f"Вернуть на «{step_title(target)}» начисто"
                                if clean
                                else f"Вернуть на «{step_title(target)}»"
                            ),
                            "method": "orch.back_clean" if clean else "orch.back",
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
            row["href"] = public(f"{base_url}/session/{run['session_id']}")
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


def step_title(step_id: str) -> str:
    """Имя роли словами — из заголовка её файла.

    Владельцу `review-fixes` ничего не говорит, «Правки» говорит. Держать
    второй список имён в движке незачем: заголовок роли и есть её имя.
    """
    from .chain import prompts_dir

    path = prompts_dir() / f"role-{step_id}.md"
    try:
        first = path.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return step_id
    return first.lstrip("# ").strip() or step_id


def _after_text(after) -> str:
    """Ворота словами: «ждать/не ждать» не покрывает ворота на исходе."""
    if after is True:
        return "ждать всегда"
    if after:
        return "ждать после " + ", ".join(after)
    return "не ждать"


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
                "sublabel": "пройден" if done_already else "ворота после · вопросы внутри",
                "value": f"{_after_text(after)} · {'можно' if ask else 'нельзя'}",
                "tooltip": (
                    "шаг уже пройден"
                    if done_already
                    else "щелчок переключает по кругу: ничего → ворота → вопросы → и то и другое"
                ),
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


def file_url(path: Path) -> str:
    """Ссылка на файл в файловом менеджере машины."""
    from urllib.parse import quote

    return f"https://{HOST}:{FILES_PORT}/files{quote(str(path))}"


def _artifact_links(db: Db, task, chain: Chain | None, session_id: str, base: str) -> list[dict]:
    """Файлы ролей, которые уже написаны; файл текущего шага первым.

    Ссылка на ещё не написанный файл открывала бы пустую страницу, а
    владельцу на воротах нужен один файл — той роли, что только что сдала
    ход. Единственное место, где панель смотрит на диск, а не в базу.
    """
    if not chain:
        return []
    root = Path(task["worktree_path"] or task["project_path"]) / ".orch" / task["id"] / "artifacts"
    rows = []
    for step in chain.steps:
        for name in step.artifact:
            if not (root / name).is_file():
                continue
            current = step.id == task["step"]
            rows.append(
                {
                    "kind": "row",
                    "label": name,
                    "sublabel": f"{step.id} · текущий шаг" if current else step.id,
                    "href": file_url(root / name),
                    "mono": True,
                    "tone": "info" if current else None,
                }
            )
    rows.sort(key=lambda r: 0 if r["tone"] == "info" else 1)
    return [{k: v for k, v in r.items() if v is not None} for r in rows]


def _payload_text(payload: str | None) -> str:
    """Полезная часть события одной строкой: без скобок и кавычек."""
    try:
        data = json.loads(payload or "{}")
    except json.JSONDecodeError:
        return (payload or "")[:100]
    if not isinstance(data, dict):
        return str(data)[:100]
    parts = []
    for key, value in data.items():
        if isinstance(value, dict):
            value = ", ".join(str(v) for v in value.values())
        elif isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        parts.append(f"{key}: {value}")
    return ", ".join(parts)[:100]


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
        CLOSED: "neutral",
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
