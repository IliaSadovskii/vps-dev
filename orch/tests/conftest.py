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
        self.by_key: dict[str, str] = {}
        self.next_id = 1
        self.worktree_root = "/tmp/fake-worktree"
        self.fail_create = False
        self.cost: float | None = None

    # чтение
    def sessions(self) -> dict[str, Session]:
        """Только живые: заархивированные из списка пропадают, как в AoE."""
        return {
            sid: Session.of(raw)
            for sid, raw in self.rows.items()
            if sid not in self.archived
        }

    def session(self, sid: str) -> Session | None:
        """Одна сессия, включая заархивированную."""
        raw = self.rows.get(sid)
        return Session.of(raw) if raw else None

    def usage(self, sid: str):
        return self.cost, None

    def pending_question(self, sid: str):
        return None

    # создание и ход
    def create(self, *, path, agent, model, effort, title, group, branch,
               new_branch, idempotency_key, base_branch=None) -> Session:
        if self.fail_create:
            from orch.aoe import AoeError

            raise AoeError(500, "{}", "/api/sessions")
        if idempotency_key in self.by_key:
            return self.session(self.by_key[idempotency_key])
        sid = f"s{self.next_id}"
        self.next_id += 1
        # Рабочая копия сессии существует на диске: движок пишет в неё папку
        # задачи до отправки промпта.
        project = f"{self.worktree_root}/{branch}" if branch else path
        Path(project).mkdir(parents=True, exist_ok=True)
        self.rows[sid] = {
            "id": sid,
            "status": IDLE,
            "title": title,
            "project_path": project,
            "acp_worker_state": "running",
            "idle_entered_at": None,
            "acp_agent_model": model,
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

    # оформление
    def set_title(self, sid, title): self.titles[sid] = title
    def set_group(self, sid, group): pass
    def set_color(self, sid, color): self.colors[sid] = color
    def set_notify(self, sid, on_idle): self.notify[sid] = on_idle
    def set_urgent(self, sid, urgent): self.urgent[sid] = urgent
    def archive(self, sid): self.archived.append(sid)
    def answer_question(self, sid, nonce, answers): return True

    # управление из теста
    def finish_turn(self, sid: str) -> None:
        """Ход кончился: `Idle`, вошли в него позже отправки промпта."""
        self.rows[sid]["status"] = IDLE
        self.rows[sid]["idle_entered_at"] = _later()

    def set_status(self, sid: str, status: str, worker: str = "running") -> None:
        self.rows[sid]["status"] = status
        self.rows[sid]["acp_worker_state"] = worker

    def drop(self, sid: str) -> None:
        self.rows.pop(sid, None)


def _later() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 60))


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
