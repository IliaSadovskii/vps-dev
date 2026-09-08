"""Клиент Agent of Empires: HTTP к 127.0.0.1:8065, никаких WebSocket.

Источник истины о ходе — один `GET /api/sessions?state=live` на проход
(`research/RISKS.md` п. 2). Внешние действия идемпотентны: сессия создаётся с
`idempotency_key = задача/шаг/заход`, промпт отправляется только если у захода
нет `prompt_sent_at`, титул и цвет ставятся всегда — они безвредны.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .clock import epoch as parse_time

# Порт демона — параметр развёртывания: рабочий демон на 8065, запасной для
# проверки плагина на другом. Настройка плагина главнее переменной окружения,
# она и передаётся в конструктор.
BASE = os.environ.get("ORCH_AOE_URL", "http://127.0.0.1:8065")

# Статусы сессии AoE, как они приходят по проводу (PascalCase).
STARTING, RUNNING, WAITING, IDLE, ERROR, STOPPED = (
    "Starting", "Running", "Waiting", "Idle", "Error", "Stopped"
)

# Режим полных прав по агентам. AoE берёт его флагом `yolo_mode` при создании;
# карта нужна для журнала и для будущей смены режима на живой сессии.
FULL_ACCESS_MODE = {
    "claude": "bypassPermissions",
    "codex": "agent-full-access",
    "opencode": "bypassPermissions",
}


class AoeError(Exception):
    def __init__(self, status: int, body: str, path: str) -> None:
        super().__init__(f"{path}: HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body
        self.path = path

    @property
    def error_code(self) -> str:
        try:
            return json.loads(self.body).get("error", "")
        except (json.JSONDecodeError, AttributeError):
            return ""


@dataclass
class Session:
    """Строка сессии из `GET /api/sessions`, только нужные поля."""

    id: str
    status: str
    title: str
    project_path: str
    group: str
    worker_state: str
    idle_entered_at: str | None
    raw: dict

    @classmethod
    def of(cls, raw: dict) -> Session:
        return cls(
            id=raw.get("id", ""),
            status=raw.get("status", "Unknown"),
            title=raw.get("title") or "",
            project_path=raw.get("project_path") or "",
            group=(raw.get("group_path") or "").strip(),
            worker_state=raw.get("acp_worker_state") or "",
            idle_entered_at=raw.get("idle_entered_at"),
            raw=raw,
        )

    def turn_ended(self, prompt_sent_at: str | None) -> bool:
        """Ход кончился, а не «ещё не начинался».

        Сразу после `POST /acp/prompt` статус несколько секунд остаётся
        прежним `Idle` (спайк 2), поэтому одного `Idle` мало: нужно, чтобы в
        него вошли позже отправки промпта. Времена сравниваются числами:
        AoE отдаёт RFC3339 с долями секунды и `+00:00`, мы пишем `...Z` — как
        строки они сравниваются неверно.
        """
        if self.status != IDLE:
            return False
        if not prompt_sent_at:
            return True
        entered = parse_time(self.idle_entered_at)
        sent = parse_time(prompt_sent_at)
        if entered is None or sent is None:
            return False
        return entered > sent


class Aoe:
    def __init__(self, base: str = BASE, timeout: float = 30.0) -> None:
        self.base = base.rstrip("/")
        self.timeout = timeout

    # ── транспорт ────────────────────────────────────────────────────────
    def call(self, method: str, path: str, body: dict | None = None, timeout: float | None = None):
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as exc:
            raise AoeError(exc.code, exc.read().decode(), path) from None
        except urllib.error.URLError as exc:
            raise AoeError(0, str(exc.reason), path) from None
        return json.loads(raw) if raw.strip() else {}

    # ── чтение ───────────────────────────────────────────────────────────
    def sessions(self) -> dict[str, Session]:
        """Все живые сессии одним вызовом: карта id → сессия."""
        data = self.call("GET", "/api/sessions?state=live")
        return {s["id"]: Session.of(s) for s in data.get("sessions", [])}

    def session(self, sid: str) -> Session | None:
        """Одна сессия, включая заархивированную.

        Маршрута `GET /api/sessions/{id}` в AoE нет — только `PATCH` и
        `DELETE`. Поэтому ищем в полном списке: без `state=live` он отдаёт и
        архив, а именно там оказывается сессия предыдущего шага, когда её
        успели убрать из живых.
        """
        try:
            data = self.call("GET", "/api/sessions")
        except AoeError:
            return None
        for raw in data.get("sessions", []):
            if raw.get("id") == sid:
                return Session.of(raw)
        return None

    def usage(self, sid: str) -> tuple[float | None, float | None]:
        """Стоимость и длительность последнего хода из событий `UsageUpdated`.

        Цену сообщает только Claude; чего нет — `None`, движок не выдумывает.
        """
        try:
            data = self.call("GET", f"/api/sessions/{sid}/acp/replay?view=raw&limit=200")
        except AoeError:
            return None, None
        events = data if isinstance(data, list) else data.get("events", [])
        cost = duration = None
        for ev in events:
            blob = json.dumps(ev, ensure_ascii=False)
            if "UsageUpdated" not in blob and "usage" not in blob.lower():
                continue
            cost = _dig_number(ev, ("cost_usd", "total_cost_usd", "cost")) or cost
            duration = _dig_number(ev, ("duration_s", "duration_ms")) or duration
        return cost, duration

    # ── создание и ход ───────────────────────────────────────────────────
    def create(
        self,
        *,
        path: str,
        agent: str,
        model: str,
        effort: str | None,
        title: str,
        group: str,
        idempotency_key: str,
    ) -> Session:
        """Обычная сессия в готовом каталоге. Полей `worktree_*` здесь нет.

        Рабочую копию задачи делает движок (`git worktree add`), а AoE о ней
        не знает вовсе. Причина в интерфейсе: сайдбар веба сворачивает все
        сессии с одинаковыми `main_repo_path` и `branch` в одну строку
        («one row per worktree», `web/src/hooks/useWorkspaces.ts`) и
        подписывает её именем ветки. Задача из восьми шагов превращалась в
        одну строку без титулов, и попасть в сессию прошлого шага было
        неоткуда. У сессии без ветки ключ строится по её `id`, поэтому
        каждый шаг виден отдельной строкой со своим титулом.
        """
        body = {
            "path": path,
            "tool": agent,
            "view": "structured",
            "title": title,
            "group": group,
            "agent_name": agent,
            "agent_model": model,
            "yolo_mode": True,
            "trust_hooks": True,
            "idempotency_key": idempotency_key,
        }
        if effort:
            body["agent_effort"] = effort
        return Session.of(self.call("POST", "/api/sessions?wait=ready", body, timeout=180))

    def prompt(self, sid: str, text: str, attempts: int = 3) -> dict:
        """Отправить промпт. `session_transient` — сессия ещё не готова, ждём."""
        last: AoeError | None = None
        for attempt in range(attempts):
            try:
                return self.call(
                    "POST", f"/api/sessions/{sid}/acp/prompt", {"text": text}, timeout=60
                )
            except AoeError as exc:
                last = exc
                if exc.error_code != "session_transient":
                    raise
                time.sleep(2 * (attempt + 1))
        raise last  # type: ignore[misc]

    def cancel(self, sid: str) -> None:
        try:
            self.call("POST", f"/api/sessions/{sid}/acp/cancel", {})
        except AoeError:
            pass

    def set_model(self, sid: str, model: str) -> bool:
        """Сменить модель живой сессии. Отказ — едем на прежней."""
        try:
            self.call(
                "POST",
                f"/api/sessions/{sid}/acp/config-option",
                {"config_id": "model", "value": model},
            )
            return True
        except AoeError:
            return False

    def option_now(self, sid: str, option: str) -> str | None:
        """Текущее значение опции сессии по последнему `ConfigOptionsUpdated`."""
        try:
            data = self.call("GET", f"/api/sessions/{sid}/acp/replay?view=raw&limit=400")
        except AoeError:
            return None
        current = None
        for frame in data.get("frames", []) if isinstance(data, dict) else []:
            event = frame.get("event") or {}
            updated = event.get("ConfigOptionsUpdated")
            if not updated:
                continue
            for item in updated.get("options") or []:
                if item.get("id") == option:
                    current = item.get("current_value")
        return current

    def apply_effort(self, sid: str, effort: str, wait_s: float = 20.0) -> bool:
        """Усилие ставится тем же вызовом, что и модель.

        При создании сессии `agent_effort` до адаптера доезжает, но объявляет
        его адаптер не мгновенно, а заход в уже живой сессии (`context: own`)
        его и вовсе не переставит: та создавалась под усилие прошлого шага.
        Поэтому сначала ждём объявленного значения и только потом ставим.
        """
        deadline = time.time() + wait_s
        while time.time() < deadline:
            if self.option_now(sid, "effort") == effort:
                return True
            time.sleep(2)
        self._quiet(
            "POST",
            f"/api/sessions/{sid}/acp/config-option",
            {"config_id": "effort", "value": effort},
        )
        deadline = time.time() + wait_s
        while time.time() < deadline:
            if self.option_now(sid, "effort") == effort:
                return True
            time.sleep(2)
        return False

    def model_now(self, sid: str) -> str | None:
        """Какая модель стоит в сессии на самом деле.

        В строке сессии AoE модель не показывает, зато адаптер объявляет её
        в событии `ConfigOptionsUpdated`. Берём последнее такое событие.
        """
        try:
            data = self.call("GET", f"/api/sessions/{sid}/acp/replay?view=raw&limit=400")
        except AoeError:
            return None
        current = None
        for frame in data.get("frames", []) if isinstance(data, dict) else []:
            event = frame.get("event") or {}
            update = event.get("ConfigOptionsUpdated")
            if not update:
                continue
            for option in _options_of(update):
                if option.get("id") == "model" or option.get("category") == "model":
                    current = option.get("current_value")
        return current

    def apply_model(self, sid: str, model: str, tries: int = 2, wait_s: float = 20.0) -> bool:
        """Поставить модель и дождаться, что адаптер её принял.

        `agent_model` при создании сессии до Claude не доезжает: AoE передаёт
        его переменной `AOE_AGENT_MODEL` (`src/acp/supervisor.rs`), а
        `claude-agent-acp` её не читает — переменная для встроенного
        `aoe-agent`. Сессия молча остаётся на модели адаптера по умолчанию
        (у Claude это Opus 1M). Единственный работающий путь — тот же вызов,
        которым меняют модель живой сессии, и проверка по `ConfigOptionsUpdated`.
        """
        for attempt in range(tries):
            if self.model_now(sid) == model:
                return True
            self.set_model(sid, model)
            deadline = time.time() + wait_s
            while time.time() < deadline:
                if self.model_now(sid) == model:
                    return True
                time.sleep(2)
        return self.model_now(sid) == model

    # ── оформление (всегда безвредно, ставится каждый проход) ────────────
    def set_title(self, sid: str, title: str) -> None:
        self._quiet("PATCH", f"/api/sessions/{sid}", {"title": title})

    def set_group(self, sid: str, group: str) -> None:
        self._quiet("PATCH", f"/api/sessions/{sid}/group", {"group": group})

    def set_color(self, sid: str, color: str | None) -> None:
        self._quiet("PATCH", f"/api/sessions/{sid}/color", {"color": color})

    def set_notify(self, sid: str, on_idle: bool) -> None:
        self._quiet(
            "PATCH", f"/api/sessions/{sid}/notifications", {"notify_on_idle": on_idle}
        )

    def set_urgent(self, sid: str, urgent: bool) -> None:
        """Флаг «срочно» — файл, который читает сортировка Attention."""
        path = hooks_dir() / sid
        try:
            path.mkdir(parents=True, exist_ok=True)
            (path / "attention.json").write_text(
                json.dumps({"urgent": bool(urgent)}), encoding="utf-8"
            )
        except OSError:
            pass

    def archive(self, sid: str) -> None:
        # Именно PATCH с телом: POST на этот маршрут отвечает 405 и молча
        # ничего не архивирует.
        self._quiet("PATCH", f"/api/sessions/{sid}/archive", {"archived": True})

    def answer_question(self, sid: str, nonce: str, answers: dict) -> bool:
        try:
            self.call(
                "POST",
                f"/api/sessions/{sid}/acp/elicitations/{nonce}",
                {"action": "accept", "answers": answers},
            )
            return True
        except AoeError:
            return False

    def pending_question(self, sid: str) -> dict | None:
        """Висящий вопрос роли: нонс и варианты, чтобы ответить автоматом."""
        try:
            data = self.call("GET", f"/api/sessions/{sid}/acp/replay?view=raw&limit=200")
        except AoeError:
            return None
        events = data if isinstance(data, list) else data.get("events", [])
        pending: dict | None = None
        for ev in events:
            blob = json.dumps(ev, ensure_ascii=False)
            if "ElicitationRequested" in blob:
                pending = ev
            elif "ElicitationResolved" in blob:
                pending = None
        return pending

    def _quiet(self, method: str, path: str, body: dict) -> None:
        try:
            self.call(method, path, body)
        except AoeError:
            pass


def hooks_dir() -> Path:
    """Каталог, через который AoE читает флаги сессий (`attention.json`).

    Это недокументированная договорённость с хостом: путь взят из его
    исходников, и при обновлении AoE может уехать. `orch doctor` проверяет,
    что каталог на месте и пишется.
    """
    return Path(f"/tmp/aoe-hooks-{os.getuid()}")


def _options_of(update) -> list[dict]:
    """Список настроек из `ConfigOptionsUpdated`: форма события не обещана."""
    if isinstance(update, dict):
        for key in ("options", "config_options", "configOptions"):
            value = update.get(key)
            if isinstance(value, list):
                return [o for o in value if isinstance(o, dict)]
        return [update] if "current_value" in update else []
    if isinstance(update, list):
        return [o for o in update if isinstance(o, dict)]
    return []


def _dig_number(obj, keys: tuple[str, ...]) -> float | None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, (int, float)):
                return float(v) / (1000.0 if k.endswith("_ms") else 1.0)
            got = _dig_number(v, keys)
            if got is not None:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = _dig_number(v, keys)
            if got is not None:
                return got
    return None
