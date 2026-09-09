"""Побочные роли со стороны движка: поводы, ходы, сдача хода.

Устройство — `ASIDE-PLAN.md` §2 и §6. Движок публикует события в `event`,
роль подписана на их виды; проход читает новые события старше курсора роли
и заводит ход. Курсор двигается в той же транзакции, что и запись хода:
падение между проходами не теряет повод и не заводит его дважды.

Побочные ходы разбираются последними в проходе: шаг цепочки всегда важнее
наблюдателя, и место под сессию он занимает первым.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from . import asides as spec_mod
from . import digest as dg
from .aoe import RUNNING, STARTING, WAITING, Aoe, AoeError, Session
from .asides import Aside, Wake
from .chain import prompts_dir
from .db import LIVE, STATE_DIR, now
from .naming import GROUP_ROOT, slug
from .workspace import create_worktree


def aside_title(spec: Aside, task_id: str | None) -> str:
    """Титул сессии роли: `🔧 T35 · Наладчик`.

    Порядок тот же, что у сессий шагов (`T35 · plan`): номер задачи первым,
    иначе строки роли и шагов читаются как из разных систем. Знак роли стоит
    перед номером — по нему в общем списке видно наблюдателя, а не шаг.
    """
    имя = f"{task_id or 'машина'} · {spec.title or spec.name}"
    return f"{spec.icon} {имя}".strip()


# Сколько событий одна роль разбирает за проход: движок не должен зависать
# на журнале, накопившемся, пока роль была выключена.
BATCH = 20


class AsideMixin:
    # ── проход ───────────────────────────────────────────────────────────
    def pump_asides(self, sessions: dict[str, Session]) -> None:
        """Довести побочные ходы и завести новые по накопившимся поводам."""
        self.watch_aside_runs(sessions)
        self.sweep_aside_sessions(sessions)
        for spec in self.aside_specs():
            try:
                self.pump_aside(spec)
            except Exception as exc:  # noqa: BLE001 — одна роль не роняет проход
                self.db.event(None, "aside_error", {"aside": spec.name, "error": repr(exc)[:400]})

    def aside_specs(self) -> list[Aside]:
        """Включённые роли. Стенд сюда не входит: у него свой повод — кнопка."""
        return spec_mod.enabled()

    def pump_aside(self, spec: Aside) -> None:
        seq = self.db.cursor_of(spec.name, "")
        if seq < 0:
            # Роль включили на живой машине: журнал за прошлое не разбираем,
            # иначе первый проход поднял бы сотню ходов о давно закрытых
            # задачах. Курсор просто встаёт на сегодня.
            with self.db.tx():
                self.db.cursor_set(spec.name, "", self.db.last_seq())
            return
        rows = self.db.events_after(seq, spec.kinds(), limit=BATCH)
        if not rows:
            return
        for event in rows:
            wake = spec.wake_for(event["kind"])
            try:
                verdict = self.aside_wake(spec, wake, event) if wake else "skip"
            except Exception as exc:  # noqa: BLE001
                # Событие, на котором роль спотыкается, курсор всё-таки
                # проходит: иначе одна кривая запись встала бы намертво и
                # роль не увидела бы больше ничего.
                with self.db.tx():
                    self.db.event(
                        event["task_id"], "aside_wake_failed",
                        {"aside": spec.name, "kind": event["kind"], "error": repr(exc)[:300]},
                    )
                verdict = "skip"
            if verdict == "defer":
                # Роль занята, нет места или выбран бюджет: повод остаётся
                # за курсором и дождётся следующего прохода
                # (`ASIDE-PLAN.md` §2 и §10). Дальше по журналу не идём —
                # порядок событий для роли важен.
                return
            with self.db.tx():
                self.db.cursor_set(spec.name, "", int(event["seq"]))

    def aside_wake(self, spec: Aside, wake: Wake, event) -> str:
        """Один повод: проверить уместность и завести ход.

        Возвращает `done` (ход заведён), `skip` (повод роли не подходит) или
        `defer` (сейчас нельзя — повод должен дождаться следующего прохода).
        """
        task = self.db.task(event["task_id"]) if event["task_id"] else None
        key = self.aside_key(spec, task, event)
        if key is None:
            return "skip"
        if task is not None and not spec.fits_chain(task["chain"]):
            return "skip"
        if task is not None and spec.scope in ("run", "task") and task["status"] not in LIVE:
            # Задача уже закрыта: наблюдать за ней нечего, кроме ролей,
            # которые именно на закрытие и подписаны.
            # Ответ владельца доходит всегда: он мог написать, когда задача
            # уже кончилась, и молча терять его слова нельзя.
            if event["kind"] not in ("done", "closed", "note_decided"):
                return "skip"

        if task is not None and event["kind"] in ("done", "closed") and not self.db.conn.execute(
            "SELECT 1 FROM run WHERE task_id = ? LIMIT 1", (task["id"],)
        ).fetchone():
            # Задачу закрыли, ни разу не запустив (карточка долга из
            # бэклога). Подводить итог нечему, помнить нечего: сводка и
            # записка о такой задаче — сожжённые сессии и лишний шум в
            # сайдбаре (T25).
            return "skip"
        aside_id = self.db.aside_live(spec.name, key)
        aside_id = int(aside_id["id"]) if aside_id else None
        if aside_id is not None and self.aside_live_runs(aside_id) >= spec.limit("max_live", 1):
            # Роль занята прошлым ходом. Повод ждёт: курсор через него не
            # переступает, иначе вопрос второй задачи пропал бы навсегда.
            self.note_once(
                event["task_id"], "aside_busy",
                {"aside": spec.name, "kind": event["kind"]}, 300.0,
            )
            return "defer"
        if aside_id is not None and not self.aside_budget_ok(spec, aside_id, event["task_id"]):
            return "skip"
        if aside_id is not None and not self.aside_session_free(spec, wake, aside_id, event):
            return "defer"
        if not self.capacity(event["task_id"], f"роль {spec.name}"):
            return "defer"

        token = uuid.uuid4().hex[:12]
        with self.db.tx():
            aside_id = self.db.aside_open(spec.name, spec.scope, key, event["task_id"])
            run_id = self.db.aside_run_start(
                aside_id, wake.prompt, int(event["seq"]), token, event["task_id"]
            )
            self.db.event(
                event["task_id"],
                "aside_started",
                {"aside": spec.name, "wake": wake.prompt, "cause": event["kind"], "run": run_id},
            )
        self.aside_send(spec, wake, aside_id, run_id, event)
        return "done"

    def aside_session_free(self, spec: Aside, wake: Wake, aside_id: int, event) -> bool:
        """Можно ли слать повод в общую переписку роли прямо сейчас.

        Промпт в занятую сессию AoE доставляется как `steer` и обрывает то,
        что в ней идёт. В общей переписке роли сидит владелец, поэтому повод
        ждёт, пока переписка освободится, а не влезает в разговор. Повод не
        теряется: курсор через него не переступает.
        """
        if wake.session != "shared":
            return True
        aside = self.db.aside(aside_id)
        sid = aside["session_id"] if aside is not None else None
        if not sid:
            return True
        session = self.aoe.session(sid)
        # Занята = идёт ход. `Waiting` (роль ждёт ответа или разрешения) сюда
        # не входит: такой промпт мост кладёт в очередь, а не рвёт им ход.
        if session is None or session.status not in (STARTING, RUNNING):
            return True
        self.note_once(
            event["task_id"], "aside_session_busy",
            {"aside": spec.name, "kind": event["kind"], "status": session.status}, 300.0,
        )
        return False

    def aside_key(self, spec: Aside, task, event) -> str | None:
        """Область роли: задача, проект или машина целиком."""
        if spec.scope == "machine":
            return "machine"
        if task is None:
            return None
        if spec.scope == "project":
            return task["project_path"]
        return task["id"]

    def aside_live_runs(self, aside_id: int) -> int:
        return len(
            [r for r in self.db.aside_runs_of(aside_id) if not r["ended_at"]]
        )

    def aside_budget_ok(self, spec: Aside, aside_id: int, task_id: str | None) -> bool:
        """Бюджет роли: сколько ходов и сколько денег ей отпущено."""
        # Считаем ходы про эту задачу: у роли с областью «проект» запись
        # одна на весь проект, и общий счёт молча заткнул бы её навсегда.
        runs = self.db.aside_runs_of(aside_id, task_id)
        limit = spec.limit("runs_per_task", 40)
        if len(runs) >= limit:
            self.note_once(
                task_id, "aside_budget",
                {"aside": spec.name, "runs": len(runs), "limit": limit}, 3600.0,
            )
            return False
        cap = spec.limit("cost_usd", 0)
        spent = sum(float(r["cost_usd"] or 0) for r in runs)
        if cap and spent >= cap:
            self.note_once(
                task_id, "aside_budget",
                {"aside": spec.name, "cost_usd": round(spent, 2), "limit": cap}, 3600.0,
            )
            return False
        return True

    def may_hold(self, spec: Aside | None) -> bool:
        return spec is not None and spec.may("hold")

    # ── ход роли ─────────────────────────────────────────────────────────
    def aside_send(self, spec: Aside, wake: Wake, aside_id: int, run_id: int, event) -> None:
        """Внешняя часть: сессия и промпт. Повторяется по ключу идемпотентности."""
        task = self.db.task(event["task_id"]) if event["task_id"] else None
        path = self.aside_path(spec, task)
        if path is None:
            self.db.event(event["task_id"], "aside_failed", {"aside": spec.name, "why": "нет копии"})
            with self.db.tx():
                self.db.aside_run_end(run_id, "no_workspace")
            return
        run = self.db.aside_run(run_id)
        aside = self.db.aside(aside_id)
        свежая = wake.session == "fresh"
        session = None
        if not свежая and aside is not None and aside["session_id"]:
            # Одна сессия на задачу: роль просыпается новым промптом в свою
            # же переписку. Так у неё есть память о прошлых ходах, а у
            # владельца — одна карточка в сайдбаре вместо десятка.
            session = self.aoe.session(aside["session_id"])
        # Повод с `session: fresh` идёт в свою сессию: разбор хода длинный, а
        # общая переписка — место, где с ролью разговаривает владелец. Промпт
        # в занятую сессию AoE обрывает то, что в ней идёт, поэтому разбор и
        # разговор разведены по разным сессиям, а не по вежливости промпта.
        повод = self.wake_title(spec, event["kind"])
        титул = aside_title(spec, event["task_id"])
        if свежая:
            титул = f"{титул} · {повод.lower()}"
        try:
            session = session or self.aoe.create(
                path=str(path),
                agent=wake.agent,
                model=wake.model,
                effort=wake.effort,
                title=титул,
                group=(task["group_path"] if task is not None else None) or f"{GROUP_ROOT}/побочные",
                # Номер хода в ключе: повтор после умершей сессии должен
                # завести новую, а не получить обратно мёртвую по старому
                # ключу. Внутри одного хода ключ постоянен — за это
                # идемпотентность и держат.
                idempotency_key=(
                    f"aside/{spec.name}/run/{run_id}" if свежая
                    else f"aside/{spec.name}/{aside_id}"
                ),
            )
        except AoeError as exc:
            self.db.event(
                event["task_id"], "aside_failed", {"aside": spec.name, "error": str(exc)[:300]}
            )
            return
        if session is None:
            self.db.event(
                event["task_id"], "aside_failed",
                {"aside": spec.name, "why": "сессия не создалась"},
            )
            return
        self.aoe.apply_model(session.id, wake.model)
        text = self.aside_prompt(spec, wake, run, task, event)
        try:
            self.aoe.prompt(session.id, text)
        except AoeError as exc:
            self.db.event(
                event["task_id"], "aside_failed", {"aside": spec.name, "error": str(exc)[:300]}
            )
            return
        with self.db.tx():
            self.db.aside_run_sent(run_id, session.id)
            # Сессия разбора живёт один повод и общей перепиской роли не
            # становится: иначе следующий повод и владелец снова оказались бы
            # в одной сессии, а разводили их как раз ради этого.
            if not свежая and (aside is None or aside["session_id"] != session.id):
                self.db.conn.execute(
                    "UPDATE aside SET session_id = ? WHERE id = ?", (session.id, aside_id)
                )
        # Сводку конца прогона владелец должен прочитать: AoE пришлёт пуш,
        # когда роль допишет её и сессия встанет в `Idle`. Остальные ходы
        # роли молчат — иначе пуш на каждый шаг.
        self.aoe.set_notify(session.id, wake.attention)
        self.aoe.set_color(session.id, "blue")
        # Роль стоит в группе задачи вперемешку с её шагами; закрепляем наверху,
        # чтобы наблюдателя было видно, не разглядывая список.
        self.aoe.set_pinned(session.id, True)
        if свежая:
            self.aside_home(spec, aside_id, task, path)

    def aside_home(self, spec: Aside, aside_id: int, task, path: Path) -> None:
        """Общая переписка роли: карточка, в которой с ней говорит владелец.

        Заводится вместе с первым ходом роли на задаче и живёт до конца
        прогона. Без неё роли в сайдбаре не видно вовсе: поводы разбора идут в
        своих сессиях и уезжают в архив, как только ход сдан, а общая
        переписка раньше появлялась только с первым поводом `session: shared`
        — у Наладчика это конец прогона.

        Заводка несёт общие правила: первое слово владельца иначе прилетело
        бы агенту, который не знает ни кто он, ни как отвечать движку.
        """
        aside = self.db.aside(aside_id)
        if aside is None or aside["session_id"]:
            return
        дом = next((w for w in spec.wakes if w.session == "shared"), None)
        if дом is None:
            # Роль, которая с владельцем не разговаривает: и заводить нечего.
            return
        if not self.capacity(aside["task_id"], f"переписка роли {spec.name}"):
            return
        try:
            session = self.aoe.create(
                path=str(path),
                agent=дом.agent,
                model=дом.model,
                effort=дом.effort,
                title=aside_title(spec, aside["task_id"]),
                group=(task["group_path"] if task is not None else None)
                or f"{GROUP_ROOT}/побочные",
                idempotency_key=f"aside/{spec.name}/{aside_id}",
            )
        except AoeError as exc:
            self.db.event(
                aside["task_id"], "aside_failed",
                {"aside": spec.name, "why": "переписка", "error": str(exc)[:300]},
            )
            return
        if session is None:
            return
        try:
            self.aoe.prompt(session.id, self.aside_home_prompt(spec, task))
        except AoeError as exc:
            self.db.event(
                aside["task_id"], "aside_failed",
                {"aside": spec.name, "why": "переписка", "error": str(exc)[:300]},
            )
            return
        with self.db.tx():
            self.db.conn.execute(
                "UPDATE aside SET session_id = ?, greeted_at = ? WHERE id = ?",
                (session.id, now(), aside_id),
            )
            self.db.event(
                aside["task_id"], "aside_home",
                {"aside": spec.name, "session": session.id},
            )
        self.aoe.set_notify(session.id, False)
        self.aoe.set_color(session.id, "blue")
        self.aoe.set_pinned(session.id, True)

    def aside_home_prompt(self, spec: Aside, task) -> str:
        """Заводка общей переписки: общие правила и чем эта переписка занята."""
        parts = []
        for name in spec.includes:
            common = prompts_dir() / f"{name}.md"
            if common.exists():
                parts.append(common.read_text(encoding="utf-8").strip())
        куда = f"задачей {task['id']} («{task['title']}»)" if task is not None else "машиной"
        parts.append(
            "# Эта переписка\n\n"
            f"Ты приставлена к {куда}. Здесь с тобой разговаривает владелец: "
            "спрашивает, что ты видишь, и решает по твоим находкам.\n\n"
            "Разбор каждого хода идёт не здесь, а в отдельной сессии на повод — "
            "она заводится сама и уезжает в архив, как только ход сдан. Сюда "
            "движок приведёт тебя на ответ владельца и на сводку в конце прогона.\n\n"
            "Отвечать сейчас нечего: работы тебе не дано, хода у тебя нет "
            "(команды `orch aside` без номера хода не работают). Скажи одной "
            "строкой, что ты на месте, и жди."
        )
        return "\n\n".join(parts)

    def aside_path(self, spec: Aside, task) -> Path | None:
        """Где роль работает: копия задачи, своя копия, или всё равно где."""
        if spec.workspace.startswith("worktree:"):
            # Своя копия проекта: наблюдатель, правящий то, по чему едет
            # прогон, испортил бы собственные показания (`ASIDE-PLAN.md` §7).
            project = Path(spec.workspace[9:]).expanduser()
            if not project.is_dir():
                return None
            path, error = create_worktree(project, f"aside/{spec.name}")
            if error:
                self.db.event(None, "aside_failed", {"aside": spec.name, "error": error[:300]})
                return None
            return path
        if spec.workspace.startswith("repo:"):
            path = Path(spec.workspace[5:]).expanduser()
            return path if path.is_dir() else None
        if spec.workspace == "none":
            root = Path(self.settings.projects_dir)
            return root if root.is_dir() else Path.home()
        if task is None:
            return None
        path = Path(task["worktree_path"] or task["project_path"])
        return path if path.is_dir() else None

    def aside_prompt(self, spec: Aside, wake: Wake, run, task, event) -> str:
        """Промпт повода плюс блок «Что случилось»."""
        # Сессия у роли одна на задачу, и переписка перед глазами: слать
        # общие правила и текст роли на каждый повод значит платить за них
        # заново каждый ход. Полный текст идёт, только пока он новый для этой
        # переписки; дальше — короткая шапка и «что случилось».
        # Считается по этой переписке, а не по всем ходам роли: ходы с
        # `session: fresh` шли в свои сессии, и их «уже читала выше» здесь
        # было бы неправдой.
        aside = self.db.aside(int(run["aside_id"]))
        сюда = (aside["session_id"] or "") if aside is not None else ""
        было = [
            r["wake"] for r in self.db.aside_runs_of(int(run["aside_id"]))
            if int(r["id"]) != int(run["id"]) and сюда and r["session_id"] == сюда
        ] if wake.session != "fresh" else []
        # Общие правила уехали в эту переписку при её заводке.
        правила_были = bool(было) or (
            wake.session != "fresh" and aside is not None and bool(aside["greeted_at"])
        )
        parts = []
        if not правила_были:
            for name in spec.includes:
                common = prompts_dir() / f"{name}.md"
                if common.exists():
                    parts.append(common.read_text(encoding="utf-8").strip())
        path = prompts_dir() / f"{wake.prompt}.md"
        if path.exists() and wake.prompt not in было:
            parts.append(path.read_text(encoding="utf-8").strip())
        elif path.exists():
            parts.append(
                f"# {wake.title or wake.prompt}\n\n"
                "Правила этой работы ты уже читала выше в этой переписке "
                f"(«{wake.title or wake.prompt}») — держись их."
            )
        parts.append(self.aside_context(spec, run, task, event, кратко=bool(было)))
        if wake.session == "fresh":
            # Сессия повода уедет в архив, как только ход сдан: то, что роль
            # сказала только в чат, там и останется. Значит найденное надо
            # класть находкой — только оттуда его возьмёт сводка.
            parts.append(
                "Эта переписка заведена под один повод и уйдёт в архив, как только "
                "ты сдашь ход. Всё, что должно дожить до конца прогона, клади "
                "находкой (`orch aside note`) — сказанное только в чат потеряется."
            )
        return "\n\n".join(parts)

    def aside_context(self, spec: Aside, run, task, event, кратко: bool = False) -> str:
        """Что случилось. В первый раз — со всей справкой, дальше коротко.

        Справочное (где лежит задача, как смотреть ход, какие права) роль
        прочитала в начале переписки и видит его выше. Повторять это на
        каждом шаге значит платить за одно и то же по десять раз.
        """
        payload = json.loads(event["payload"] or "{}")
        повод = self.wake_title(spec, event["kind"])
        шаг = payload.get("step") or (task["step"] if task is not None else "")
        заход = payload.get("n")
        где = f"Шаг `{шаг}`" + (f", заход {заход}" if заход else "") if шаг else ""

        if кратко:
            строки = ["# Что случилось", "", f"**{повод}.** {где}".rstrip(". ") + "."]
            строки.append(
                f"Твой ход `A{run['id']}`, пропуск `{run['token'] or ''}`. "
                "Правила ты знаешь — действуй."
            )
            # Пять строк на каждый повод дешевле, чем роль, забывшая к
            # десятому шагу, что находка бывает только с последствием.
            строки += [
                "",
                "Коротко, чтобы не сбиться: находка — только когда из-за неё ход "
                "пошёл иначе; без флага она копится до сводки, `--hold` останавливает "
                "прогон; сама ничего не правишь и не двигаешь; чисто — молчи; "
                f"ход закончи `orch aside done --id A{run['id']} --pass {run['token'] or ''}`.",
            ]
            хвост = self.short_tail(spec, task, payload, шаг, заход)
            if хвост:
                строки += ["", хвост]
            # Итог собирают и в переписке, где роль уже ходила: лента прошлых
            # задач нужна ему и там.
            прошлое = self.notes_history(spec, task, self.wake_history(spec, run))
            if прошлое:
                строки += ["", прошлое]
            return "\n".join(строки)

        lines = [
            "# Что случилось",
            "",
            f"**{повод}.** {где}".rstrip(". ") + ".",
            f"Твой ход: `A{run['id']}`, пропуск `{run['token'] or ''}`.",
            "Команды `orch aside` требуют оба: "
            f"`--id A{run['id']} --pass {run['token'] or ''}`. У каждого хода они свои, "
            "новые придут вместе с новым поводом. Пропуск никому не показывай.",
        ]
        if task is not None:
            папка = Path(task["worktree_path"] or task["project_path"]) / ".orch" / task["id"]
            lines += [
                "",
                f"Задача {task['id']}: {task['title']}",
                f"Цепочка: `{task['chain']}`. Проект: `{task['project_path']}`",
                f"Рабочая копия задачи: `{task['worktree_path'] or task['project_path']}`",
                f"Папка задачи: `{папка}` — внутри `prompts/` (задания шагов), "
                "`artifacts/` (файлы ролей), `logs/`, `chain.yml` (замороженная цепочка).",
            ]
        lines += ["", "Права, выданные тебе: " + ", ".join(sorted(spec.rights)) + "."]
        mirror = self.aside_mirror(spec, task)
        if mirror:
            lines += [
                "",
                f"Живое дерево, правки в нём действуют сразу: `{mirror[0]}`",
                f"Твоя копия под коммиты и ветку: `{mirror[1]}`",
            ]
        if task is not None:
            lines += [
                "",
                "## Как смотреть чужой ход",
                "",
                "Скелет хода — вызовы с исходами, ошибки, тронутые файлы, финальное "
                "сообщение роли:",
                "",
                "```sh",
                f"orch digest {task['id']} <шаг> <заход>",
                "```",
                "",
                "Не хватило — весь транскрипт лежит в "
                f"`{dg.TRANSCRIPTS / dg.project_slug(task['worktree_path'] or task['project_path'])}/`, "
                "по файлу на сессию; читай выборочно, подряд он весит сотни тысяч знаков.",
            ]
        note = self.note_block(payload)
        if note:
            lines += ["", note]
        лента = self.notes_ledger(spec, task, payload)
        if лента:
            lines += ["", лента]
        прошлое = self.notes_history(spec, task, self.wake_history(spec, run))
        if прошлое:
            lines += ["", прошлое]
        return "\n".join(lines)

    def wake_history(self, spec: Aside, run) -> int:
        """Сколько прошлых находок просит повод этого хода."""
        wake = spec.wake_by_prompt(run["wake"]) if run["wake"] else None
        return wake.history if wake else 0

    def notes_history(self, spec: Aside, task, сколько: int) -> str:
        """Находки роли по прошлым задачам — с ответами владельца.

        Памяти между прогонами у ролей нет: копилки сняты (2026-09-09), и
        всё, что роль помнит, лежит в её же находках. Здесь их отдают
        обратно, чтобы на итоге было видно повторяющееся: тот же дефект в
        третий раз — это уже не наблюдение, а причина править.

        Даётся только поводу с `history` — то есть итогу. Разбор одного хода
        обходится без чужих прогонов: там нужен этот шаг, а не история.
        """
        if сколько < 1:
            return ""
        свои = task["id"] if task is not None else None
        строки = []
        for note in reversed(self.db.notes()):
            if свои and note["task_id"] == свои:
                continue
            aside = self.db.aside(int(note["aside_id"]))
            if aside is None or aside["name"] != spec.name:
                continue
            ответ = note["decision"] or ("без ответа" if note["state"] in ("open", "sent") else "")
            строки.append(
                f"- {note['task_id']}: «{note['title']}»" + (f" → {ответ}" if ответ else "")
            )
            if len(строки) >= сколько:
                break
        if not строки:
            return ""
        return (
            "## Твои находки по прошлым задачам\n\n"
            "Свежие сверху. Повторившееся — повод сказать об этом отдельно.\n\n"
            + "\n".join(строки)
        )

    def wake_title(self, spec: Aside, kind: str) -> str:
        wake = spec.wake_for(kind)
        return (wake.title if wake and wake.title else kind)

    def short_tail(self, spec: Aside, task, payload: dict, шаг, заход) -> str:
        """Короткий хвост: чем смотреть ход и ответ владельца, если он был."""
        куски = []
        if шаг and заход and task is not None:
            куски.append(f"Ход: `orch digest {task['id']} {шаг} {заход}`.")
        note = self.note_block(payload)
        if note:
            куски.append(note)
        return "\n\n".join(куски)

    def notes_ledger(self, spec: Aside, task, payload: dict) -> str:
        """Что ты уже говорила по этой задаче и что владелец ответил.

        Каждый ход — новая сессия с чистой памятью, а разговор с владельцем
        идёт кругами: без ленты роль на третьем сообщении не помнит, с чего
        начали, и предлагает то же самое заново.
        """
        if task is None:
            return ""
        текущая = int(payload.get("note") or 0)
        строки = []
        for note in self.db.notes(task_id=task["id"]):
            aside = self.db.aside(int(note["aside_id"]))
            if aside is None or aside["name"] != spec.name or int(note["id"]) == текущая:
                continue
            ответ = note["decision"] or ("ждёт ответа" if note["state"] == "sent" else "не отправлена")
            строки.append(f"- «{note['title']}» → {ответ}")
        if not строки:
            return ""
        return "## Твои находки по этой задаче\n\n" + "\n".join(строки[-12:])

    def note_block(self, payload: dict) -> str:
        """Находка и решение владельца — когда роль будят его ответом.

        Без этого роль просыпается на «владелец ответил» и не помнит, о чём
        речь: её сессия закрыта, память живёт в файлах и здесь.
        """
        note = self.db.note(int(payload["note"])) if payload.get("note") else None
        if note is None:
            return ""
        verb = payload.get("verb") or ""
        target = payload.get("target") or ""
        решение = {
            "continue": "оставить как есть",
            "restart": "перезапустить шаг",
            "back": f"вернуть на «{target}»",
            "back_clean": f"вернуть на «{target}» начисто",
            "stop": "остановить задачу",
            "patch": "править",
            "say": "сказал словами",
        }.get(verb, verb)
        lines = [
            "# Твоя находка, на которую ответил владелец",
            "",
            f"**{note['title']}**",
            "",
            (note["body"] or "").strip(),
            "",
            f"Владелец выбрал: **{решение}**.",
        ]
        if verb == "say" and target:
            lines += ["", "Его слова:", "", f"> {target.strip()}"]
        return "\n".join(lines)

    def aside_mirror(self, spec: Aside, task=None) -> tuple[str, str] | None:
        """Пара «живое дерево, копия под коммиты» — для ролей с `mirror`.

        `worktree:project` — копия того проекта, за которым роль приставлена:
        у Менеджера проект свой в каждом прогоне, зашить путь нельзя.
        """
        if not spec.mirror.startswith("worktree:"):
            return None
        цель = spec.mirror[9:]
        if цель == "project":
            if task is None or not task["project_path"]:
                return None
            project = Path(task["project_path"])
        else:
            project = Path(цель).expanduser()
        if not project.is_dir():
            return None
        path, error = create_worktree(project, f"aside/{spec.name}")
        if error:
            self.note_once(None, "aside_mirror_failed", {"aside": spec.name, "error": error[:200]})
            return None
        return str(project), str(path)

    def aside_digest(self, task, payload: dict) -> str:
        """Где смотреть разбираемый ход. Сам ход в задание не вклеиваем.

        Транскрипт лежит на диске целиком, и роль читает его сама: копий
        движок не делает, а обзор собирается командой по требованию.
        """
        run_id = payload.get("run")
        if task is None or not run_id:
            return ""
        row = self.db.conn.execute("SELECT * FROM run WHERE id = ?", (run_id,)).fetchone()
        if row is None or not task["worktree_path"]:
            return ""
        папка = dg.TRANSCRIPTS / dg.project_slug(task["worktree_path"])
        файл = f"{row['acp_session_id']}.jsonl" if row["acp_session_id"] else "<сессия>.jsonl"
        return "\n".join([
            "## Разбираемый ход",
            "",
            f"Шаг `{row['step']}`, заход {row['n']}, сессия `{row['session_id'] or '?'}`, "
            f"окно {row['started_at']} … {row['ended_at'] or 'ещё идёт'}.",
            "",
            "Скелет хода — вызовы с исходами, ошибки, тронутые файлы, финальное "
            "сообщение роли:",
            "",
            "```sh",
            f"orch digest {task['id']} {row['step']} {row['n']}",
            "```",
            "",
            f"Не хватит — весь транскрипт этого хода лежит в `{папка}/{файл}`; "
            "читай его выборочно, подряд он весит сотни тысяч знаков. Соседние "
            "файлы в той же папке — чужие сессии, в них ход не разбирают.",
        ])

    # ── конец хода ───────────────────────────────────────────────────────
    def watch_aside_runs(self, sessions: dict[str, Session]) -> None:
        """Закрыть ходы, которые кончились, и добить те, что не начались."""
        for run in self.db.aside_runs_open():
            if self.spec_of(run["name"]) is None:
                # Стенд и уборка стенда живут в тех же таблицах, но не по
                # этим правилам: их ход кончается словом роли (`orch stand`),
                # а сессию гасит `finish_teardown`. Общий сторож закрыл бы
                # их сразу после первого `Idle` и убрал бы стенд в архив.
                continue
            sid = run["session_id"]
            if not sid:
                # Ход записан, сессии нет: следующий проход её заведёт.
                continue
            session = sessions.get(sid) or self.aoe.session(sid)
            if session is None:
                with self.db.tx():
                    self.db.aside_run_end(int(run["id"]), "lost")
                    self.db.event(
                        run["task_id"], "aside_lost", {"aside": run["name"], "session": sid}
                    )
                self.retry_aside(run)
                continue
            if session.status in (STARTING, WAITING) or not session.turn_ended(
                run["prompt_sent_at"]
            ):
                continue
            cost, _ = self.aoe.usage(sid)
            with self.db.tx():
                self.db.aside_run_end(int(run["id"]), "ended", cost)
                self.db.event(
                    run["task_id"],
                    "aside_ended",
                    {"aside": run["name"], "run": int(run["id"]), "cost_usd": cost},
                )

    def sweep_aside_sessions(self, sessions: dict[str, Session]) -> None:
        """Сессия повода живёт один ход: сдала — уезжает в архив.

        Поводы с `session: fresh` заводят свою сессию на каждый шаг, и за
        прогон их набегает по две на шаг: сайдбар зарастает так, что живой
        работы в нём не видно (T26). Всё, что роль на таком ходу нашла, уже
        лежит в базе (находки и лента), а сводку в конце прогона
        собирает общая переписка — значит карточка после сдачи хода не нужна.

        В архив, а не насовсем: переписка остаётся, а суточная уборка
        (`orch-sweep`) отправит её в корзину через три дня. Общую переписку
        роли не трогаем никогда — в ней с ролью разговаривает владелец.
        """
        for run in self.db.aside_runs_in_sessions(list(sessions)):
            spec = self.spec_of(run["name"])
            wake = spec.wake_by_prompt(run["wake"]) if spec else None
            if wake is None or wake.session != "fresh":
                continue
            sid = run["session_id"]
            if sid == run["aside_session"]:
                continue
            session = sessions.get(sid)
            if session is None or session.status in (STARTING, RUNNING, WAITING):
                # Ход сдан командой, но текст ещё дописывается или роль
                # спросила владельца: архивируем на следующем проходе.
                continue
            self.aoe.archive(sid)
            with self.db.tx():
                self.db.event(
                    run["task_id"], "aside_session_archived",
                    {"aside": run["name"], "run": int(run["id"]), "session": sid},
                )

    def close_task_asides(self, task_id: str) -> None:
        """Роль, приставленная к задаче, кончается вместе с задачей.

        Иначе запись роли остаётся `live` навсегда, а её общая переписка —
        строкой в сайдбаре: по одной на каждую прошедшую задачу. Роли с
        областью «проект» и «машина» это не касается — они переживают задачу
        по замыслу.

        Зовётся из `archive_old`, то есть через `ARCHIVE_AFTER_H` после
        конца: сводка к этому времени прочитана, а ответить на находку
        владелец успел.
        """
        for aside in self.db.asides_live():
            if aside["task_id"] != task_id or aside["scope"] not in ("run", "task"):
                continue
            сессии = {aside["session_id"] or ""} | {
                r["session_id"] for r in self.db.aside_runs_of(int(aside["id"]))
                if r["session_id"]
            }
            for sid in sorted(x for x in сессии if x):
                self.aoe.archive(sid)
            with self.db.tx():
                self.db.aside_close(int(aside["id"]))
                self.db.event(task_id, "aside_closed", {"aside": aside["name"]})

    def retry_aside(self, run) -> None:
        """Сессия роли исчезла, не сдав ход, — поднять её ещё раз.

        Повод уже прошёл курсор и сам не вернётся, поэтому без повтора запись
        роли о задаче пропала бы молча. Повтор ровно один: если сессия гибнет
        дважды, дело не в случайности.
        """
        spec = self.spec_of(run["name"])
        if spec is None:
            return
        повторы = [
            r for r in self.db.aside_runs_of(int(run["aside_id"]), run["task_id"])
            if r["wake"] == run["wake"]
        ]
        if len(повторы) >= 2 or not run["cause_seq"]:
            return
        event = self.db.conn.execute(
            "SELECT * FROM event WHERE seq = ?", (run["cause_seq"],)
        ).fetchone()
        if event is None:
            return
        wake = spec.wake_for(event["kind"])
        if wake is None or not self.capacity(run["task_id"], f"роль {spec.name} (повтор)"):
            return
        token = uuid.uuid4().hex[:12]
        with self.db.tx():
            # `cause_seq` пустой: повод тот же, но ключ уникальности занят
            # первым ходом, а второй заводится сознательно.
            run_id = self.db.aside_run_start(
                int(run["aside_id"]), run["wake"], None, token, run["task_id"]
            )
            self.db.event(
                run["task_id"], "aside_retry",
                {"aside": spec.name, "wake": run["wake"], "run": run_id},
            )
        self.aside_send(spec, wake, int(run["aside_id"]), run_id, event)

    # ── заявки роли (`orch aside …` через inbox) ─────────────────────────
    def aside_note(
        self, run_id: int, severity: str, title: str, body: str, options: list, token: str = ""
    ) -> str:
        run, aside, spec, refuse = self.aside_caller(run_id, token)
        if refuse:
            return refuse
        # Три веса, и по умолчанию самый тихий: агент, которого попросили
        # искать, всегда что-нибудь найдёт, и без порога мессенджер владельца
        # превратится в поток мелочи.
        #   hold — задача встаёт: владелец увидит это в панели;
        #   log  — копится и входит в сводку конца прогона.
        if severity not in ("hold", "log"):
            severity = "log"
        if severity == "hold" and not self.may_hold(spec):
            # Роль без права останавливать всё равно скажет, но прогон не
            # застопорит.
            severity = "log"
        with self.db.tx():
            note_id = self.db.note_add(
                int(run["aside_id"]), run_id, aside["task_id"], severity, title, body, options
            )
            self.db.event(
                aside["task_id"],
                "aside_note",
                {"aside": aside["name"], "note": note_id, "severity": severity},
            )
        if severity == "hold" and aside["task_id"]:
            self.stop(aside["task_id"], "aside_hold", urgent=True)
        return f"находка записана (N{note_id})"

    def aside_done(self, run_id: int, outcome: str | None = None, token: str = "") -> str:
        run, aside, _spec, refuse = self.aside_caller(run_id, token)
        if refuse:
            return refuse
        with self.db.tx():
            self.db.aside_run_end(run_id, outcome or "done")
            self.db.event(
                aside["task_id"], "aside_done", {"aside": aside["name"], "run": run_id}
            )
        return "ход принят"

    def aside_caller(self, run_id: int, token: str, need: str = "") -> tuple:
        """Ход, от имени которого пришла команда, или отказ.

        Пропуск сверяется всегда: номер хода — маленькое целое, и без
        секрета его хватало бы, чтобы чужая сессия остановила любую задачу
        (`ASIDE-PLAN.md` §6). Закрытый ход тоже не считается: роль,
        сдавшая ход, больше ничего не решает.
        """
        run = self.db.aside_run(run_id)
        if run is None:
            return None, None, None, f"нет хода A{run_id}"
        if (run["token"] or "") != (token or ""):
            with self.db.tx():
                self.db.event(
                    None, "aside_bad_token", {"run": run_id, "given": (token or "")[:8]}
                )
            return None, None, None, "пропуск не подходит к этому ходу"
        if run["ended_at"]:
            return None, None, None, "ход уже закрыт"
        aside = self.db.aside(int(run["aside_id"]))
        spec = self.spec_of(aside["name"])
        if need and (spec is None or not spec.may(need)):
            return None, None, None, f"этой роли не выдано право «{need}»"
        return run, aside, spec, ""

    # ── решение владельца по находке ─────────────────────────────────────
    def note_decision(self, note_id: int, verb: str, target: str | None, who: str) -> str:
        """Исполнить вариант, который владелец выбрал под находкой.

        Глаголы — словарь движка (`ASIDE-PLAN.md` §4): произвольный текст
        исполнить нельзя, поэтому роль и предлагает только их.
        """
        note = self.db.note(note_id)
        if note is None:
            return f"нет находки N{note_id}"
        if note["state"] in ("answered", "applied", "dropped"):
            return "решение по этой находке уже принято"
        task_id = note["task_id"]
        task = self.db.task(task_id) if task_id else None
        answer = "принято"

        if verb == "continue":
            if task is not None and task["wait_reason"] == "aside_hold":
                answer = self.button(task_id, task["revision"], "accept")
        elif verb == "stop":
            if task is not None:
                self.stop(task_id, "aside_hold", urgent=True)
                answer = "задача остановлена"
        elif verb in ("restart", "again"):
            if task is not None:
                answer = self.button(task_id, task["revision"], "again", comment=note["title"])
        elif verb in ("back", "back_clean"):
            if task is not None:
                answer = self.button(task_id, task["revision"], verb, target, note["title"])
        elif verb == "say":
            # Слова владельца не двигают задачу: их дело — дойти до роли,
            # которая находку написала. Она проснётся событием ниже.
            answer = "передал роли ваши слова"
        elif verb == "patch":
            answer = "роль применит правку следующим ходом"
        else:
            return f"глагол {verb!r} движок исполнить не умеет"

        with self.db.tx():
            self.db.note_state(
                note_id, "answered", decision=f"{verb}:{target or ''}", decided_at=now()
            )
            # Событие — повод проснуться той роли, что находку написала:
            # она применит правку или закроет свою запись (`§1`, `note_decided`).
            self.db.event(
                task_id,
                "note_decided",
                {"note": note_id, "verb": verb, "target": target, "who": who},
            )
        return answer

    def spec_of(self, name: str) -> Aside | None:
        for spec in spec_mod.all_asides():
            if spec.name == name:
                return spec
        return None
