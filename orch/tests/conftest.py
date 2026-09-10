"""Поддельный AoE в памяти и заготовки задач для тестов движка.

Живой AoE тесты не трогают: всё, что ниже, — та же поверхность вызовов,
но состояние сессий двигает тест, а не агент.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from orch.aoe import IDLE, RUNNING, Session
from orch.db import Db
from orch.engine import Engine, Settings


@pytest.fixture(autouse=True)
def _не_из_среды_агента(monkeypatch):
    """Тесты идут как из терминала владельца, а не изнутри сессии AoE.

    `orch gate` и кнопки `orch task move` отказывают, когда видят
    `AOE_ARTIFACT_DIR`: это решение владельца, а не роли. Прогон тестов
    внутри сессии AoE (а он там и идёт, когда правят изнутри) подхватывал эту
    переменную и валил четверо ворот.
    """
    monkeypatch.delenv("AOE_ARTIFACT_DIR", raising=False)


@pytest.fixture(autouse=True)
def _не_трогаем_живой_inbox(tmp_path_factory, monkeypatch):
    """Ни один тест не читает настоящий `~/.local/share/orch/inbox`.

    `reconcile()` начинается с `take_inbox()`, и тест, забывший подменить
    каталог, съедал живую заявку владельца молча: файл удаляется всегда, а
    задача заводилась в базе теста. Однажды такой прогон снёс и рабочую
    копию живой задачи (`free_branch` увидел «чужую» ветку).
    """
    import orch.inbox as inbox_mod

    monkeypatch.setattr(inbox_mod, "INBOX", tmp_path_factory.mktemp("inbox"))


class FakeAoe:
    """Тот же интерфейс, что у `orch.aoe.Aoe`, но без сети."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.prompts: list[tuple[str, str]] = []
        self.cancels: list[str] = []
        self.colors: dict[str, str] = {}
        self.titles: dict[str, str] = {}
        self.notify: dict[str, bool] = {}
        self.urgent: dict[str, bool] = {}
        self.archived: list[str] = []
        self.pinned: dict[str, bool] = {}
        self.unread: dict[str, bool] = {}
        self.by_key: dict[str, str] = {}
        self.acp_ids: dict[str, str] = {}
        self.next_id = 1
        self.worktree_root = "/tmp/fake-worktree"
        self.fail_create = False
        self.model_apply_fails = False
        self.cost: float | None = None
        # Откуда брать «сейчас» для `idle_entered_at`: тесты с управляемым
        # временем подменяют.
        self.now = time.time

    # чтение
    def sessions(self) -> dict[str, Session]:
        """Только живые: заархивированные из списка пропадают, как в AoE."""
        return {
            sid: Session.of(raw)
            for sid, raw in self.rows.items()
            if sid not in self.archived
        }

    def acp_session_id(self, sid: str) -> str | None:
        """uuid сессии агента: имя файла транскрипта. Тест ставит его сам."""
        return self.acp_ids.get(sid)

    def session(self, sid: str) -> Session | None:
        """Одна сессия, включая заархивированную."""
        raw = self.rows.get(sid)
        return Session.of(raw) if raw else None

    def usage(self, sid: str):
        return self.cost, None

    def pending_question(self, sid: str):
        return None

    # создание и ход
    def create(self, *, path, agent, model, effort, title, group,
               idempotency_key) -> Session:
        """Обычная сессия в готовом каталоге: полей worktree_* больше нет —
        рабочую копию задачи делает движок сам."""
        if self.fail_create:
            from orch.aoe import AoeError

            raise AoeError(500, "{}", "/api/sessions")
        if idempotency_key in self.by_key:
            return self.session(self.by_key[idempotency_key])
        sid = f"s{self.next_id}"
        self.next_id += 1
        project = path
        self.rows[sid] = {
            "id": sid,
            "status": IDLE,
            "title": title,
            "project_path": project,
            "group_path": group or "",
            "acp_worker_state": "running",
            "idle_entered_at": None,
            # Модель адаптер получает не при создании: движок ставит её
            # отдельным вызовом до промпта (см. Aoe.apply_model).
            "acp_agent_model": None,
        }
        self.by_key[idempotency_key] = sid
        return self.session(sid)

    def prompt(self, sid: str, text: str, attempts: int = 3) -> dict:
        self.prompts.append((sid, text))
        self.rows[sid]["status"] = RUNNING
        return {"disposition": "sent"}

    def cancel(self, sid: str) -> None:
        self.cancels.append(sid)

    def set_model(self, sid: str, model: str) -> bool:
        self.rows[sid]["acp_agent_model"] = model
        return True

    def model_now(self, sid: str) -> str | None:
        return self.rows.get(sid, {}).get("acp_agent_model")

    def apply_model(self, sid: str, model: str, tries: int = 2, wait_s: float = 20.0) -> bool:
        if self.model_apply_fails:
            return False
        self.set_model(sid, model)
        return True

    # оформление
    def set_title(self, sid, title): self.titles[sid] = title
    def set_group(self, sid, group): self.rows[sid]["group_path"] = group
    def set_pinned(self, sid, pinned): self.pinned[sid] = pinned
    def set_unread(self, sid, unread): self.unread[sid] = unread
    def set_color(self, sid, color): self.colors[sid] = color
    def set_notify(self, sid, on_idle): self.notify[sid] = on_idle
    def set_urgent(self, sid, urgent): self.urgent[sid] = urgent
    def archive(self, sid): self.archived.append(sid)
    def answer_question(self, sid, nonce, answers): return True

    # управление из теста
    def finish_turn(self, sid: str) -> None:
        """Ход кончился: `Idle`, вошли в него позже отправки промпта."""
        self.rows[sid]["status"] = IDLE
        self.rows[sid]["idle_entered_at"] = _later(self.now)

    def set_status(self, sid: str, status: str, worker: str = "running") -> None:
        self.rows[sid]["status"] = status
        self.rows[sid]["acp_worker_state"] = worker

    def drop(self, sid: str) -> None:
        self.rows.pop(sid, None)


def _later(now=time.time) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now() + 60))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Пустой репозиторий: рабочая копия задачи в тестах."""
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=root, check=True,
                   env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
                        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    return root


@pytest.fixture
def engine(tmp_path: Path, repo: Path) -> Engine:
    fake = FakeAoe()
    fake.worktree_root = str(tmp_path / "wt")
    eng = Engine(Db(tmp_path / "orch.db"), fake, Settings(max_running=3))
    eng.repo = repo  # удобство тестов
    return eng


@pytest.fixture
def fake(engine: Engine) -> FakeAoe:
    return engine.aoe


class Clock:
    """Управляемое время: отметки базы и «сейчас» движка идут от него.

    Выдержки движка (полминуты между побудками, между отменами вопроса)
    иначе не проверить, не ожидая их по-настоящему.
    """

    def __init__(self) -> None:
        self.t = 1_800_000_000.0

    def tick(self, seconds: float) -> None:
        self.t += seconds

    def stamp(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.t))

    def stamp_precise(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(self.t)) + f".{int((self.t % 1) * 1e6):06d}Z"


@pytest.fixture
def clock(monkeypatch, engine: Engine) -> Clock:
    import orch.db as db_mod
    import orch.engine as engine_mod

    clk = Clock()
    engine.aoe.now = lambda: clk.t
    monkeypatch.setattr(db_mod, "now", clk.stamp)
    monkeypatch.setattr(db_mod, "now_precise", clk.stamp_precise)
    monkeypatch.setattr(engine_mod, "now", clk.stamp)
    monkeypatch.setattr(engine_mod, "_epoch_now", lambda: clk.t)
    return clk
