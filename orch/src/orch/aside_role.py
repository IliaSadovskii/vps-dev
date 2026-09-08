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
from .aoe import STARTING, WAITING, Aoe, AoeError, Session
from .asides import Aside, Wake
from .chain import prompts_dir
from .db import LIVE, STATE_DIR, now
from .naming import GROUP_ROOT, slug
from .workspace import create_worktree

# Сколько событий одна роль разбирает за проход: движок не должен зависать
# на журнале, накопившемся, пока роль была выключена.
BATCH = 20


class AsideMixin:
    # ── проход ───────────────────────────────────────────────────────────
    def pump_asides(self, sessions: dict[str, Session]) -> None:
        """Довести побочные ходы и завести новые по накопившимся поводам."""
        self.watch_aside_runs(sessions)
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
        session = None
        if aside is not None and aside["session_id"]:
            # Одна сессия на задачу: роль просыпается новым промптом в свою
            # же переписку. Так у неё есть память о прошлых ходах, а у
            # владельца — одна карточка в сайдбаре вместо десятка.
            session = self.aoe.session(aside["session_id"])
        try:
            session = session or self.aoe.create(
                path=str(path),
                agent=wake.agent,
                model=wake.model,
                effort=wake.effort,
                title=f"{spec.title or spec.name} · {event['task_id'] or 'машина'}",
                group=(task["group_path"] if task is not None else None) or f"{GROUP_ROOT}/побочные",
                # Номер хода в ключе: повтор после умершей сессии должен
                # завести новую, а не получить обратно мёртвую по старому
                # ключу. Внутри одного хода ключ постоянен — за это
                # идемпотентность и держат.
                idempotency_key=f"aside/{spec.name}/{aside_id}",
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
            if aside is None or aside["session_id"] != session.id:
                self.db.conn.execute(
                    "UPDATE aside SET session_id = ? WHERE id = ?", (session.id, aside_id)
                )
        self.aoe.set_notify(session.id, False)
        self.aoe.set_color(session.id, "blue")

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
        было = [
            r["wake"] for r in self.db.aside_runs_of(int(run["aside_id"]))
            if int(r["id"]) != int(run["id"])
        ]
        parts = []
        if not было:
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
        parts.append(self.aside_context(spec, run, task, event))
        return "\n\n".join(parts)

    def aside_context(self, spec: Aside, run, task, event) -> str:
        """Блок задачи для побочной роли: id хода, повод, что читать.

        Опознаётся роль по `--id`: своей рабочей копии у неё может не быть,
        а окружение AoE обычным сессиям не передаёт (`RISKS.md` п. 1).
        """
        payload = json.loads(event["payload"] or "{}")
        lines = [
            "# Что случилось",
            "",
            f"Твой ход: `A{run['id']}`, пропуск `{run['token'] or ''}`.",
            "Команды `orch aside` требуют оба: "
            f"`--id A{run['id']} --pass {run['token'] or ''}`. Пропуск никому не показывай.",
            f"Повод: `{event['kind']}` в {event['at']}.",
        ]
        if payload:
            lines.append("Подробности повода: " + json.dumps(payload, ensure_ascii=False))
        if task is not None:
            lines += [
                "",
                f"Задача {task['id']}: {task['title']}",
                f"Цепочка: `{task['chain']}`, шаг сейчас: `{task['step'] or '—'}`",
                f"Проект: `{task['project_path']}`",
                f"Рабочая копия задачи: `{task['worktree_path'] or task['project_path']}`",
                f"Папка задачи: `{Path(task['worktree_path'] or task['project_path']) / '.orch' / task['id']}`",
            ]
        mirror = self.aside_mirror(spec, task)
        if mirror:
            lines += [
                "",
                f"Живое дерево, правки в нём действуют сразу: `{mirror[0]}`",
                f"Твоя копия под коммиты и ветку: `{mirror[1]}`",
            ]
        lines += ["", "Права, выданные тебе: " + ", ".join(sorted(spec.rights)) + "."]
        if spec.may("memory"):
            # Без пути роль не знает, где её собственная память, и пишет
            # заново то, что уже записала в прошлый раз.
            lines.append(f"Твоя копилка: `{self.memory_path(spec, {'task_id': task['id'] if task is not None else None, 'scope_key': self.aside_key(spec, task, event) or ''})}`")
        note = self.note_block(payload)
        if note:
            lines += ["", note]
        лента = self.notes_ledger(spec, task, payload)
        if лента:
            lines += ["", лента]
        skeleton = self.aside_digest(task, payload)
        if skeleton:
            lines += ["", skeleton]
        return "\n".join(lines)

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
        """Скелет хода, о котором речь, — если повод про заход."""
        run_id = payload.get("run")
        if task is None or not run_id:
            return ""
        row = self.db.conn.execute(
            "SELECT * FROM run WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None or not task["worktree_path"]:
            return ""
        data = dg.digest(
            task["worktree_path"], since=row["started_at"], until=row["ended_at"]
        )
        return dg.render(data) if data["turns"] else ""

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
        elif verb == "back":
            if task is not None:
                answer = self.button(task_id, task["revision"], "back", target, note["title"])
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

    # ── копилка ──────────────────────────────────────────────────────────
    def aside_memory(self, run_id: int, text: str, token: str = "") -> str:
        run, aside, spec, refuse = self.aside_caller(run_id, token, need="memory")
        if refuse:
            return refuse
        path = self.memory_path(spec, aside)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n## {now()}\n\n{text.strip()}\n")
        with self.db.tx():
            self.db.event(
                aside["task_id"], "aside_memory", {"aside": aside["name"], "file": str(path)}
            )
        return f"записано в {path}"

    def memory_path(self, spec: Aside, aside) -> Path:
        """Копилка роли: одна на машину, на проект или на задачу.

        Живёт рядом с базой, а не в репозитории: это память машины о
        прогонах, ей не место в чужих коммитах.
        """
        root = STATE_DIR / "memory"
        if spec.memory == "task" and aside["task_id"]:
            return root / f"{spec.name}-{aside['task_id']}.md"
        if spec.memory == "project":
            return root / f"{spec.name}-{slug(aside['scope_key'])}.md"
        return root / f"{spec.name}.md"

    def spec_of(self, name: str) -> Aside | None:
        for spec in spec_mod.all_asides():
            if spec.name == name:
                return spec
        return None
