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


def test_note_пишет_сигнал_а_ask_нет(task, capsys):
    """`orch ask` снят: движок сигнал вопроса не читал, а команда обещала,
    что задача встанет. Вопрос владельцу — только интерактивный."""
    assert run(["note", "заметка"], capsys)[0] == 0
    assert list((task / "signals").glob("two-1-note-*.json"))
    with pytest.raises(SystemExit):
        run(["ask", "Какой цвет?"], capsys)


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


def test_task_new_по_умолчанию_в_бэклог(task, capsys, tmp_path, monkeypatch):
    """В работу задача уходит рукой владельца, а не потому, что её завели."""
    import orch.cli as mod

    inbox = tmp_path / "inbox"
    monkeypatch.setattr(mod, "INBOX", inbox)
    code, text = run(["task", "new", "новая задача", "--chain", "smoke"], capsys)
    assert code == 0 and "в бэклог" in text
    request = json.loads(list(inbox.glob("*.json"))[0].read_text(encoding="utf-8"))
    assert request["backlog"] is True


def test_task_new_start_ставит_в_очередь(task, capsys, tmp_path, monkeypatch):
    import orch.cli as mod

    inbox = tmp_path / "inbox"
    monkeypatch.setattr(mod, "INBOX", inbox)
    code, text = run(["task", "new", "новая задача", "--chain", "smoke", "--start"], capsys)
    assert code == 0 and "в очередь" in text
    request = json.loads(list(inbox.glob("*.json"))[0].read_text(encoding="utf-8"))
    assert request["backlog"] is False


def test_task_start_кладёт_заявку_на_ту_же_задачу(task, capsys, tmp_path, monkeypatch):
    """Мастер отпускает заявку, а не заводит вторую: номер в заявке — её."""
    import orch.cli as mod

    inbox = tmp_path / "inbox"
    monkeypatch.setattr(mod, "INBOX", inbox)
    code, text = run(["task", "start", "T29", "--chain", "deep", "--preset", "auto"], capsys)
    assert code == 0 and "T29" in text
    request = json.loads(list(inbox.glob("*.json"))[0].read_text(encoding="utf-8"))
    assert request["kind"] == "start" and request["task"] == "T29"
    assert request["chain"] == "deep" and request["preset"] == "auto"
    # Неназванное приходит пустым: в базе останется то, что записано в заявке.
    assert request["text"] is None and request["branch"] is None
    assert request["stand"] is None and request["notify"] is None


def test_ворота_из_среды_агента_отказывают(task, capsys, tmp_path, monkeypatch):
    """Роль не решает за владельца: в сессии AoE `gate` и кнопки отказывают.

    Находка Наладчика на T26 (2026-09-09): роль приняла пересказ требования
    за согласие и сама вызвала `orch gate back`.
    """
    import orch.cli as mod

    monkeypatch.setattr(mod, "INBOX", tmp_path / "inbox")
    _fake_db(tmp_path, monkeypatch)
    monkeypatch.setenv("AOE_ARTIFACT_DIR", "/tmp/агент")

    code, text = run(["gate", "accept"], capsys)
    assert code == 1 and "решение владельца, не роли" in text
    code, text = run(["task", "move", "T1", "back", "--target", "one"], capsys)
    assert code == 1 and "решение владельца, не роли" in text

    # Запрет только на кнопки владельца: остальные команды роли работают.
    monkeypatch.setattr(mod, "INBOX", tmp_path / "inbox")
    code, text = run(["task", "new", "мелкая задача", "--chain", "smoke"], capsys)
    assert code == 0 and "в бэклог" in text


def _fake_db(tmp_path, monkeypatch, **fields):
    """База только на чтение: одна задача с нужным статусом."""
    import sqlite3

    import orch.cli as mod

    path = tmp_path / "orch.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE task (id TEXT PRIMARY KEY, revision INT, status TEXT, "
        "wait_reason TEXT, step TEXT, branch TEXT, project_path TEXT, "
        "worktree_path TEXT)"
    )
    conn.execute(
        "INSERT INTO task VALUES (?,?,?,?,?,?,?,?)",
        (
            fields.get("id", "T1"),
            fields.get("revision", 3),
            fields.get("status", "waiting"),
            fields.get("wait_reason", "gate"),
            fields.get("step", "two"),
            None,
            None,
            fields.get("worktree_path"),
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


def test_gate_back_clean_доезжает_до_движка(task, capsys, tmp_path, monkeypatch):
    """`--clean` — это другая кнопка, а не пометка в комментарии."""
    import orch.cli as mod

    inbox = tmp_path / "inbox"
    monkeypatch.setattr(mod, "INBOX", inbox)
    _fake_db(tmp_path, monkeypatch)
    code, _ = run(["gate", "back", "one", "--clean"], capsys)
    assert code == 0
    request = json.loads(next(inbox.glob("*.json")).read_text(encoding="utf-8"))
    assert request["action"] == "back_clean" and request["target"] == "one"


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


def test_заявка_из_корня_проекта_не_подписана_чужой_задачей(
    task, capsys, tmp_path, monkeypatch
):
    """`.orch/<T>` могла остаться от прошлой задачи: подпись была бы ложью."""
    import orch.cli as mod

    inbox = tmp_path / "inbox"
    monkeypatch.setattr(mod, "INBOX", inbox)
    _fake_db(tmp_path, monkeypatch, id="T1", status="done")
    code, _ = run(["task", "new", "новая", "--chain", "smoke"], capsys)
    assert code == 0
    request = json.loads(next(inbox.glob("*.json")).read_text(encoding="utf-8"))
    assert request["author"] is None


def test_gc_показывает_сирот_и_не_трогает_без_согласия(tmp_path, capsys, monkeypatch):
    """Копия без живой задачи — сирота; удалять её молча нельзя."""
    import sqlite3
    import subprocess

    import orch.cli as mod

    project = tmp_path / "repo"
    project.mkdir()
    subprocess.run(["git", "init", "-q", "."], cwd=project, check=True)
    (project / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=project, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
        cwd=project, check=True,
    )
    сирота = tmp_path / "repo-orch" / "t1-x"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(сирота), "-b", "t1-x"],
        cwd=project, check=True, capture_output=True,
    )

    db = tmp_path / "orch.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE task (id TEXT, project_path TEXT, worktree_path TEXT, archived_at TEXT)"
    )
    conn.execute("INSERT INTO task VALUES ('T1', ?, NULL, NULL)", (str(project),))
    conn.commit()
    conn.close()
    monkeypatch.setattr(mod, "DB_PATH", db)

    code, text = run(["gc"], capsys)
    assert code == 0 and "t1-x" in text and "это показ" in text
    assert сирота.exists(), "показ не должен ничего удалять"

    code, text = run(["gc", "--yes"], capsys)
    assert code == 0 and "убрана" in text
    assert not сирота.exists()


def _current(task: Path, **kw):
    data = json.loads((task / "current.json").read_text(encoding="utf-8"))
    data.update(kw)
    (task / "current.json").write_text(json.dumps(data), encoding="utf-8")


def test_тз_со_ссылкой_в_папку_чужой_задачи_отвергается(tmp_path, monkeypatch):
    """Папка задачи не в git: ссылка на неё протухает молча, и роль ищет
    файл, которого нет (прогон T24)."""
    import pytest

    from orch.cli import Refused, check_text

    check_text("обычный текст без ссылок")
    check_text("свои файлы можно: .orch/T7/artifacts/plan.md", "T7")

    with pytest.raises(Refused) as exc:
        check_text("подробности — .orch/T19/artifacts/remarks.md", "T23")
    assert ".orch/T19/" in str(exc.value)
