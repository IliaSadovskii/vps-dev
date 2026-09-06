"""Команда `orch` для ролей: отказы с объяснением и запись сигналов."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from orch.chain import chains_dir
from orch.cli import main

CHAIN = (chains_dir() / "smoke.yml").read_text(encoding="utf-8")


@pytest.fixture
def task(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "."], cwd=root, check=True)
    path = root / ".orch" / "T1"
    (path / "artifacts").mkdir(parents=True)
    (path / "signals").mkdir(parents=True)
    (path / "chain.yml").write_text(CHAIN, encoding="utf-8")
    (path / "current.json").write_text(
        json.dumps({"task": "T1", "step": "two", "run": 1, "session_id": "s1"}),
        encoding="utf-8",
    )
    monkeypatch.chdir(root)
    return path


def run(argv, capsys):
    code = main(argv)
    out = capsys.readouterr()
    return code, out.out + out.err


def test_whoami_называет_задачу_шаг_и_исходы(task, capsys):
    code, text = run(["whoami"], capsys)
    assert code == 0
    assert "задача: T1" in text and "шаг: two" in text and "ok, back" in text


def test_вне_задачи_отказ(tmp_path, monkeypatch, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    subprocess.run(["git", "init", "-q", "."], cwd=plain, check=True)
    monkeypatch.chdir(plain)
    code, text = run(["whoami"], capsys)
    assert code == 1 and "не рабочая копия задачи" in text


def test_неверный_исход(task, capsys):
    code, text = run(["done", "выдумка"], capsys)
    assert code == 1
    assert "не существует" in text and "ok, back" in text


def test_нет_артефакта(task, capsys):
    code, text = run(["done", "ok"], capsys)
    assert code == 1 and "нет файла" in text and "two.md" in text


def test_не_тот_заголовок(task, capsys):
    (task / "artifacts" / "two.md").write_text("# Не тот\nтекст\n", encoding="utf-8")
    code, text = run(["done", "ok"], capsys)
    assert code == 1 and "## Итог" in text


def test_пустой_артефакт(task, capsys):
    (task / "artifacts" / "two.md").write_text("   \n", encoding="utf-8")
    code, text = run(["done", "ok"], capsys)
    assert code == 1 and "пуст" in text


def test_успешная_сдача_пишет_сигнал(task, capsys):
    (task / "artifacts" / "two.md").write_text("## Итог\nготово\n", encoding="utf-8")
    code, text = run(["done", "ok"], capsys)
    assert code == 0 and "ход сдан с исходом ok" in text
    signal = json.loads((task / "signals" / "two-1.json").read_text(encoding="utf-8"))
    assert signal == {
        "kind": "done", "outcome": "ok", "step": "two", "run": 1, "at": signal["at"]
    }


def test_повторная_сдача_отказ(task, capsys):
    (task / "artifacts" / "two.md").write_text("## Итог\nготово\n", encoding="utf-8")
    run(["done", "ok"], capsys)
    code, text = run(["done", "ok"], capsys)
    assert code == 1 and "ход уже сдан" in text


def test_третий_отказ_велит_остановиться(task, capsys):
    _, first = run(["done", "нет"], capsys)
    assert "Дальше не повторяй" not in first
    _, second = run(["done", "нет"], capsys)
    assert "Дальше не повторяй" in second


def test_отказ_виден_панели_как_сигнал(task, capsys):
    run(["done", "нет"], capsys)
    files = list((task / "signals").glob("two-1-refused-*.json"))
    assert files
    assert "не существует" in json.loads(files[0].read_text(encoding="utf-8"))["text"]


def test_шаг_с_одним_переходом_не_принимает_исход(task, capsys):
    (task / "current.json").write_text(
        json.dumps({"task": "T1", "step": "one", "run": 1}), encoding="utf-8"
    )
    (task / "artifacts" / "one.md").write_text("## Итог\nготово\n", encoding="utf-8")
    code, text = run(["done", "ok"], capsys)
    assert code == 1 and "один переход" in text
    code, text = run(["done"], capsys)
    assert code == 0


def test_ask_и_note_пишут_сигналы(task, capsys):
    assert run(["ask", "Какой цвет?"], capsys)[0] == 0
    assert run(["note", "заметка"], capsys)[0] == 0
    assert list((task / "signals").glob("two-1-ask-*.json"))
    assert list((task / "signals").glob("two-1-note-*.json"))


def test_push_не_пушит_главную_ветку(task, capsys, monkeypatch):
    (task / "current.json").write_text(
        json.dumps({"task": "T1", "step": "two", "run": 1, "branch": "main"}),
        encoding="utf-8",
    )
    code, text = run(["push"], capsys)
    assert code == 1 and "не пушит главную ветку" in text


def test_task_new_кладёт_заявку(task, capsys, tmp_path, monkeypatch):
    import orch.cli as mod

    inbox = tmp_path / "inbox"
    monkeypatch.setattr(mod, "INBOX", inbox)
    code, text = run(
        ["task", "new", "новая задача", "--chain", "smoke", "--backlog"], capsys
    )
    assert code == 0 and "в бэклог" in text
    files = list(inbox.glob("*.json"))
    assert len(files) == 1
    request = json.loads(files[0].read_text(encoding="utf-8"))
    assert request["chain"] == "smoke" and request["backlog"] is True


def _fake_db(tmp_path, monkeypatch, **fields):
    """База только на чтение: одна задача с нужным статусом."""
    import sqlite3

    import orch.cli as mod

    path = tmp_path / "orch.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE task (id TEXT PRIMARY KEY, revision INT, status TEXT, "
        "wait_reason TEXT, step TEXT, branch TEXT, project_path TEXT)"
    )
    conn.execute(
        "INSERT INTO task VALUES (?,?,?,?,?,?,?)",
        (
            fields.get("id", "T1"),
            fields.get("revision", 3),
            fields.get("status", "waiting"),
            fields.get("wait_reason", "gate"),
            fields.get("step", "two"),
            None,
            None,
        ),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(mod, "DB_PATH", path)
    return path


def test_gate_передаёт_решение_владельца_сказанное_словами(
    task, capsys, tmp_path, monkeypatch
):
    """Владелец правит план в чате и там же говорит, куда двигаться."""
    import orch.cli as mod

    inbox = tmp_path / "inbox"
    monkeypatch.setattr(mod, "INBOX", inbox)
    _fake_db(tmp_path, monkeypatch)
    code, text = run(["gate", "back", "one", "--comment", "мало тестов"], capsys)
    assert code == 0 and "решение владельца принято" in text
    request = json.loads(next(inbox.glob("*.json")).read_text(encoding="utf-8"))
    assert request["kind"] == "button" and request["action"] == "back"
    assert request["target"] == "one" and request["comment"] == "мало тестов"
    assert request["revision"] == 3


def test_gate_не_двигает_задачу_которая_не_ждёт(task, capsys, tmp_path, monkeypatch):
    """Иначе роль сдвинет себя сама, решив, что владелец доволен."""
    import orch.cli as mod

    monkeypatch.setattr(mod, "INBOX", tmp_path / "inbox")
    _fake_db(tmp_path, monkeypatch, status="running", wait_reason=None)
    code, text = run(["gate", "accept"], capsys)
    assert code == 1 and "не ждёт владельца" in text


def test_gate_back_без_шага_отказывает(task, capsys, tmp_path, monkeypatch):
    import orch.cli as mod

    monkeypatch.setattr(mod, "INBOX", tmp_path / "inbox")
    _fake_db(tmp_path, monkeypatch)
    code, text = run(["gate", "back"], capsys)
    assert code == 1 and "назовите шаг" in text


def test_chains_показывает_выбор_мастеру(capsys):
    code, text = run(["chains"], capsys)
    assert code == 0
    assert "deep:" in text and "шаги:" in text and "ворота по умолчанию:" in text


def test_task_edit_кладёт_новое_тз(task, capsys, tmp_path, monkeypatch):
    import orch.cli as mod

    inbox = tmp_path / "inbox"
    monkeypatch.setattr(mod, "INBOX", inbox)
    code, text = run(["task", "edit", "T5", "--text", "новое ТЗ"], capsys)
    assert code == 0
    request = json.loads(next(inbox.glob("*.json")).read_text(encoding="utf-8"))
    assert request["kind"] == "edit_text" and request["text"] == "новое ТЗ"
