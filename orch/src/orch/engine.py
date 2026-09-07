"""Движок: reconcile() по всем идущим задачам раз в 5 секунд.

Реконсиляция вместо событий: каждый проход читает базу, один
`GET /api/sessions`, файлы задач; выводит одно действие на задачу; выполняет;
записывает. Старт после падения — обычный первый проход (`PLAN.md` §2).

Единственный писатель базы — движок. Всё, что меняет задачу, идёт транзакцией
с инкрементом ревизии; внешние действия (создать сессию, послать промпт)
повторяемы по намерению, записанному в базе.

Здесь — жизненный цикл задачи и захода: очередь, рабочая копия, сессия,
наблюдение за ходом, приём сигнала. Остальные обязанности движка лежат
рядом и подмешиваются в класс: заявки (`inbox.py`), мастер (`wizard.py`),
кнопки владельца (`buttons.py`), стенд (`stand_role.py`), контекст промпта
(`promptctx.py`). У всех один `self.db` и один `self.aoe`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from . import artifacts as art
from . import signals
from .aoe import ERROR, RUNNING, STARTING, STOPPED, WAITING, Aoe, AoeError, Session, parse_time
from .chain import (
    DONE,
    Chain,
    ChainError,
    Step,
    apply_preset,
    chains_dir,
    load as load_chain,
    parse as parse_chain,
)
from .db import (
    ABANDONED,
    BACKLOG,
    DONE as ST_DONE,
    FINISHED,
    LIVE,
    QUEUED,
    RUNNING as ST_RUNNING,
    WAITING as ST_WAITING,
    Db,
    epoch,
    now,
)
from .buttons import ButtonsMixin
from .inbox import InboxMixin
from .naming import GROUP_ROOT, session_title, slug, title_from
from .promptctx import PromptContextMixin, artifact_sha
from .stand_role import StandMixin
from .wizard import WizardMixin
from .workspace import (
    Workspace,
    create_worktree,
    has_work,
    remove_worktree,
    worktree_holder,
)

ARCHIVE_AFTER_H = 168

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
    projects_dir: str = "/projects"
    # Модель для служебных ходов, где думать не о чем: уборка стенда.
    cheap_model: str = "haiku"


class Engine(InboxMixin, WizardMixin, ButtonsMixin, StandMixin, PromptContextMixin):
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
        self.adopt_wizards(sessions)
        self.watch_teardown()
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
        stand: bool = False,
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
            sheet = apply_preset(sheet, sheet_edits)
        task_id = self.db.next_task_id()
        title = title or title_from(text)
        if branch:
            busy = self.task_on_branch(branch)
            if busy:
                raise ChainError(
                    f"ветка {branch} занята задачей {busy['id']} ({busy['status']}). "
                    "Одна рабочая копия — одна задача: закройте ту или возьмите "
                    "другую ветку"
                )
        else:
            branch = f"{task_id.lower()}-{slug(title)}"
        with self.db.tx():
            self.db.conn.execute(
                "INSERT INTO task (id, chain, chain_yaml, title, text, project_path, branch, "
                "group_path, step, status, human_sheet, base_branch, author, stand_wanted, "
                "revision, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
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
                    1 if stand else 0,
                    now(),
                ),
            )
            self.db.event(
                task_id,
                "created",
                {"chain": chain.name, "preset": preset, "branch": branch, "base": base},
            )
        # Один мастер — одна заявка: заведя её (в очередь или в бэклог),
        # мастер уходит в архив. Следующая идея — новый мастер.
        self.move_wizard_to(task_id, str(Path(project_path).resolve()))
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
        """Через `ARCHIVE_AFTER_H` после Done сессии задачи уходят в архив.

        Брошенная задача убирается сразу: её сессий уже нет (владелец удалил
        их руками или AoE потерял), ждать от них нечего, а рабочая копия
        занимает диск и держит ветку. Ветку не трогаем никогда — в ней работа.
        """
        for task in self.db.tasks((ABANDONED,)):
            if task["archived_at"]:
                continue
            self.drop_stand(task)
            if task["stand_teardown"] or self.db.task(task["id"])["stand_teardown"]:
                # Уборщик стенда работает в этой копии — снесём её на
                # следующем проходе, когда он закончит.
                continue
            error = ""
            if task["worktree_path"] and Path(task["worktree_path"]).is_dir():
                error = remove_worktree(task["project_path"], task["worktree_path"])
            with self.db.tx():
                self.db.bump(task["id"], archived_at=now())
                self.db.event(
                    task["id"],
                    "abandoned_cleaned",
                    {"worktree_removed": not error, "error": error[:300]},
                )

        for task in self.db.tasks(FINISHED):
            if task["archived_at"] or not task["closed_at"]:
                continue
            closed = epoch(task["closed_at"])
            if closed is None or (time.time() - closed) / 3600 < ARCHIVE_AFTER_H:
                continue
            self.drop_stand(task)
            if self.db.task(task["id"])["stand_teardown"]:
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

        with self.db.tx():
            self.db.prompt_sent(run_id, session.id, sha)
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
        if not self.free_branch(task):
            return False
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

    def free_branch(self, task) -> bool:
        """Освободить ветку задачи, если её держит брошенная копия.

        Git не даёт вычекать одну ветку дважды, а ветка задачи вполне может
        быть занята: так дорабатывают уже открытый PR, копию под который
        оставила прошлая задача. Разбираем три случая, ничего не гадая:
        держит живая задача — стоп с её номером; в копии есть работа — стоп
        с путём, решать владельцу; копия брошена и чиста — снимаем её и
        забираем ветку себе.
        """
        holder = worktree_holder(task["project_path"], task["branch"])
        if holder is None:
            return True
        want = Path(task["project_path"]).resolve()
        if holder.resolve() == want:
            # Ветка вычекана в самом проекте: своей копии из неё не сделать,
            # а переключать чужой рабочий каталог мы не вправе.
            self.db.event(task["id"], "branch_in_project", {"path": str(holder)})
            self.stop(task["id"], "branch_busy")
            return False
        busy = self.db.conn.execute(
            "SELECT id FROM task WHERE worktree_path = ? AND status IN "
            "('queued','running','waiting')",
            (str(holder),),
        ).fetchone()
        if busy:
            self.db.event(
                task["id"], "branch_held", {"by": busy["id"], "path": str(holder)}
            )
            self.stop(task["id"], "branch_busy")
            return False
        if has_work(holder):
            self.db.event(task["id"], "branch_dirty", {"path": str(holder)})
            self.stop(task["id"], "branch_busy")
            return False
        error = remove_worktree(task["project_path"], holder)
        if error:
            # Снять копию не всегда можно: git сверяет путь строкой, а каталог
            # проекта бывает доступен под двумя (например, `/projects` и
            # `~/projects` — один и тот же каталог). Работы в копии нет, так
            # что берём ветку второй копией: это делает `create_worktree`.
            self.db.event(
                task["id"], "branch_release_failed", {"path": str(holder), "error": error[:300]}
            )
            return True
        self.db.event(task["id"], "branch_released", {"path": str(holder)})
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

        # Ключ идемпотентности — задача/шаг/заход плюс время создания задачи и
        # номер строки захода. Время спасает от пересозданной базы; номер
        # строки — от повторного захода с тем же номером: заход, начатый
        # заново, должен получить чистую сессию, а не ту, где лежит прежний
        # разговор (наблюдение прогона T16).
        key = f"{task['id']}@{task['created_at']}/{step.id}/{run['n']}#{run['id']}"
        try:
            session = self.aoe.create(
                path=task["worktree_path"],
                agent=step.agent,
                model=step.model,
                effort=step.effort,
                title=session_title(task["id"], step.id),
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
            self.db.prompt_sent(run["id"], session.id, sha)
            self.db.mark_delivered(comment_ids)
        self.dress(task, chain, step, session.id)

    def on_waiting(self, task, chain: Chain, step: Step, run, session: Session) -> None:
        """`Waiting` = вопрос роли или запрос разрешения."""
        if self.ask_allowed(task, step):
            self.stop(task["id"], "ask", urgent=True)
            return
        # Вопросы выключены листом автономии: закрываем ход и говорим решать самой.
        # После отмены статус ещё несколько секунд остаётся `Waiting`, и без
        # выдержки движок отменял бы тот же вопрос каждый проход.
        if self.recently(task, "question_refused", run, WAKE_GRACE_S):
            return
        self.aoe.cancel(session.id)
        self.db.event(task["id"], "question_refused", {"step": step.id, "run": run["id"]})
        self.repeat_prompt(
            run,
            session,
            "Вопросов не задаём: реши сам, запиши выбор в `## Допущения` и "
            "продолжай. Закончи ход командой `orch done`.",
        )

    def on_error(self, task, chain: Chain, step: Step, run, session: Session) -> None:
        """Один раз «продолжай», второй — остановка с причиной «ошибка»."""
        if self.db.run_events(task["id"], "error_retry", run["id"]):
            # Сессия в ошибке уже после нашего «продолжай» — или ещё в ней
            # через выдержку. До выдержки не смотрим: статус после промпта
            # меняется не сразу.
            if not self.recently(task, "error_retry", run, WAKE_GRACE_S):
                self.stop(task["id"], "error", urgent=True)
            return
        self.db.event(task["id"], "error_retry", {"run": run["id"], "step": step.id})
        if not self.repeat_prompt(
            run, session, "Продолжай с места остановки и закончи ход `orch done`."
        ):
            self.stop(task["id"], "error", urgent=True)

    def wake(self, task, run, session: Session) -> None:
        """Разбудить уснувший воркер промптом. Не больше `WAKE_LIMIT` раз."""
        sent = parse_time(run["prompt_sent_at"])
        if sent and _epoch_now() - sent < WAKE_GRACE_S:
            # Воркер ещё поднимается — после создания сессии или после
            # прошлой побудки: каждая побудка сдвигает `prompt_sent_at`,
            # поэтому попытки идут с выдержкой, а не три подряд за 15 секунд.
            return
        tried = len(self.db.run_events(task["id"], "worker_wake", run["id"]))
        if tried >= WAKE_LIMIT:
            self.db.event(
                task["id"],
                "wake_gave_up",
                {"run": run["id"], "session": session.id, "tries": tried},
            )
            self.stop(task["id"], "no_worker", urgent=True)
            return
        self.db.event(task["id"], "worker_wake", {"run": run["id"], "session": session.id})
        self.repeat_prompt(run, session, "Продолжай с места остановки и закончи ход `orch done`.")

    def repeat_prompt(self, run, session: Session, text: str) -> bool:
        """Повторный промпт в идущий заход: «заверши ход», «продолжай», побудка.

        Обязательно сдвигает `prompt_sent_at`: конец хода считается от
        последней отправки. Без этого следующий проход через пять секунд
        видел старый `Idle` как новый конец хода и закрывал заход, пока роль
        работала (T16, 22:50:38 → 22:50:43).
        """
        try:
            self.aoe.prompt(session.id, text)
        except AoeError as exc:
            self.db.event(run["task_id"], "prompt_failed", {"run": run["id"], "error": str(exc)})
            return False
        with self.db.tx():
            self.db.prompt_sent(run["id"])
        return True

    def recently(self, task, kind: str, run, within_s: float) -> bool:
        """Было ли событие `kind` у этого захода моложе `within_s` секунд."""
        rows = self.db.run_events(task["id"], kind, run["id"])
        if not rows:
            return False
        at = epoch(rows[-1]["at"])
        return at is not None and _epoch_now() - at < within_s

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
        sha = artifact_sha(ws, step)
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
                closed_now = False
                if target == DONE:
                    revision = self.db.bump(
                        task["id"], status=ST_DONE, step=None, closed_at=now()
                    )
                    self.db.move(
                        task["id"], step.id, DONE, "agent", trigger, revision,
                        artifact_sha=sha,
                    )
                    self.db.event(task["id"], "done", {})
                    closed_now = True
                else:
                    revision = self.db.bump(task["id"], step=target)
                    self.db.move(
                        task["id"], step.id, target, "agent", trigger, revision,
                        artifact_sha=sha,
                    )
        if gated:
            self.mark_stopped(task, session.id)
            self.stand_if_wanted(self.db.task(task["id"]))
        else:
            row = self.db.task(task["id"])
            self.aoe.set_color(session.id, "green" if row["status"] == ST_DONE else "amber")
            if closed_now:
                # Задача доведена до конца: стенд больше некому смотреть, а
                # он держит порты, контейнеры и тома.
                self.drop_stand(row)

    def end_without_signal(
        self, task, step: Step, run, ws: Workspace, end_sha: str | None, session: Session
    ) -> None:
        """Ход кончился без сигнала.

        Один раз просим закончить автоматически — роль часто просто забыла
        последнюю команду (`PLAN.md` §5 п. 4). Второй раз задача встаёт.
        """
        if not self.db.run_events(task["id"], "auto_continue", run["id"]):
            self.db.event(task["id"], "auto_continue", {"run": run["id"], "step": step.id})
            if self.repeat_prompt(
                run,
                session,
                "Ход закончился без сигнала. Заверши работу и подай сигнал: "
                "последнее действие — `orch done`. Если закончить нечем, "
                "запиши в `## Не решено`, чего не хватает.",
            ):
                return

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
        self.stand_if_wanted(self.db.task(task["id"]))

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
            self.stand_if_wanted(self.db.task(task_id))

    def mark_stopped(self, task, session_id: str | None) -> None:
        if not session_id:
            return
        self.aoe.set_color(session_id, "red")
        self.aoe.set_urgent(session_id, True)

    def dress(self, task, chain: Chain, step: Step, session_id: str) -> None:
        """Титул, группа, цвет, пуш — ставятся каждый раз, они безвредны."""
        self.aoe.set_title(session_id, session_title(task["id"], step.id))
        self.aoe.set_group(session_id, task["group_path"] or f"{GROUP_ROOT}/{task['id']}")
        self.aoe.set_color(session_id, "amber")
        self.aoe.set_urgent(session_id, False)
        gated = self.gates_on(task, step, None) or isinstance(
            (self.sheet(task).get(step.id) or {}).get("after", step.human_after), list
        )
        self.aoe.set_notify(session_id, bool(gated))

# ── свободные функции ────────────────────────────────────────────────────
def _epoch_now() -> float:
    return time.time()
