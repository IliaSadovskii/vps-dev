"""Движок: reconcile() по всем идущим задачам раз в 5 секунд.

Реконсиляция вместо событий: каждый проход читает базу, один
`GET /api/sessions`, файлы задач; выводит одно действие на задачу; выполняет;
записывает. Старт после падения — обычный первый проход (`PLAN.md` §2).

Единственный писатель базы — движок. Всё, что меняет задачу, идёт транзакцией
с инкрементом ревизии; внешние действия (создать сессию, послать промпт)
повторяемы по намерению, записанному в базе.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import artifacts as art
from . import promptbuild, signals
from .aoe import ERROR, IDLE, RUNNING, STARTING, STOPPED, WAITING, Aoe, AoeError, Session
from .chain import DONE, Chain, ChainError, Step, chains_dir, load as load_chain, parse as parse_chain
from .db import ABANDONED, BACKLOG, DONE as ST_DONE, LIVE, QUEUED, RUNNING as ST_RUNNING, WAITING as ST_WAITING, Db, now
from .workspace import Workspace, create_worktree, git, remove_worktree

INBOX = Path.home() / ".local" / "share" / "orch" / "inbox"
GROUP_ROOT = "orch"
ARCHIVE_AFTER_H = 168

# Причины остановки. Код лежит в `task.wait_reason`, текст рисует панель.
WAIT_REASONS = {
    "gate": "ворота: ждёт вашего решения",
    "no_signal": "роль закончила ход, не подав сигнал",
    "max_runs": "предел заходов на шаг",
    "error": "сессия в ошибке",
    "ask": "роль спрашивает вас",
    "bad_outcome": "роль назвала исход не из списка",
    "chain_broken": "замороженная цепочка не читается",
    "path_mismatch": "рабочая копия сессии не совпала с задачей",
    "no_worker": "у сессии не поднялся воркер агента",
    "no_worktree": "не удалось создать рабочую копию задачи",
    "artifact": "роль сдала ход, но её файла нет или он не той формы",
    "abandoned": "сессия задачи исчезла",
}

# Пробуждение уснувшего воркера: сколько раз пробуем и сколько ждём после
# отправки промпта, прежде чем считать воркер уснувшим.
WAKE_LIMIT = 3
WAKE_GRACE_S = 30.0


@dataclass
class Settings:
    poll_secs: float = 5.0
    max_running: int = 3
    cost_warn_usd: float = 5.0
    default_chain: str = "deep"
    aoe_url: str = ""


class Engine:
    def __init__(self, db: Db, aoe: Aoe | None = None, settings: Settings | None = None) -> None:
        self.db = db
        self.aoe = aoe or Aoe()
        self.settings = settings or Settings()

    # ── проход ───────────────────────────────────────────────────────────
    def reconcile(self) -> None:
        """Один проход по всем задачам. Идемпотентен: повтор ничего не ломает."""
        self.take_inbox()
        # Очередь разбирается до обхода задач, иначе только что созданная
        # задача ждала бы следующего прохода зря.
        self.promote_queue()
        try:
            sessions = self.aoe.sessions()
        except AoeError as exc:
            self.db.event(None, "aoe_unreachable", {"error": str(exc)})
            return
        for row in self.db.tasks(LIVE):
            try:
                self.step_task(row, sessions)
            except Exception as exc:  # noqa: BLE001 — одна задача не роняет проход
                self.db.event(row["id"], "engine_error", {"error": repr(exc)})
        self.archive_old()

    def step_task(self, task, sessions: dict[str, Session]) -> None:
        if task["status"] == QUEUED:
            return
        if task["status"] == ST_WAITING:
            # Задача, вставшая на вопросе роли, снимается сама: владелец
            # отвечает в чате, сессия уходит из `Waiting`, и ход продолжается.
            # Остальные остановки ждут кнопки.
            if task["wait_reason"] == "ask":
                self.resume_after_answer(task, sessions)
            return
        chain = self.chain_of(task)
        if chain is None:
            self.stop(task["id"], "chain_broken")
            return
        run = self.db.open_run(task["id"])
        if run is None:
            self.begin_run(task, chain)
            return
        self.watch_run(task, chain, run, sessions)

    def resume_after_answer(self, task, sessions: dict[str, Session]) -> None:
        """Владелец ответил роли в чате — задача снова едет."""
        run = self.db.open_run(task["id"])
        if run is None or not run["session_id"]:
            return
        session = sessions.get(run["session_id"]) or self.aoe.session(run["session_id"])
        if session is None or session.status == WAITING:
            return
        with self.db.tx():
            self.db.bump(task["id"], status=ST_RUNNING, wait_reason=None)
            self.db.event(task["id"], "answered", {"session": session.id})
        self.aoe.set_color(session.id, "amber")
        self.aoe.set_urgent(session.id, False)

    # ── заявки и очередь ─────────────────────────────────────────────────
    def take_inbox(self) -> None:
        """Заявки из `inbox/`: новая задача, кнопка из терминала, сессия Inbox.

        Так `orch` в сессии и в терминале не пишет в базу: писатель один.
        """
        if not INBOX.is_dir():
            return
        for path in sorted(INBOX.glob("*.json")):
            try:
                request = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                path.unlink(missing_ok=True)
                continue
            kind = request.get("kind", "new")
            try:
                if kind == "button":
                    answer = self.button(
                        request["task"],
                        request["revision"],
                        request["action"],
                        request.get("target"),
                        request.get("comment"),
                    )
                    self.db.event(request["task"], "button_from_cli", {"answer": answer})
                elif kind == "edit_text":
                    self.edit_text(request["task"], request["text"])
                elif kind == "wizard":
                    self.open_wizard(
                        request["project_path"],
                        request.get("task"),
                        request.get("mode") or "start",
                    )
                else:
                    task_id = self.create_task(
                        chain_name=request.get("chain") or self.settings.default_chain,
                        project_path=request["project_path"],
                        text=request["text"],
                        preset=request.get("preset"),
                        sheet_edits=request.get("sheet_edits") or {},
                        backlog=bool(request.get("backlog")),
                        branch=request.get("branch"),
                        base=request.get("base"),
                        author=request.get("author"),
                        from_backlog=request.get("from_backlog"),
                    )
                    self.db.event(task_id, "task_created", {"from": "inbox", "file": path.name})
            except (ChainError, KeyError, OSError) as exc:
                self.db.event(None, "inbox_rejected", {"file": path.name, "error": str(exc)})
            path.unlink(missing_ok=True)

    def edit_text(self, task_id: str, text: str) -> str:
        """Переписать ТЗ заявки. Только пока она в бэклоге: у поехавшей задачи
        текст уже разошёлся по промптам прошлых шагов, и молча менять его —
        врать ролям."""
        task = self.db.task(task_id)
        if task is None:
            return "нет такой задачи"
        if task["status"] != BACKLOG:
            return f"{task_id} уже не в бэклоге: текст правится только у заявки"
        with self.db.tx():
            self.db.bump(task_id, text=text, title=_title_from(text))
            self.db.event(task_id, "text_edited", {"len": len(text)})
        return f"{task_id}: ТЗ переписано"

    def open_wizard(
        self,
        project_path: str,
        task_id: str | None = None,
        mode: str = "start",
    ) -> str | None:
        """Мастер задачи: сессия, в которой владелец заводит задачу разговором.

        Панель не умеет ни поля ввода, ни дропдауна (`UX-PLAN.md`), поэтому
        цепочку, ветку и автономию спрашивает роль в чате вариантами, а потом
        сама зовёт `orch task new`. Сессия одна на проект: мастер дешёвый, и
        плодить их на каждую заявку незачем.
        """
        from .chain import catalog, prompts_dir

        project = str(Path(project_path).resolve())
        task = self.db.task(task_id) if task_id else None
        prompt_file = prompts_dir() / "role-wizard.md"
        try:
            session = self.aoe.create(
                path=project,
                agent="claude",
                model="sonnet",
                effort=None,
                title=f"Мастер · {Path(project).name}",
                group=f"{GROUP_ROOT}/мастер",
                idempotency_key=f"wizard/{project}",
            )
        except AoeError as exc:
            self.db.event(None, "wizard_failed", {"project": project, "error": str(exc)})
            return None
        # Группу ставим отдельным вызовом: при создании AoE её не применяет,
        # и мастер оказывался вне группы, вперемешку с сессиями шагов.
        self.aoe.set_group(session.id, f"{GROUP_ROOT}/мастер")
        # Модель ставится вызовом, а не полем при создании: `agent_model` до
        # адаптера Claude не доезжает, и сессия молча уходит на Opus (см.
        # `apply_model`). Мастер — дешёвая роль, платить за него Opus незачем.
        if not self.aoe.apply_model(session.id, "sonnet"):
            self.db.event(
                None,
                "wizard_model_not_applied",
                {"session": session.id, "got": self.aoe.model_now(session.id)},
            )
        text = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else ""
        text += "\n\n" + self.wizard_context(project, catalog(), task, mode)
        try:
            self.aoe.prompt(session.id, text)
        except AoeError as exc:
            self.db.event(None, "wizard_prompt_failed", {"project": project, "error": str(exc)})
        self.db.event(
            task_id,
            "wizard_opened",
            {"project": project, "session": session.id, "mode": mode},
        )
        return session.id

    def wizard_context(self, project: str, chains: list[dict], task, mode: str) -> str:
        """Блок «чем располагаешь» для мастера: цепочки, проект, заявка."""
        lines = ["## Чем располагаешь", "", f"Проект: `{project}`", "", "Цепочки:"]
        for item in chains:
            if item.get("error"):
                lines.append(f"- `{item['name']}` — не читается: {item['error']}")
                continue
            gates = ", ".join(item["gates"]) or "нет"
            lines.append(
                f"- `{item['name']}` — {item['description'] or 'без описания'}\n"
                f"  шаги: {' → '.join(item['steps'])}\n"
                f"  ворота по умолчанию: {gates}; пресеты: "
                f"{', '.join(item['presets']) or 'нет'}"
            )
        if task is not None:
            lines += [
                "",
                f"## Заявка {task['id']} из бэклога",
                "",
                "Текст, который владелец уже записал:",
                "",
                "```",
                (task["text"] or "").strip(),
                "```",
                "",
                f"Ветка заявки: {task['branch'] or 'не выбрана'}.",
            ]
            if mode == "text":
                lines.append(
                    "Владелец нажал «Править ТЗ»: перепиши текст в разговоре и, "
                    f"когда он одобрит, вызови `orch task edit {task['id']} --text -`. "
                    "Задачу не запускай."
                )
            else:
                lines.append(
                    "Владелец нажал «В работу»: уточни, что нужно, спроси цепочку, "
                    "ветку и автономию, и заведи задачу вызовом `orch task new` с "
                    f"`--from-backlog {task['id']}` — заявка закроется сама."
                )
        else:
            lines += [
                "",
                "## Новая задача",
                "",
                "Владелец нажал «Новая задача»: начни с вопроса, что он хочет.",
            ]
        return "\n".join(lines)

    def create_task(
        self,
        *,
        chain_name: str,
        project_path: str,
        text: str,
        preset: str | None = None,
        sheet_edits: dict | None = None,
        backlog: bool = False,
        title: str | None = None,
        branch: str | None = None,
        base: str | None = None,
        author: str | None = None,
        from_backlog: str | None = None,
    ) -> str:
        """Завести задачу.

        `branch` — работать в названной ветке вместо новой: так задача
        садится на уже открытый PR. Ветка есть — движок подключится к ней,
        нет — заведёт с этим именем. `base` — от чего ответвляться, если
        ветки ещё нет.
        """
        chain = load_chain(chains_dir() / f"{chain_name}.yml")
        sheet = chain.sheet_with_preset(preset)
        if sheet_edits:
            from .chain import apply_preset

            sheet = apply_preset(sheet, sheet_edits)
        task_id = self.db.next_task_id()
        title = title or _title_from(text)
        if branch:
            busy = self.task_on_branch(branch)
            if busy:
                raise ChainError(
                    f"ветка {branch} занята задачей {busy['id']} ({busy['status']}). "
                    "Одна рабочая копия — одна задача: закройте ту или возьмите "
                    "другую ветку"
                )
        else:
            branch = f"{task_id.lower()}-{_slug(title)}"
        with self.db.tx():
            self.db.conn.execute(
                "INSERT INTO task (id, chain, chain_yaml, title, text, project_path, branch, "
                "group_path, step, status, human_sheet, base_branch, author, revision, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
                (
                    task_id,
                    chain.name,
                    chain.source,
                    title,
                    text,
                    str(Path(project_path).resolve()),
                    branch,
                    f"{GROUP_ROOT}/{task_id} · {title}",
                    None,
                    BACKLOG if backlog else QUEUED,
                    json.dumps(sheet, ensure_ascii=False),
                    base or None,
                    author or None,
                    now(),
                ),
            )
            self.db.event(
                task_id,
                "created",
                {"chain": chain.name, "preset": preset, "branch": branch, "base": base},
            )
        if from_backlog:
            # Заявка, из которой выросла задача, закрывается: работа поехала
            # под новым номером, держать её ветку за старой незачем.
            old = self.db.task(from_backlog)
            if old is not None and old["status"] == BACKLOG:
                self.button(old["id"], old["revision"], "close")
                self.db.event(task_id, "from_backlog", {"task": from_backlog})
        return task_id

    def promote_queue(self) -> None:
        """Одновременно `running` не больше `max_running`; остальные ждут."""
        running = [t for t in self.db.tasks((ST_RUNNING,))]
        free = self.settings.max_running - len(running)
        if free <= 0:
            return
        for task in self.db.tasks((QUEUED,))[:free]:
            chain = self.chain_of(task)
            if chain is None:
                self.stop(task["id"], "chain_broken")
                continue
            with self.db.tx():
                revision = self.db.bump(task["id"], status=ST_RUNNING, step=chain.first.id)
                self.db.move(task["id"], None, chain.first.id, "engine", "start", revision)
                self.db.event(task["id"], "started", {"step": chain.first.id})

    def archive_old(self) -> None:
        """Через `ARCHIVE_AFTER_H` после Done сессии задачи уходят в архив."""
        import time

        from .db import epoch

        for task in self.db.tasks((ST_DONE,)):
            if task["archived_at"] or not task["closed_at"]:
                continue
            closed = epoch(task["closed_at"])
            if closed is None or (time.time() - closed) / 3600 < ARCHIVE_AFTER_H:
                continue
            for sid in self.db.sessions_of_task(task["id"]):
                self.aoe.archive(sid)
            # Рабочую копию убирает движок: AoE о ней не знает. Ветку не
            # трогаем — в ней вся работа задачи.
            error = ""
            if task["worktree_path"] and Path(task["worktree_path"]).is_dir():
                error = remove_worktree(task["project_path"], task["worktree_path"])
            with self.db.tx():
                self.db.bump(task["id"], archived_at=now())
                self.db.event(
                    task["id"], "archived", {"worktree_removed": not error, "error": error[:300]}
                )

    # ── старт захода ─────────────────────────────────────────────────────
    def begin_run(self, task, chain: Chain) -> None:
        step = chain.step(task["step"])
        done_runs = self.db.runs_of_step(task["id"], step.id)
        if len(done_runs) >= self.runs_allowed(task, step):
            self.stop(task["id"], "max_runs")
            return

        # Рабочая копия задачи — забота движка, а не AoE: и создание, и
        # удаление. Она готова до первой сессии, поэтому файлы задачи всегда
        # на месте раньше промпта (`PLAN.md` §2, правило 7).
        if not self.ensure_worktree(task):
            return
        task = self.db.task(task["id"])
        ws = self.workspace(task)
        ws.ensure(task["text"], task["chain_yaml"])
        start_sha = ws.head()

        with self.db.tx():
            run_id = self.db.start_run(task["id"], step.id, step.context, start_sha)
        run = self.db.conn.execute("SELECT * FROM run WHERE id = ?", (run_id,)).fetchone()

        session = self.attach_session(task, chain, step, run)
        if session is None:
            return
        ws.write_current(
            step.id, run["n"], session.id, "running", task["branch"], list(step.reads)
        )

        self.apply_model(task, step, session)

        text, sha, comment_ids = self.assemble(task, chain, step, run, ws)
        (ws.prompts / f"{step.id}-{run['n']}.md").write_text(text, encoding="utf-8")

        try:
            disposition = self.aoe.prompt(session.id, text)
        except AoeError as exc:
            self.db.event(task["id"], "prompt_failed", {"step": step.id, "error": str(exc)})
            return

        sent_at = now()
        with self.db.tx():
            self.db.conn.execute(
                "UPDATE run SET session_id = ?, prompt_sent_at = ?, prompt_sha = ? WHERE id = ?",
                (session.id, sent_at, sha, run_id),
            )
            self.db.mark_delivered(comment_ids)
            self.db.event(
                task["id"],
                "prompt_sent",
                {"step": step.id, "run": run["n"], "disposition": disposition, "sha": sha[:12]},
            )
        self.dress(task, chain, step, session.id)

    def task_on_branch(self, branch: str):
        """Задача, которая уже работает в этой ветке, или None.

        Две задачи в одной рабочей копии писали бы `.orch/` друг поверх
        друга, и `orch` в сессии не смог бы понять, чей он.
        """
        return self.db.conn.execute(
            "SELECT id, status FROM task WHERE branch = ? "
            "AND status IN ('backlog','queued','running','waiting') LIMIT 1",
            (branch,),
        ).fetchone()

    def ensure_worktree(self, task) -> bool:
        """Рабочая копия задачи существует. False — не смогли, задача встала.

        Делает `git worktree add` сам: AoE о рабочих копиях задач не знает
        вовсе. Иначе все сессии задачи имели бы одну ветку, а сайдбар веба
        сворачивает такие сессии в одну строку с именем ветки вместо титулов
        (`web/src/hooks/useWorkspaces.ts`), и до сессии прошлого шага было бы
        не добраться.
        """
        if task["worktree_path"] and Path(task["worktree_path"]).is_dir():
            return True
        path, error = create_worktree(
            task["project_path"], task["branch"], base=task["base_branch"] or ""
        )
        if error:
            self.db.event(
                task["id"], "worktree_failed", {"path": str(path), "error": error[:500]}
            )
            self.stop(task["id"], "no_worktree")
            return False
        with self.db.tx():
            self.db.bump(task["id"], worktree_path=str(path))
            self.db.event(task["id"], "worktree_created", {"path": str(path)})
        return True

    def attach_session(self, task, chain: Chain, step: Step, run) -> Session | None:
        """`fresh` — новая сессия; `continue` — последняя сессия этого агента."""
        if step.context == "continue":
            same_agent = [s.id for s in chain.steps if s.agent == step.agent]
            prev = self.db.last_run_of_agent(task["id"], same_agent)
            if prev and prev["session_id"]:
                session = self.aoe.session(prev["session_id"])
                if session:
                    return session

        # Ключ идемпотентности — задача/шаг/заход плюс время создания задачи.
        # Без времени пересозданная база наткнулась бы на старую сессию с тем
        # же именем и получила её вместе с мёртвым воркером.
        key = f"{task['id']}@{task['created_at']}/{step.id}/{run['n']}"
        try:
            session = self.aoe.create(
                path=task["worktree_path"],
                agent=step.agent,
                model=step.model,
                effort=step.effort,
                title=_session_title(task, step),
                group=task["group_path"] or f"{GROUP_ROOT}/{task['id']}",
                idempotency_key=key,
            )
        except AoeError as exc:
            self.db.event(task["id"], "session_create_failed", {"step": step.id, "error": str(exc)})
            return None

        if session.project_path and session.project_path != task["worktree_path"]:
            self.db.event(
                task["id"],
                "worktree_mismatch",
                {"expected": task["worktree_path"], "got": session.project_path},
            )
            self.stop(task["id"], "path_mismatch")
            return None
        return session

    def apply_model(self, task, step: Step, session: Session) -> None:
        """Поставить модель шага и убедиться, что адаптер её принял.

        Обязательно **до** промпта и на каждом заходе, а не только при смене
        модели в `continue`: `agent_model` при создании сессии до Claude не
        доезжает вовсе, и сессия молча работает на модели адаптера по
        умолчанию — у Claude это Opus, а не то, что записано в цепочке.
        Отказ не останавливает задачу: ход пойдёт на модели по умолчанию, но
        это будет видно в журнале, а не тихо.
        """
        if self.aoe.apply_model(session.id, step.model):
            return
        self.db.event(
            task["id"],
            "model_not_applied",
            {
                "session": session.id,
                "want": step.model,
                "got": self.aoe.model_now(session.id),
                "step": step.id,
            },
        )

    # ── наблюдение за ходом ──────────────────────────────────────────────
    def watch_run(self, task, chain: Chain, run, sessions: dict[str, Session]) -> None:
        step = chain.step(run["step"])
        sid = run["session_id"]
        if not sid:
            # Транзакция прошла, сессия не создалась: доводим намерение.
            self.begin_run_intent(task, chain, step, run)
            return
        session = sessions.get(sid) or self.aoe.session(sid)
        if session is None:
            self.stop(task["id"], "abandoned", status=ABANDONED)
            return

        if session.status in (RUNNING, STARTING):
            return

        if session.status == WAITING:
            self.on_waiting(task, chain, step, run, session)
            return

        if session.status == ERROR:
            self.on_error(task, chain, step, run, session)
            return

        if session.status == STOPPED or session.worker_state in ("absent", "stopped"):
            # Воркер умер: промпт — сам путь пробуждения (спайк 2). Но если
            # адаптер упал ещё на `session/new`, будить нечего: сессия так и
            # останется без воркера, поэтому попыток не больше трёх.
            if not session.turn_ended(run["prompt_sent_at"]):
                self.wake(task, run, session)
                return

        if session.turn_ended(run["prompt_sent_at"]):
            self.on_idle(task, chain, step, run, session)

    def begin_run_intent(self, task, chain: Chain, step: Step, run) -> None:
        """Заход создан, сессии нет — повторяем внешнюю часть по ключу."""
        session = self.attach_session(task, chain, step, run)
        if session is None:
            return
        task = self.db.task(task["id"])
        ws = self.workspace(task)
        ws.ensure(task["text"], task["chain_yaml"])
        ws.write_current(step.id, run["n"], session.id, "running", task["branch"], list(step.reads))
        self.apply_model(task, step, session)
        text, sha, comment_ids = self.assemble(task, chain, step, run, ws)
        (ws.prompts / f"{step.id}-{run['n']}.md").write_text(text, encoding="utf-8")
        try:
            self.aoe.prompt(session.id, text)
        except AoeError as exc:
            self.db.event(task["id"], "prompt_failed", {"step": step.id, "error": str(exc)})
            return
        with self.db.tx():
            self.db.conn.execute(
                "UPDATE run SET session_id = ?, prompt_sent_at = ?, prompt_sha = ? WHERE id = ?",
                (session.id, now(), sha, run["id"]),
            )
            self.db.mark_delivered(comment_ids)
        self.dress(task, chain, step, session.id)

    def on_waiting(self, task, chain: Chain, step: Step, run, session: Session) -> None:
        """`Waiting` = вопрос роли или запрос разрешения."""
        if self.ask_allowed(task, step):
            self.stop(task["id"], "ask", urgent=True)
            return
        # Вопросы выключены листом автономии: закрываем ход и говорим решать самой.
        self.aoe.cancel(session.id)
        self.db.event(task["id"], "question_refused", {"step": step.id, "run": run["n"]})
        try:
            self.aoe.prompt(
                session.id,
                "Вопросов не задаём: реши сам, запиши выбор в `## Допущения` и "
                "продолжай. Закончи ход командой `orch done`.",
            )
        except AoeError:
            pass

    def on_error(self, task, chain: Chain, step: Step, run, session: Session) -> None:
        """Один раз «продолжай», второй — остановка с причиной «ошибка»."""
        seen = self.db.conn.execute(
            "SELECT COUNT(*) c FROM event WHERE task_id = ? AND kind = 'error_retry' "
            "AND payload LIKE ?",
            (task["id"], f'%"run": {run["id"]}%'),
        ).fetchone()["c"]
        if seen:
            self.stop(task["id"], "error", urgent=True)
            return
        self.db.event(task["id"], "error_retry", {"run": run["id"], "step": step.id})
        try:
            self.aoe.prompt(session.id, "Продолжай с места остановки и закончи ход `orch done`.")
        except AoeError:
            self.stop(task["id"], "error", urgent=True)

    def wake(self, task, run, session: Session) -> None:
        """Разбудить уснувший воркер промптом. Не больше `WAKE_LIMIT` раз."""
        from .aoe import parse_time

        sent = parse_time(run["prompt_sent_at"])
        if sent and _epoch_now() - sent < WAKE_GRACE_S:
            return          # воркер ещё поднимается после создания сессии
        tried = self.db.conn.execute(
            "SELECT COUNT(*) c FROM event WHERE task_id = ? AND kind = 'worker_wake' "
            "AND payload LIKE ?",
            (task["id"], f'%"run": {run["id"]}%'),
        ).fetchone()["c"]
        if tried >= WAKE_LIMIT:
            self.db.event(
                task["id"],
                "wake_gave_up",
                {"run": run["id"], "session": session.id, "tries": tried},
            )
            self.stop(task["id"], "no_worker", urgent=True)
            return
        self.db.event(task["id"], "worker_wake", {"run": run["id"], "session": session.id})
        try:
            self.aoe.prompt(session.id, "Продолжай с места остановки и закончи ход `orch done`.")
        except AoeError as exc:
            self.db.event(task["id"], "wake_failed", {"error": str(exc)})

    def on_idle(self, task, chain: Chain, step: Step, run, session: Session) -> None:
        """Ход кончился. Сигнал читается только здесь (`RISKS.md` п. 1)."""
        ws = self.workspace(task)
        signal = signals.read(signals.done_path(ws.signals, step.id, run["n"]))
        end_sha = ws.head()

        if signal is None:
            self.end_without_signal(task, step, run, ws, end_sha, session)
            return

        outcome = signal.get("outcome")
        if step.single_next is None and outcome not in step.next:
            with self.db.tx():
                self.db.end_run(run["id"], None, end_sha, signalled=True)
                self.db.bump(task["id"], status=ST_WAITING, wait_reason="bad_outcome")
                self.db.event(task["id"], "bad_outcome", {"outcome": outcome, "step": step.id})
            self.mark_stopped(task, session.id)
            return

        problems = art.check_all(ws.artifacts, step.artifact)
        if problems:
            with self.db.tx():
                self.db.end_run(run["id"], None, end_sha, signalled=True)
                self.db.bump(task["id"], status=ST_WAITING, wait_reason="artifact")
                self.db.event(task["id"], "artifact_missing", {"problems": problems})
            self.mark_stopped(task, session.id)
            return

        cost, _ = self.aoe.usage(session.id)
        ws.save_history(step.id, run["n"], run["start_sha"])
        sha = _artifact_sha(ws, step)
        # У шага с одним переходом исхода нет — не пиши «outcome:None».
        trigger = f"outcome:{outcome}" if outcome else "signal"

        with self.db.tx():
            self.db.end_run(run["id"], outcome, end_sha, signalled=True)
            if cost is not None:
                self.db.conn.execute(
                    "UPDATE run SET cost_usd = ? WHERE id = ?", (cost, run["id"])
                )
            if self.gates_on(task, step, outcome):
                revision = self.db.bump(task["id"], status=ST_WAITING, wait_reason="gate")
                self.db.move(
                    task["id"], step.id, step.id, "agent", trigger, revision,
                    artifact_sha=sha,
                )
                self.db.event(task["id"], "gate", {"step": step.id, "outcome": outcome})
                gated = True
            else:
                target = step.target(outcome)
                gated = False
                if target == DONE:
                    revision = self.db.bump(
                        task["id"], status=ST_DONE, step=None, closed_at=now()
                    )
                    self.db.move(
                        task["id"], step.id, DONE, "agent", trigger, revision,
                        artifact_sha=sha,
                    )
                    self.db.event(task["id"], "done", {})
                else:
                    revision = self.db.bump(task["id"], step=target)
                    self.db.move(
                        task["id"], step.id, target, "agent", trigger, revision,
                        artifact_sha=sha,
                    )
        if gated:
            self.mark_stopped(task, session.id)
        else:
            row = self.db.task(task["id"])
            self.aoe.set_color(session.id, "green" if row["status"] == ST_DONE else "amber")

    def end_without_signal(
        self, task, step: Step, run, ws: Workspace, end_sha: str | None, session: Session
    ) -> None:
        """Ход кончился без сигнала.

        Один раз просим закончить автоматически — роль часто просто забыла
        последнюю команду (`PLAN.md` §5 п. 4). Второй раз задача встаёт.
        """
        nudged = self.db.conn.execute(
            "SELECT COUNT(*) c FROM event WHERE task_id = ? AND kind = 'auto_continue' "
            "AND payload LIKE ?",
            (task["id"], f'%"run": {run["id"]}%'),
        ).fetchone()["c"]
        if not nudged:
            self.db.event(task["id"], "auto_continue", {"run": run["id"], "step": step.id})
            try:
                self.aoe.prompt(
                    session.id,
                    "Ход закончился без сигнала. Заверши работу и подай сигнал: "
                    "последнее действие — `orch done`. Если закончить нечем, "
                    "запиши в `## Не решено`, чего не хватает.",
                )
                return
            except AoeError:
                pass

        last = signals.latest(ws.signals, step.id, run["n"])
        ws.save_history(step.id, run["n"], run["start_sha"])
        with self.db.tx():
            self.db.end_run(run["id"], None, end_sha)
            self.db.bump(task["id"], status=ST_WAITING, wait_reason="no_signal")
            self.db.event(
                task["id"],
                "no_signal",
                {"step": step.id, "run": run["n"], "last": (last or {}).get("text", "")[:400]},
            )
        self.mark_stopped(task, run["session_id"])

    # ── кнопки владельца ─────────────────────────────────────────────────
    def button(
        self,
        task_id: str,
        revision: int,
        action: str,
        target: str | None = None,
        comment: str | None = None,
    ) -> str:
        """Единственный вход для панели. Устаревшая ревизия отклоняется."""
        task = self.db.task(task_id)
        if task is None:
            return "нет такой задачи"
        if int(revision) != int(task["revision"]):
            self.db.event(task_id, "stale_button", {"action": action, "revision": revision})
            return "устаревшая кнопка, панель перерисована"
        chain = self.chain_of(task)
        if chain is None:
            return "цепочка задачи не читается"
        handler = {
            "accept": self._btn_accept,
            "back": self._btn_back,
            "again": self._btn_again,
            "continue": self._btn_again,
            "start": self._btn_start,
            "accept_as_is": self._btn_accept,
            "close": self._btn_close,
        }.get(action)
        if handler is None:
            return f"неизвестное действие {action}"
        return handler(task, chain, target, comment)

    def _btn_accept(self, task, chain: Chain, target: str | None, comment: str | None) -> str:
        """Принять ход владельцем.

        `target` — исход, который владелец выбрал сам («принять как есть» на
        пределе заходов или после хода без сигнала). Без него берём исход,
        которым роль закончила.
        """
        step = chain.step(task["step"])
        last = self.db.last_run_of_step(task["id"], step.id)
        outcome = target or (last["outcome"] if last else None)
        if outcome == "дальше":
            outcome = None
        to = step.target(outcome) or step.target(None)
        if to is None:
            return "не понял, каким исходом принимать: назовите исход"
        with self.db.tx():
            if to == DONE:
                revision = self.db.bump(task["id"], status=ST_DONE, step=None, closed_at=now(), wait_reason=None)
            else:
                revision = self.db.bump(task["id"], status=ST_RUNNING, step=to, wait_reason=None)
            self.db.move(task["id"], step.id, to, "human", "button", revision, comment=comment)
            self.db.event(task["id"], "button", {"action": "accept", "to": to})
        return "принято"

    def _btn_back(self, task, chain: Chain, target: str | None, comment: str | None) -> str:
        step = chain.step(task["step"])
        if not target or target not in step.human_moves:
            return f"вернуть можно на: {', '.join(step.human_moves) or '—'}"
        with self.db.tx():
            revision = self.db.bump(task["id"], status=ST_RUNNING, step=target, wait_reason=None)
            self.db.move(task["id"], step.id, target, "human", "button", revision, comment=comment)
            self.db.event(task["id"], "button", {"action": "back", "to": target})
        return f"вернул на {target}"

    def _btn_again(self, task, chain: Chain, target: str | None, comment: str | None) -> str:
        """«Ещё заход» / «Продолжай».

        Если задача встала на пределе заходов, кнопка обязана этот предел
        поднять: иначе движок тут же остановит её снова, и владелец будет
        нажимать в пустоту.
        """
        step = chain.step(task["step"])
        grant = task["wait_reason"] == "max_runs"
        with self.db.tx():
            revision = self.db.bump(task["id"], status=ST_RUNNING, wait_reason=None)
            if grant:
                self.db.move(
                    task["id"], step.id, step.id, "human", "grant_run", revision,
                    comment=comment,
                )
            else:
                self.db.move(
                    task["id"], step.id, step.id, "human", "button", revision,
                    comment=comment,
                )
            self.db.event(
                task["id"], "button", {"action": "again", "step": step.id, "grant": grant}
            )
        return "ещё заход" + (" (предел поднят)" if grant else "")

    def _btn_close(self, task, chain: Chain, target: str | None, comment: str | None) -> str:
        """Закрыть задачу, не доводя до конца.

        Роли заводят заявки в бэклог сами, и часть из них никогда не поедет.
        Пока такую задачу нельзя закрыть, она держит свою ветку и мешает
        завести на ней новую.
        """
        with self.db.tx():
            # `wait_reason` у закрытой задачи не используется — метим им, что
            # её сняли, а не довели. Иначе снятая заявка встаёт в «Готово»
            # рядом с настоящей работой и читается как достижение.
            revision = self.db.bump(
                task["id"], status=ST_DONE, step=None, closed_at=now(),
                wait_reason="closed_by_owner",
            )
            self.db.move(
                task["id"], task["step"], DONE, "human", "button", revision, comment=comment
            )
            self.db.event(task["id"], "closed", {"comment": comment})
        return "закрыта"

    def _btn_start(self, task, chain: Chain, target: str | None, comment: str | None) -> str:
        if task["status"] not in (BACKLOG, QUEUED):
            return "задача уже идёт"
        with self.db.tx():
            self.db.bump(task["id"], status=QUEUED)
            self.db.event(task["id"], "button", {"action": "start"})
        return "в очередь"

    # ── вспомогательное ──────────────────────────────────────────────────
    def chain_of(self, task) -> Chain | None:
        try:
            return parse_chain(task["chain_yaml"], source=f"задача {task['id']}")
        except ChainError as exc:
            self.db.event(task["id"], "chain_broken", {"error": str(exc)})
            return None

    def workspace(self, task) -> Workspace:
        return Workspace(task["worktree_path"] or task["project_path"], task["id"])

    def sheet(self, task) -> dict:
        try:
            return json.loads(task["human_sheet"])
        except (TypeError, json.JSONDecodeError):
            return {}

    def ask_allowed(self, task, step: Step) -> bool:
        entry = self.sheet(task).get(step.id) or {}
        return bool(entry.get("ask", step.human_ask))

    def runs_allowed(self, task, step: Step) -> int:
        """Предел заходов плюс те, что владелец добавил кнопкой «Ещё заход».

        Счётчика нет: добавленные заходы считаются по движениям с триггером
        `grant_run` — так же, как сами заходы считаются по строкам `run`
        (`research/DB-NOTES.md`, правило 1).
        """
        granted = self.db.conn.execute(
            "SELECT COUNT(*) c FROM move WHERE task_id = ? AND to_step = ? "
            "AND trigger = 'grant_run'",
            (task["id"], step.id),
        ).fetchone()["c"]
        return step.max_runs + granted

    def gates_on(self, task, step: Step, outcome: str | None) -> bool:
        entry = self.sheet(task).get(step.id)
        after = entry.get("after") if entry else step.human_after
        if isinstance(after, bool):
            return after
        if isinstance(after, list):
            return outcome in after
        return False

    def stop(self, task_id: str, reason: str, status: str = ST_WAITING, urgent: bool = False) -> None:
        with self.db.tx():
            self.db.bump(task_id, status=status, wait_reason=reason)
            self.db.event(task_id, "stopped", {"reason": reason})
        if urgent or status == ST_WAITING:
            run = self.db.conn.execute(
                "SELECT session_id FROM run WHERE task_id = ? AND session_id IS NOT NULL "
                "ORDER BY id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if run:
                self.mark_stopped(self.db.task(task_id), run["session_id"])

    def mark_stopped(self, task, session_id: str | None) -> None:
        if not session_id:
            return
        self.aoe.set_color(session_id, "red")
        self.aoe.set_urgent(session_id, True)

    def dress(self, task, chain: Chain, step: Step, session_id: str) -> None:
        """Титул, группа, цвет, пуш — ставятся каждый раз, они безвредны."""
        self.aoe.set_title(session_id, _session_title(task, step))
        self.aoe.set_group(session_id, task["group_path"] or f"{GROUP_ROOT}/{task['id']}")
        self.aoe.set_color(session_id, "amber")
        self.aoe.set_urgent(session_id, False)
        gated = self.gates_on(task, step, None) or isinstance(
            (self.sheet(task).get(step.id) or {}).get("after", step.human_after), list
        )
        self.aoe.set_notify(session_id, bool(gated))

    def assemble(self, task, chain: Chain, step: Step, run, ws: Workspace):
        """Собрать промпт и вернуть (текст, sha, id доставленных комментариев)."""
        import hashlib

        comments = self.db.undelivered_comments(task["id"], step.id)
        prev = self.db.last_run_of_step(task["id"], step.id)
        prev_end = None
        if run["n"] > 1:
            rows = self.db.runs_of_step(task["id"], step.id)
            done = [r for r in rows if r["n"] == run["n"] - 1]
            prev_end = done[0]["end_sha"] if done else None

        ctx = promptbuild.Context(
            chain=chain,
            step=step,
            task_id=task["id"],
            task_text=task["text"],
            task_dir=ws.path,
            root=ws.root,
            run_n=run["n"],
            path_steps=self.path_steps(task["id"]),
            came_from=self.came_from(task, step, run),
            comments=[c["comment"] for c in comments],
            ask_allowed=self.ask_allowed(task, step),
            changed_since=ws.diff_stat(prev_end),
            later_artifacts=self.later_artifacts(ws, step, prev),
            owner_edited=self.owner_edited(task, ws, chain),
            sub_prompts=self.sub_prompts(step),
        )
        text = promptbuild.build(ctx)
        if ctx.oversized:
            self.db.event(task["id"], "prompt_oversized", {"step": step.id, "run": run["n"]})
        return text, hashlib.sha256(text.encode()).hexdigest(), [c["id"] for c in comments]

    def path_steps(self, task_id: str) -> list[str]:
        """Путь задачи по шагам; повторный вход в шаг помечен `⟲`."""
        steps = [
            m["to_step"]
            for m in reversed(self.db.moves(task_id, limit=40))
            if m["to_step"] and m["to_step"] != DONE
        ]
        out: list[str] = []
        seen: set[str] = set()
        for s in steps:
            if out and out[-1].lstrip("⟲ ") == s:
                continue
            out.append(f"⟲ {s}" if s in seen else s)
            seen.add(s)
        return out

    def came_from(self, task, step: Step, run) -> str:
        if run["n"] == 1 and not self.db.moves(task["id"], limit=2):
            return ""
        last = next(
            (m for m in self.db.moves(task["id"], limit=10) if m["to_step"] == step.id), None
        )
        if last is None:
            return ""
        if last["actor"] == "human":
            if last["from_step"] == step.id:
                return promptbuild.came_from_phrase("again")
            return promptbuild.came_from_phrase("human")
        if last["actor"] == "agent" and last["from_step"] != step.id:
            return promptbuild.came_from_phrase("role", last["from_step"])
        return ""

    def later_artifacts(self, ws: Workspace, step: Step, prev) -> list[str]:
        """Файлы из `reads`, обновлённые после прошлого захода этого шага."""
        if not prev or not prev["ended_at"]:
            return []
        import os

        from .db import epoch

        cutoff = epoch(prev["ended_at"])
        if cutoff is None:
            return []
        out = []
        for name in step.reads:
            path = ws.artifacts / name
            try:
                if os.path.getmtime(path) > cutoff:
                    out.append(name)
            except OSError:
                continue
        return out

    def owner_edited(self, task, ws: Workspace, chain: Chain) -> list[str]:
        """Файлы, отпечаток которых изменился после сдачи роли (`PLAN.md` §5).

        Смотрим последнюю сдачу каждого шага: владелец мог поправить руками
        файл любой из пройденных ролей, не только предыдущей.
        """
        seen: set[str] = set()
        out: list[str] = []
        for move in self.db.moves(task["id"], limit=40):
            if move["actor"] != "agent" or not move["artifact_sha"] or not move["from_step"]:
                continue
            if move["from_step"] in seen:
                continue
            seen.add(move["from_step"])
            try:
                prev_step = chain.step(move["from_step"])
            except ChainError:
                continue
            current = _artifact_sha(ws, prev_step)
            if current and current != move["artifact_sha"]:
                out.extend(prev_step.artifact)
        return out

    def sub_prompts(self, step: Step) -> list[str]:
        """Пути к ролям подагентов, которые называет сама роль шага.

        Угадывать по имени шага нельзя: шаг `code-review` пользуется файлами
        `sub-review-defects.md` и `sub-review-security.md`, и никакая маска по
        имени шага их не находит. Роль называет их прямо в своём тексте —
        оттуда и берём, тогда список не разъедется с промптом.
        """
        import re

        from .chain import prompts_dir

        role = prompts_dir() / f"{step.prompt_file}.md"
        try:
            text = role.read_text(encoding="utf-8")
        except OSError:
            return []
        names = sorted(set(re.findall(r"\bsub-[a-z0-9-]+\.md\b", text)))
        return [str(prompts_dir() / n) for n in names if (prompts_dir() / n).exists()]


# ── свободные функции ────────────────────────────────────────────────────
def _epoch_now() -> float:
    import time

    return time.time()


def _session_title(task, step: Step) -> str:
    order = ""
    return f"{task['id']} · {order}{step.id}".replace("  ", " ")


def _artifact_sha(ws: Workspace, step: Step) -> str | None:
    parts = [art.sha(ws.artifacts / name) or "" for name in step.artifact]
    if not any(parts):
        return None
    import hashlib

    return hashlib.sha256("".join(parts).encode()).hexdigest()


def _title_from(text: str) -> str:
    """Титул — первые слова текста, очищенные от разметки.

    Мастер пишет ТЗ размеченным markdown («**Цель.** …»), и без чистки
    строка задачи в панели начиналась со звёздочек и слова «Цель».
    """
    first = ""
    for line in text.strip().splitlines():
        line = re.sub(r"[*_`#>]+", "", line).strip()
        line = re.sub(r"^(цель|задача|результат)[.:]\s*", "", line, flags=re.I)
        if line:
            first = line
            break
    words = (first or "задача").split()
    return " ".join(words[:7])[:60] or "задача"


def _slug(title: str) -> str:
    table = str.maketrans(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
        "abvgdeejzijklmnoprstufhccss'y'eua",
    )
    s = title.lower().translate(table)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    # Обрезаем сначала, чистим дефисы потом: наоборот обрезка снова оставляет
    # дефис на конце, и имя ветки в базе расходится с именем настоящей ветки
    # (`orch push` отвечает «src refspec does not match any»).
    return s[:32].strip("-") or "task"
