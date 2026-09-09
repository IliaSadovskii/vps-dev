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
from . import digest as dg
from . import signals
from .aoe import ERROR, RUNNING, STARTING, STOPPED, WAITING, Aoe, AoeError, Session, parse_time
from .chain import (
    DONE,
    Chain,
    ChainError,
    Step,
    apply_preset,
    gates_on as chain_gates_on,
    load as load_chain,
    parse as parse_chain,
    path_of as chain_path,
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
from .aside_role import AsideMixin
from .buttons import ButtonsMixin
from .inbox import InboxMixin
from .naming import GROUP_ROOT, session_title, slug, title_from
from .promptctx import PromptContextMixin, artifact_sha
from .stand_role import StandMixin
from .wizard import WizardMixin
from .workspace import (
    Workspace,
    create_worktree,
    git_try,
    has_work,
    remove_worktree,
    touched_files,
    worktree_holder,
)

ARCHIVE_AFTER_H = 168

# Пробуждение уснувшего воркера: сколько раз пробуем и сколько ждём после
# отправки промпта, прежде чем считать воркер уснувшим.
WAKE_LIMIT = 3
NUDGES_BEFORE_STOP = 4
# Пауза между толчками: роль, ждущая подагентов, отвечает мгновенно.
NUDGE_GRACE_S = 120.0
WAKE_GRACE_S = 30.0
# Сколько сессия должна простоять в `Idle`, прежде чем толкать её промптом.
# Промпт в занятую сессию AoE отдаёт мосту как `steer`, а тот доставляет его
# с приоритетом «сейчас» — то есть **обрывает** текущую генерацию. Мост при
# этом умеет объявить ход законченным раньше, чем роль на самом деле
# закончила (T26, 17:57: `Stopped{prompt_complete}`, а роль работала), и
# толчок рвал живую работу. Выдержка стоит минуту на забытый `orch done` и
# спасает час работы там, где `Idle` соврал.
IDLE_SETTLE_S = 90.0
# Признак жизни мимо AoE: транскрипт, который агент пишет сам. Если файл
# рос только что, роль работает, что бы ни говорил статус сессии.
ALIVE_S = 60.0


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
    # Предел одновременно работающих сессий AoE: шаги цепочек, стенды,
    # побочные роли.
    # `max_running` считает задачи и до сессий не дотягивается, поэтому
    # три задачи со стендами и наблюдателями клали машину по памяти
    # (`ASIDE-PLAN.md` §10).
    max_sessions: int = 6
    # Сколько памяти должно остаться свободным, чтобы поднимать ещё сессию.
    min_free_mb: int = 1500


class Engine(InboxMixin, WizardMixin, ButtonsMixin, StandMixin, AsideMixin, PromptContextMixin):
    def __init__(self, db: Db, aoe: Aoe | None = None, settings: Settings | None = None) -> None:
        self.db = db
        self.aoe = aoe or Aoe()
        self.settings = settings or Settings()
        self.live_sessions = 0
        # Канал наружу заводится лениво: без токена он молчит.
        self.notifier = None

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
        # Считаем не все живые сессии, а работающие: память и процессор
        # ест ход агента, а сессия в `Idle` стоит почти ничего и висит до
        # архивации неделю. Предохранитель резервирует место под каждую
        # новую сессию (`capacity`), резерв живёт один проход.
        self.live_sessions = sum(
            1 for s in sessions.values() if s.status in (RUNNING, STARTING)
        )
        self.adopt_wizards(sessions)
        self.watch_teardown()
        for row in self.db.tasks(LIVE):
            try:
                self.step_task(row, sessions)
            except Exception as exc:  # noqa: BLE001 — одна задача не роняет проход
                self.db.event(row["id"], "engine_error", {"error": repr(exc)})
        self.watch_clashes()
        # Побочные роли — последними: шаг цепочки важнее наблюдателя и
        # место под сессию занимает первым (`ASIDE-PLAN.md` §2).
        self.pump_asides(sessions)
        self.pump_notify()
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
            if task["wait_reason"] == "no_signal":
                self.late_signal(task)
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

    def late_signal(self, task) -> None:
        """Сигнал, пришедший после того, как задача встала без него.

        Роль, ждущая подагентов, заканчивает ход короткими репликами («жду»),
        и движок принимает их за конец работы. Настоящий `orch done` приходит
        минутами позже, когда задача уже стоит. Терять его нельзя: работа
        сделана, файл написан, а владельца зовут разбираться на пустом месте.
        """
        chain = self.chain_of(task)
        if chain is None or not task["step"] or not task["worktree_path"]:
            return
        try:
            step = chain.step(task["step"])
        except ChainError:
            return
        row = self.db.conn.execute(
            "SELECT * FROM run WHERE task_id = ? AND step = ? ORDER BY id DESC LIMIT 1",
            (task["id"], step.id),
        ).fetchone()
        if row is None or not row["ended_at"]:
            return
        ws = self.workspace(task)
        signal = signals.read(signals.done_path(ws.signals, step.id, row["n"]))
        if not signal or signal.get("kind") != "done":
            return
        outcome = signal.get("outcome")
        if outcome is not None and outcome not in step.next:
            return
        target = step.target(outcome)
        if target is None:
            return
        with self.db.tx():
            self.db.conn.execute(
                "UPDATE run SET outcome = ?, signalled = 1 WHERE id = ?", (outcome, row["id"])
            )
            revision = self.db.bump(task["id"], status=ST_RUNNING, step=target, wait_reason=None)
            self.db.move(
                task["id"], step.id, target, "agent", f"signal_late:{outcome or ''}", revision
            )
            self.db.event(
                task["id"],
                "late_signal",
                {"step": step.id, "run": row["n"], "outcome": outcome, "to": target},
            )
        if row["session_id"]:
            self.aoe.set_urgent(row["session_id"], False)
            self.aoe.set_color(row["session_id"], "green")

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
        notify_gates: bool = False,
    ) -> str:
        """Завести задачу.

        `branch` — работать в названной ветке вместо новой: так задача
        садится на уже открытый PR. Ветка есть — движок подключится к ней,
        нет — заведёт с этим именем. `base` — от чего ответвляться, если
        ветки ещё нет.

        Заводить на занятую ветку можно сколько угодно задач: очередь и
        бэклог места в рабочей копии не занимают. Одна копия — одна работа
        держится позже, на выходе из очереди (`promote_queue`).
        """
        chain = load_chain(chain_path(chain_name))
        sheet = chain.sheet_with_preset(preset)
        if sheet_edits:
            sheet = apply_preset(sheet, sheet_edits)
        task_id = self.db.next_task_id()
        title = title or title_from(text)
        if not branch:
            branch = f"{task_id.lower()}-{slug(title)}"
        with self.db.tx():
            self.db.conn.execute(
                "INSERT INTO task (id, chain, chain_yaml, title, text, project_path, branch, "
                "group_path, step, status, human_sheet, base_branch, author, stand_wanted, "
                "notify_gates, revision, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
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
                    1 if notify_gates else 0,
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
        """Одновременно `running` не больше `max_running`; остальные ждут.

        Вторые ворота — ветка: на одной ветке одна рабочая копия, поэтому
        задача на занятой ветке стоит в очереди, пока та, что в работе, не
        закончится. Задачи на разные ветки её при этом обгоняют.
        """
        running = [t for t in self.db.tasks((ST_RUNNING,))]
        free = self.settings.max_running - len(running)
        if free <= 0:
            return
        for task in self.db.tasks((QUEUED,)):
            if free <= 0:
                return
            chain = self.chain_of(task)
            if chain is None:
                self.stop(task["id"], "chain_broken")
                continue
            busy = self.task_on_branch(task["branch"], skip=task["id"])
            if busy:
                continue
            free -= 1
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
            if self.teardown_session(task["id"]):
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
            if self.teardown_session(task["id"]):
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
        done_runs = self.runs_this_cycle(task, step)
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

        if not self.capacity(task["id"], f"шаг {step.id}"):
            return

        with self.db.tx():
            run_id = self.db.start_run(task["id"], step.id, step.context, start_sha)
            self.db.event(
                task["id"],
                "run_started",
                {"run": run_id, "step": step.id, "n": len(done_runs) + 1,
                 "context": step.context},
            )
        run = self.db.conn.execute("SELECT * FROM run WHERE id = ?", (run_id,)).fetchone()

        session = self.attach_session(task, chain, step, run)
        if session is None:
            return
        ws.write_current(
            step.id, run["n"], session.id, "running", task["branch"], list(step.reads),
            gate_after=self.gate_after(task, step), ask=self.ask_allowed(task, step),
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
        self.dress(task, chain, step, session.id, run["n"])

    def notify(self):
        """Канал наружу. Создаётся один раз и переживает проходы."""
        if self.notifier is None:
            from .notify import Notifier

            self.notifier = Notifier(self)
        return self.notifier

    def pump_notify(self) -> None:
        try:
            self.notify().pump()
        except Exception as exc:  # noqa: BLE001 — канал не роняет проход
            self.note_once(None, "notify_error", {"error": repr(exc)[:300]})

    def capacity(self, task_id: str | None, what: str) -> bool:
        """Можно ли поднять ещё одну сессию AoE.

        Место резервируется сразу: за проход движок заводит несколько
        сессий, и считать их постфактум поздно. Резерв живёт один проход —
        следующий пересчитает от списка AoE.
        """
        if self.live_sessions >= self.settings.max_sessions:
            self.note_once(
                task_id,
                "sessions_capped",
                {"live": self.live_sessions, "limit": self.settings.max_sessions, "for": what},
            )
            return False
        free = free_memory_mb()
        if free is not None and free < self.settings.min_free_mb:
            self.note_once(
                task_id,
                "memory_low",
                {"free_mb": free, "need_mb": self.settings.min_free_mb, "for": what},
            )
            return False
        self.live_sessions += 1
        return True

    def note_once(self, task_id: str | None, kind: str, payload: dict, within_s: float = 300.0) -> None:
        """Событие, которое повторяется каждый проход, пишется раз в пять минут.

        Нехватка памяти держится часами: без выдержки журнал забился бы
        одной и той же строкой раз в пять секунд.
        """
        # Дроссель считается по виду и задаче: та же нехватка памяти на
        # другой задаче — другой сигнал, и молчать о нём нельзя.
        if task_id:
            row = self.db.conn.execute(
                "SELECT at FROM event WHERE kind = ? AND task_id = ? ORDER BY seq DESC LIMIT 1",
                (kind, task_id),
            ).fetchone()
        else:
            row = self.db.conn.execute(
                "SELECT at FROM event WHERE kind = ? AND task_id IS NULL ORDER BY seq DESC LIMIT 1",
                (kind,),
            ).fetchone()
        last = epoch(row["at"]) if row else None
        if last is not None and _epoch_now() - last < within_s:
            return
        self.db.event(task_id, kind, payload)

    def watch_clashes(self) -> None:
        """Две живые задачи полезли в один файл.

        Единственное, чего не видит ни один шаг цепочки: соседей. Но это
        факт, а не суждение, — считается git-ом, без модели и без агента
        (`ASIDE-PLAN.md` §2, сторожа).
        """
        live = [
            t for t in self.db.tasks(LIVE)
            if t["worktree_path"] and Path(t["worktree_path"]).is_dir()
        ]
        if len(live) < 2:
            return
        touched = {
            t["id"]: touched_files(t["worktree_path"], t["base_branch"] or "")
            for t in live
        }
        seen = set()
        for one in live:
            for other in live:
                if one["id"] >= other["id"]:
                    continue
                shared = sorted(touched[one["id"]] & touched[other["id"]])
                if not shared:
                    continue
                pair = f"{one['id']}+{other['id']}"
                if pair in seen:
                    continue
                seen.add(pair)
                self.note_once(
                    one["id"],
                    "watch_file_clash",
                    {"pair": pair, "with": other["id"], "files": shared[:10]},
                    3600.0,
                )

    def task_on_branch(self, branch: str, skip: str | None = None):
        """Задача, которая уже работает в этой ветке, или None.

        Две задачи в одной рабочей копии писали бы `.orch/` друг поверх
        друга, и `orch` в сессии не смог бы понять, чей он. Копию занимает
        только начатая работа: в очереди и в бэклоге на одной ветке задачи
        копятся свободно.
        """
        return self.db.conn.execute(
            "SELECT id, status FROM task WHERE branch = ? AND id IS NOT ? "
            "AND status IN ('running','waiting') LIMIT 1",
            (branch, skip),
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
        """Где идёт заход.

        `fresh` — новая сессия; `continue` — последняя сессия того же агента
        (продолжение разговора предыдущего шага); `own` — последняя сессия
        этого же шага: роль возвращается к себе и помнит свой прошлый заход.
        """
        if step.context == "own":
            prev = self.db.conn.execute(
                "SELECT session_id FROM run WHERE task_id = ? AND step = ? AND id <> ? "
                "AND session_id IS NOT NULL AND void_at IS NULL ORDER BY id DESC LIMIT 1",
                (task["id"], step.id, run["id"]),
            ).fetchone()
            if prev:
                session = self.aoe.session(prev["session_id"])
                if session:
                    return session

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
                title=session_title(
                    task["id"], step.id, run["n"], step.context in ("own", "continue")
                ),
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

    def acp_uuid(self, run, session: Session) -> str | None:
        """uuid сессии агента для захода: имя файла транскрипта.

        Спрашиваем AoE один раз и запоминаем: id сессии AoE и id сессии
        Claude Code — разные, а связь нужна и признаку жизни, и скелету хода
        (без неё он склеивался из транскриптов чужих сессий).
        """
        if run["acp_session_id"]:
            return str(run["acp_session_id"])
        found = self.aoe.acp_session_id(session.id)
        if not found:
            return None
        with self.db.tx():
            self.db.conn.execute(
                "UPDATE run SET acp_session_id = ? WHERE id = ?", (found, run["id"])
            )
        return found

    def role_alive(self, task, run, session: Session) -> bool:
        """Пишет ли роль прямо сейчас — по времени записи её транскрипта.

        `Idle` от AoE бывает преждевременным: мост объявляет ход
        законченным, пока роль работает (T26). Толкать её в этот момент
        значит оборвать ей генерацию, поэтому перед толчком смотрим не на
        статус, а на файл, который пишет сам агент. Не нашли файл — ведём
        себя как раньше: решает выдержка простоя.
        """
        root = task["worktree_path"] or task["project_path"]
        uuid = self.acp_uuid(run, session)
        if not uuid or not root:
            return False
        path = dg.TRANSCRIPTS / dg.project_slug(root) / f"{uuid}.jsonl"
        try:
            touched = path.stat().st_mtime
        except OSError:
            return False
        return _epoch_now() - touched < ALIVE_S

    def apply_model(self, task, step: Step, session: Session) -> None:
        """Поставить модель шага и убедиться, что адаптер её принял.

        Обязательно **до** промпта и на каждом заходе, а не только при смене
        модели в `continue`: `agent_model` при создании сессии до Claude не
        доезжает вовсе, и сессия молча работает на модели адаптера по
        умолчанию — у Claude это Opus, а не то, что записано в цепочке.
        Отказ не останавливает задачу: ход пойдёт на модели по умолчанию, но
        это будет видно в журнале, а не тихо.
        """
        if step.effort and not self.aoe.apply_effort(session.id, step.effort):
            self.db.event(
                task["id"],
                "effort_not_applied",
                {"session": session.id, "want": step.effort},
            )
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
        ws.write_current(
            step.id, run["n"], session.id, "running", task["branch"], list(step.reads),
            gate_after=self.gate_after(task, step), ask=self.ask_allowed(task, step),
        )
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
        self.dress(task, chain, step, session.id, run["n"])

    def on_waiting(self, task, chain: Chain, step: Step, run, session: Session) -> None:
        """`Waiting` = вопрос роли или запрос разрешения."""
        if self.ask_allowed(task, step):
            # Отметка о заданном вопросе живёт в папке задачи: по ней
            # `orch done` отличает выбор, сделанный владельцем внутри хода,
            # от выбора, отложенного на ворота.
            ws = self.workspace(task)
            if not signals.count(ws.signals, "ask", step.id, run["n"]):
                signals.write_aux(ws.signals, "ask", step.id, run["n"], "роль спросила владельца")
                # Отдельное событие, а не общий `stopped`: на вопрос роли
                # подписан Тимлид, и будить его на каждой остановке незачем.
                self.db.event(
                    task["id"], "role_asked", {"step": step.id, "run": run["id"]}
                )
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
            answer = self.aoe.prompt(session.id, text)
        except AoeError as exc:
            self.db.event(run["task_id"], "prompt_failed", {"run": run["id"], "error": str(exc)})
            return False
        # AoE отвечает, что сделала с промптом: `sent` — начала ход, `queued` —
        # положила в очередь, `steered` — доставила в идущий ход, оборвав его
        # генерацию. Последнее означает, что мы толкнули работающую роль, и
        # это надо видеть в журнале, а не искать потом в транскрипте.
        disposition = (answer or {}).get("disposition") if isinstance(answer, dict) else None
        if disposition == "steered":
            self.db.event(
                run["task_id"],
                "prompt_steered",
                {"run": run["id"], "session": session.id, "text": text[:120]},
            )
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
        # Связь «сессия AoE → файл транскрипта» запоминается здесь: к концу
        # хода событие `AcpSessionAssigned` уже точно есть, а нужна она и
        # скелету хода, и признаку жизни роли.
        if not run["acp_session_id"]:
            self.acp_uuid(run, session)
            run = self.db.conn.execute("SELECT * FROM run WHERE id = ?", (run["id"],)).fetchone()
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
        # Толкаем несколько раз, а не один: роль, ждущая подагентов, кончает
        # ход короткой репликой («жду три чтения»), и это неотличимо от
        # забытой команды. Один толчок закрывал такой заход за полминуты,
        # когда работа шла (T19, 14:41).
        # Считать толчки мало: роль отвечает на них мгновенно («жду»), и
        # четыре толчка сгорали за 38 секунд (T19, 15:32:57 → 15:33:29).
        # Между толчками нужна пауза — тогда предел означает время, а не
        # число реплик.
        if self.recently(task, "auto_continue", run, NUDGE_GRACE_S):
            return
        # Толчок — это промпт в чужую сессию, а промпт в занятую сессию рвёт
        # её работу (см. `IDLE_SETTLE_S`). Пока простой свежий, верить ему
        # нельзя: ждём, пока `Idle` устоится. Время считаем по своей отметке,
        # а не по часам AoE: врёт как раз она.
        # Роль пишет транскрипт прямо сейчас — значит `Idle` соврал, и
        # толкать нечего: промпт оборвал бы ей ход.
        if self.role_alive(task, run, session):
            self.note_once(
                task["id"], "idle_lied",
                {"run": run["id"], "step": step.id, "session": session.id}, 300.0,
            )
            return
        # Отметка своя на каждый простой: после толчка роль отвечает и
        # засыпает заново, и новый простой надо выдержать так же, как первый.
        метка = session.idle_entered_at or ""
        свои = [
            e for e in self.db.run_events(task["id"], "idle_seen", run["id"])
            if (json.loads(e["payload"] or "{}").get("idle_at") or "") == метка
        ]
        if not свои:
            self.db.event(
                task["id"],
                "idle_seen",
                {"run": run["id"], "step": step.id, "idle_at": метка},
            )
            return
        first = epoch(свои[0]["at"])
        if first is not None and _epoch_now() - first < IDLE_SETTLE_S:
            return
        nudges = len(self.db.run_events(task["id"], "auto_continue", run["id"]))
        if nudges < NUDGES_BEFORE_STOP:
            self.db.event(task["id"], "auto_continue", {"run": run["id"], "step": step.id})
            if self.repeat_prompt(
                run,
                session,
                "Ход закончился без сигнала. Если ты ждёшь подагентов или "
                "долгую команду — просто продолжай, я спрошу снова. Если "
                "работа закончена, подай сигнал: последнее действие — "
                "`orch done`. Если закончить нечем, запиши в `## Не решено`, "
                "чего не хватает.",
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

    def runs_this_cycle(self, task, step: Step) -> list:
        """Заходы шага после последнего движения владельца.

        Предел держит роли, а не владельца: вернув работу назад, он начинает
        круг заново, и шаги ниже по цепочке должны идти со своим полным
        пределом. Иначе задача, отправленная в Реализацию с воротов, тут же
        встаёт «предел заходов» на Ревью кода, потратившем заходы в прошлом
        круге (T19, 18:59).
        """
        runs = [r for r in self.db.runs_of_step(task["id"], step.id) if not r["void_at"]]
        row = self.db.conn.execute(
            "SELECT at FROM move WHERE task_id = ? AND actor = 'human' ORDER BY id DESC LIMIT 1",
            (task["id"],),
        ).fetchone()
        if row is None:
            return runs
        # Строго позже: заход, начатый в ту же секунду, что и движение
        # владельца, — это и есть заход нового круга.
        return [r for r in runs if (r["started_at"] or "") > row["at"]]

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
        # Ключа может не быть, если лист старше цепочки: тогда действует
        # значение шага, а не «ворот нет».
        after = entry.get("after", step.human_after) if entry else step.human_after
        return chain_gates_on(after, outcome)

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

    def quiet_others(self, task, keep: str | None) -> None:
        """Снять зов со всех сессий задачи, кроме текущей.

        Сессия шага, который уже сходил, оставалась с флагом уведомления и
        красным цветом: сайдбар показывал два зовущих шага сразу, и владелец
        не понимал, какой из них ждёт его на самом деле.
        """
        for row in self.db.conn.execute(
            "SELECT DISTINCT session_id FROM run WHERE task_id = ? AND session_id IS NOT NULL",
            (task["id"],),
        ):
            sid = row["session_id"]
            if not sid or sid == keep:
                continue
            self.aoe.set_urgent(sid, False)
            self.aoe.set_notify(sid, False)
            self.aoe.set_color(sid, "green")

    def dress(self, task, chain: Chain, step: Step, session_id: str, run_n: int = 1) -> None:
        """Титул, группа, цвет, пуш — ставятся каждый раз, они безвредны."""
        self.quiet_others(task, session_id)
        self.aoe.set_title(
            session_id,
            session_title(task["id"], step.id, run_n, step.context in ("own", "continue")),
        )
        self.aoe.set_group(session_id, task["group_path"] or f"{GROUP_ROOT}/{task['id']}")
        self.aoe.set_color(session_id, "amber")
        self.aoe.set_urgent(session_id, False)
        # Уведомление ставим щедро: шаг, который может встать хоть на каком-то
        # исходе или на вопросе, зовёт владельца заранее.
        after = (self.sheet(task).get(step.id) or {}).get("after", step.human_after)
        gated = bool(after)
        self.aoe.set_notify(session_id, bool(gated))

# ── свободные функции ────────────────────────────────────────────────────
def free_memory_mb() -> int | None:
    """Сколько памяти реально доступно, по `MemAvailable`.

    Не `MemFree`: кэш страниц ядро отдаёт само, и по `MemFree` машина с
    тёплым кэшем всегда выглядит забитой.
    """
    try:
        text = Path("/proc/meminfo").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("MemAvailable:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1]) // 1024
    return None


def _epoch_now() -> float:
    return time.time()
