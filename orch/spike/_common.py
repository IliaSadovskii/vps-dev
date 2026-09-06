"""Общее для скриптов спайка: клиент AoE, ожидание, уборка.

Спайк ходит в живой демон на 127.0.0.1:8065 без токена. Сессии создаются в
группе `orch-test` и архивируются после прогона; ветки `t0-*` удаляются.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8065"
GROUP = "orch-test"
TRIAL = "/projects/kandev-trial"
DAEMON_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/snap/bin"

# Метка прогона в ключе идемпотентности: без неё повторный запуск проверки
# получил бы старую сессию (AoE отдаёт её по ключу даже после архива), а с
# ней — мёртвый воркер и удалённую рабочую копию.
RUN = str(int(time.time()))


def key(name: str) -> str:
    return f"{name}/{RUN}"


class HttpError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:400]}")
        self.status = status
        self.body = body


def call(method: str, path: str, body: dict | None = None, timeout: float = 60.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as exc:
        raise HttpError(exc.code, exc.read().decode()) from None
    return json.loads(raw) if raw.strip() else {}


def sessions() -> list[dict]:
    return call("GET", "/api/sessions?state=live")["sessions"]


def session(sid: str) -> dict | None:
    for s in sessions():
        if s["id"] == sid:
            return s
    try:
        return call("GET", f"/api/sessions/{sid}")
    except HttpError:
        return None


def create(**kw) -> dict:
    body = {
        "path": TRIAL,
        "tool": "claude",
        "view": "structured",
        "group": GROUP,
        "yolo_mode": True,
        "trust_hooks": True,
    }
    body.update(kw)
    return call("POST", "/api/sessions?wait=ready", body, timeout=120)


def prompt(sid: str, text: str) -> dict:
    return call("POST", f"/api/sessions/{sid}/acp/prompt", {"text": text}, timeout=60)


def wait_status(sid: str, want: set[str], timeout: float = 600.0, poll: float = 5.0) -> str:
    """Ждать одного из статусов; вернуть достигнутый или последний."""
    deadline = time.time() + timeout
    last = "?"
    while time.time() < deadline:
        s = session(sid)
        if s is None:
            return "Gone"
        last = s.get("status", "?")
        if last in want:
            return last
        time.sleep(poll)
    return last


def replay_rows(sid: str, limit: int = 200) -> list[dict]:
    data = call("GET", f"/api/sessions/{sid}/acp/replay?view=rows&limit={limit}")
    return data if isinstance(data, list) else data.get("rows", [])


def replay_text(sid: str, limit: int = 200) -> str:
    """Транскрипт одной простынёй.

    Строки приходят потоком по токенам («за», «да», «ча»), поэтому склеиваем
    подряд идущие `text` без разделителя — иначе подстрока не найдётся.
    """
    parts = []
    for row in replay_rows(sid, limit):
        text = row.get("text")
        if text:
            parts.append(text)
        tool = row.get("tool") or {}
        if tool.get("args_preview"):
            parts.append("\n" + tool["args_preview"] + "\n")
    return "".join(parts)


def turn_done(sid: str, sent_at: str | None) -> bool:
    """Ход закончился: сессия `Idle` и в него вошли позже отправки промпта.

    Сразу после `POST /acp/prompt` со статусом `sent` сессия ещё несколько
    секунд числится `Idle` — статус старый. Сравнение с `idle_entered_at`
    отличает «ход кончился» от «ход не начинался».
    """
    s = session(sid)
    if not s or s.get("status") != "Idle":
        return False
    entered = s.get("idle_entered_at")
    if sent_at is None:
        return True
    return bool(entered and entered > sent_at)


def wait_turn(sid: str, sent_at: str, timeout: float = 600.0, poll: float = 5.0) -> str:
    """Ждать конца хода; вернуть статус (`Idle` — ход кончился)."""
    deadline = time.time() + timeout
    last = "?"
    while time.time() < deadline:
        s = session(sid)
        if s is None:
            return "Gone"
        last = s.get("status", "?")
        if last in ("Error", "Waiting"):
            return last
        if turn_done(sid, sent_at):
            return "Idle"
        time.sleep(poll)
    return last


def now_iso() -> str:
    import datetime

    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def archive(sid: str) -> None:
    # Маршрут архива — PATCH с телом; POST отвечает 405.
    try:
        call("PATCH", f"/api/sessions/{sid}/archive", {"archived": True})
    except HttpError:
        pass


def write_task_dir(root: str | Path, task: str, current: dict) -> Path:
    """Положить `.orch/<task>/current.json` в рабочую копию."""
    path = Path(root) / ".orch" / task
    (path / "artifacts").mkdir(parents=True, exist_ok=True)
    (path / "signals").mkdir(parents=True, exist_ok=True)
    (path / "current.json").write_text(
        json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    exclude = Path(root) / ".git" / "info" / "exclude"
    if exclude.parent.is_dir():
        text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if ".orch/" not in text:
            exclude.write_text(text + "\n.orch/\n", encoding="utf-8")
    return path


def git(*args: str, cwd: str | Path = TRIAL) -> str:  # noqa: D401
    out = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=60
    )
    return out.stdout.strip()


def drop_branch(branch: str) -> None:
    """Убрать рабочую копию и ветку прогона; `main` полигона не трогаем.

    Каталог worktree AoE держит под замком, поэтому сначала снимаем замок и
    удаляем каталог, и только потом ветку: удалить ветку, оставив каталог,
    значит сломать следующий прогон («Worktree already exists»).
    """
    if branch in ("main", "master", ""):
        return

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=TRIAL, capture_output=True, text=True)

    for line in git("worktree", "list", "--porcelain").splitlines():
        if not line.startswith("worktree "):
            continue
        path = line.split(" ", 1)[1]
        if not path.startswith("/projects/kandev-trial-worktrees/"):
            continue
        head = git("rev-parse", "--abbrev-ref", "HEAD", cwd=path)
        if head == branch or path.rsplit("/", 1)[-1] == branch:
            run("worktree", "unlock", path)
            run("worktree", "remove", "--force", path)
    run("worktree", "prune")
    run("branch", "-D", branch)


def report(name: str, ok: bool, lines: list[str]) -> int:
    print(f"=== спайк {name}: {'ok' if ok else 'FAIL'}")
    for line in lines:
        print(f"    {line}")
    return 0 if ok else 1


def main_guard(fn):
    """Запустить проверку, вернуть код 0/1, не давать исключению съесть вывод."""
    try:
        code = fn()
    except Exception as exc:  # noqa: BLE001 — спайк должен доложить, а не упасть
        import traceback

        traceback.print_exc()
        print(f"=== спайк: FAIL ({exc.__class__.__name__}: {exc})")
        code = 1
    sys.exit(code)
