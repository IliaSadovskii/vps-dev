#!/usr/bin/env python3
"""Спайк 4. Плагин: панель рисуется, клик доходит до воркера с `session_id`,
`composer.read` отдаёт черновик поля ввода.

Закрывает `RISKS.md` п. 8. Идёт против отдельного демона на 8199 с
изолированным `XDG_CONFIG_HOME`: рабочий демон на 8065 подхватывает
локально поставленный плагин только при перезапуске, а перезапускать его
нельзя (`orch/HANDOFF.md`, запись в `DECISIONS-NEEDED.md`).
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

PLUGIN = "dev.sadovskii.orch"
BASE = "http://127.0.0.1:8199"
TRIAL = "/projects/kandev-trial"

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _common import main_guard, report  # noqa: E402


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
        return {"_status": exc.code, "_body": exc.read().decode()}
    return json.loads(raw) if raw.strip() else {}


def ui_entry(slot: str, ident: str) -> dict | None:
    for e in call("GET", "/api/plugins/ui-state").get("entries", []):
        if e.get("slot") == slot and e.get("id") == ident:
            return e
    return None


def wait_entry(slot: str, ident: str, pred, timeout: float = 20.0) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        e = ui_entry(slot, ident)
        if e and pred(e):
            return e
        time.sleep(1)
    return ui_entry(slot, ident)


def run() -> int:
    lines: list[str] = []
    ok = True

    plugins = call("GET", "/api/plugins")
    ids = [p["id"] for p in plugins.get("plugins", [])]
    lines.append(f"плагины демона: {ids}, ошибки загрузки: {plugins.get('load_errors')}")
    ok = ok and PLUGIN in ids

    # (а) home-pane нарисовалась из ui.state.set
    home = ui_entry("home-pane", "tasks")
    lines.append(f"а) home-pane: {'есть' if home else 'нет'}")
    ok = ok and bool(home)

    # (б) сессия для слотов на сессию
    s = call(
        "POST",
        "/api/sessions?wait=ready",
        {
            "path": TRIAL,
            "tool": "claude",
            "view": "structured",
            "title": "orch spike4",
            "group": "orch-test",
            "yolo_mode": True,
            "trust_hooks": True,
            "agent_name": "claude",
            "agent_model": "haiku",
            "idempotency_key": "spike4/main",
        },
        timeout=120,
    )
    sid = s.get("id")
    lines.append(f"б) сессия {sid}, статус {s.get('status')}")
    ok = ok and bool(sid)
    if not sid:
        return report("4 (плагин: панель, клик, черновик)", False, lines)

    # (в) клик по кнопке панели доходит с session_id
    stamp = f"ping-{int(time.time())}"
    resp = call(
        "POST",
        f"/api/plugins/{PLUGIN}/action",
        {"method": "orch.ping", "params": {"from": stamp}, "session_id": sid},
    )
    lines.append(f"в) POST action: {resp}")
    got = wait_entry(
        "home-pane",
        "tasks",
        lambda e: sid in json.dumps(e, ensure_ascii=False),
    )
    click_ok = bool(got) and sid in json.dumps(got, ensure_ascii=False)
    lines.append(f"в) воркер получил клик с session_id: {click_ok}")
    ok = ok and click_ok

    # (г) composer.read: снимок черновика доезжает до воркера
    draft = f"черновик-{int(time.time())}"
    call(
        "POST",
        f"/api/plugins/{PLUGIN}/action",
        {
            "method": "orch.move_with_text",
            "params": {"composer": {"text": draft, "selection_start": 0, "selection_end": 0}},
            "session_id": sid,
        },
    )
    got = wait_entry(
        "home-pane", "tasks", lambda e: draft in json.dumps(e, ensure_ascii=False)
    )
    draft_ok = bool(got) and draft in json.dumps(got, ensure_ascii=False)
    lines.append(f"г) черновик доехал до воркера: {draft_ok}")
    ok = ok and draft_ok

    # (д) composer-action и pane на сессию рисуются
    call(
        "POST",
        f"/api/plugins/{PLUGIN}/action",
        {"method": "orch.push_session_slots", "params": {}, "session_id": sid},
    )
    ca = wait_entry("composer-action", "move", lambda e: e.get("session_id") == sid)
    pane = wait_entry("pane", "task", lambda e: e.get("session_id") == sid)
    lines.append(f"д) composer-action на сессии: {bool(ca)}; pane на сессии: {bool(pane)}")
    ok = ok and bool(ca) and bool(pane)

    lines.append(f"сессия спайка оставлена для ручного клика в вебе: {sid}")
    return report("4 (плагин: панель, клик, черновик)", ok, lines)


if __name__ == "__main__":
    main_guard(run)
