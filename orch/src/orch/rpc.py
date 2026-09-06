"""Протокол воркера плагина AoE: JSON-RPC 2.0 построчно по stdio.

Воркер — клиент: пишет запросы в stdout и читает ответы из stdin. Хост шлёт
воркеру уведомления о кликах по кнопкам панели («fire-and-forget», без ответа)
и запросы команд палитры. Всё, что не протокол, идёт в stderr.
"""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Callable
from typing import Any

METHOD_NOT_FOUND = -32601


def log(*parts: object) -> None:
    print(*parts, file=sys.stderr, flush=True)


class Rpc:
    """Двусторонний JSON-RPC по stdio.

    `call` шлёт запрос хосту и ждёт ответа; входящие запросы и уведомления
    хоста отдаются обработчику по последнему сегменту имени метода (хост
    присылает `plugin.<id>.<cmd>` для команд и `<method>` как есть для кнопок).
    """

    def __init__(
        self,
        handler: Callable[[str, dict], Any],
        stdin=None,
        stdout=None,
    ) -> None:
        self._handler = handler
        self._in = stdin or sys.stdin
        self._out = stdout or sys.stdout
        self._write_lock = threading.Lock()
        self._next_id = 0
        self._id_lock = threading.Lock()
        self._pending: dict[int, threading.Event] = {}
        self._replies: dict[int, dict] = {}
        self._stopped = threading.Event()

    # ── исходящие ────────────────────────────────────────────────────────
    def _send(self, obj: dict) -> None:
        line = json.dumps(obj, ensure_ascii=False)
        with self._write_lock:
            self._out.write(line + "\n")
            self._out.flush()

    def call(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        """Запрос к хосту. Возвращает `result` или бросает `RpcError`."""
        with self._id_lock:
            self._next_id += 1
            rid = self._next_id
        event = threading.Event()
        self._pending[rid] = event
        self._send(
            {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
        )
        deadline = timeout
        step = 0.25
        while not event.wait(min(step, deadline)):
            deadline -= step
            if self._stopped.is_set():
                self._pending.pop(rid, None)
                raise RpcError(-1, f"канал к хосту закрыт на {method}")
            if deadline <= 0:
                self._pending.pop(rid, None)
                raise RpcError(-1, f"хост не ответил на {method} за {timeout} с")
        reply = self._replies.pop(rid, {})
        self._pending.pop(rid, None)
        if "error" in reply:
            err = reply["error"]
            raise RpcError(err.get("code", -1), err.get("message", ""), err.get("data"))
        return reply.get("result") or {}

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    # ── входящие ─────────────────────────────────────────────────────────
    def serve(self) -> None:
        """Читать stdin до EOF. Возврат = хост закрыл канал, пора выходить."""
        for raw in self._in:
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                log("orch-plugin: не разобрал строку:", raw[:200])
                continue
            if "method" in msg:
                # Обработчик может звать хост (`ui.state.set`), а ответ придёт
                # в этот же поток чтения — поэтому клик уходит в отдельный
                # поток, иначе воркер запирает сам себя.
                threading.Thread(
                    target=self._dispatch, args=(msg,), daemon=True
                ).start()
            else:
                rid = msg.get("id")
                if isinstance(rid, int) and rid in self._pending:
                    self._replies[rid] = msg
                    self._pending[rid].set()
        self._stopped.set()

    @property
    def stopped(self) -> threading.Event:
        return self._stopped

    def _dispatch(self, msg: dict) -> None:
        method = msg.get("method") or ""
        params = msg.get("params") or {}
        rid = msg.get("id")
        try:
            result = self._handler(method, params)
        except Exception as exc:  # noqa: BLE001 — воркер не должен падать от клика
            log(f"orch-plugin: ошибка в {method}: {exc!r}")
            if rid is not None:
                self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": rid,
                        "error": {"code": -32603, "message": str(exc)},
                    }
                )
            return
        if rid is None:
            return
        if result is NotImplemented:
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "error": {"code": METHOD_NOT_FOUND, "message": f"нет метода {method}"},
                }
            )
        else:
            self._send({"jsonrpc": "2.0", "id": rid, "result": result or {}})


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.data = data
