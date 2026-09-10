"""Цепочка: чтение `chains/<name>.yml`, умолчания, линтер.

Структура цепочки замораживается при создании задачи (`task.chain_yaml` и
зеркало `.orch/<task>/chain.yml`); тексты промптов читаются при каждом старте
шага. Новые поля читаются с умолчаниями — миграций замороженных копий нет
(`PLAN.md` §4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .db import STATE_DIR

DONE = "done"
DEFAULT_MAX_RUNS = 3
VALID_CONTEXT = ("fresh", "continue", "own")
VALID_MODE = ("full",)
VALID_AGENTS = ("claude", "codex", "opencode")
# Заголовок, с которого обязан начинаться артефакт (`PLAN.md` §5).
ARTIFACT_HEADINGS = ("## Итог", "## Для владельца")


class ChainError(Exception):
    """Цепочка не читается или не проходит линтер."""


@dataclass
class Step:
    id: str
    agent: str
    model: str
    effort: str | None = None
    mode: str = "full"
    prompt_file: str = ""
    instructions: str = ""
    reads: list[str] = field(default_factory=list)
    # Общие файлы только для этого шага: правило, которое нужно двум ролям из
    # восьми, приклеенное ко всем, — сорок строк не по адресу (наблюдение
    # прогона T16, `PROMPT-NOTES.md`).
    includes: list[str] = field(default_factory=list)
    context: str = "fresh"
    artifact: list[str] = field(default_factory=list)
    next: dict[str, str] = field(default_factory=dict)
    # Ворота: `false` — никогда, `true` — после любого хода, список — после
    # этих исходов. Смысл списка — исход, который ходом не кончает: у Плана
    # `review` уезжает на ревью, и владельцу там нечего принимать.
    human_after: bool | list[str] = False
    human_ask: bool = True
    human_moves: list[str] = field(default_factory=list)
    max_runs: int = DEFAULT_MAX_RUNS

    @property
    def outcomes(self) -> list[str]:
        """Исходы, которыми роль может закончить ход."""
        return list(self.next.keys())

    @property
    def single_next(self) -> str | None:
        """Цель, если у шага один безымянный переход."""
        return self.next.get("*")

    def target(self, outcome: str | None) -> str | None:
        if self.single_next is not None:
            return self.single_next
        if outcome is None:
            return None
        return self.next.get(outcome)

    def gates_on(self, outcome: str | None) -> bool:
        """Ждать ли владельца после этого хода."""
        return gates_on(self.human_after, outcome)


@dataclass
class Chain:
    name: str
    includes: list[str] = field(default_factory=list)
    presets: dict[str, dict] = field(default_factory=dict)
    # Зачем этот пресет: одна строка на каждый. Мастер выбирает по смыслу, а
    # не по созвучию имени (`hands-off` — не автономия, прогон T24).
    preset_notes: dict[str, str] = field(default_factory=dict)
    steps: list[Step] = field(default_factory=list)
    source: str = ""

    def step(self, step_id: str) -> Step:
        for s in self.steps:
            if s.id == step_id:
                return s
        raise ChainError(f"в цепочке {self.name} нет шага {step_id!r}")

    def has(self, step_id: str) -> bool:
        return any(s.id == step_id for s in self.steps)

    @property
    def first(self) -> Step:
        if not self.steps:
            raise ChainError(f"в цепочке {self.name} нет шагов")
        return self.steps[0]

    def default_sheet(self) -> dict[str, dict]:
        """Лист автономии по умолчанию: как записано в шагах."""
        return {
            s.id: {"after": s.human_after, "ask": s.human_ask} for s in self.steps
        }

    def sheet_with_preset(self, preset: str | None) -> dict[str, dict]:
        sheet = self.default_sheet()
        if not preset:
            return sheet
        if preset not in self.presets:
            raise ChainError(
                f"в цепочке {self.name} нет пресета {preset!r}; "
                f"есть: {', '.join(sorted(self.presets)) or '—'}"
            )
        return apply_preset(sheet, self.presets[preset])


def _preset_body(value) -> dict:
    """Тело пресета: плоский словарь ручек или `{when: …, set: {…}}`."""
    if isinstance(value, dict) and "set" in value:
        return dict(value.get("set") or {})
    return dict(value or {})


def apply_preset(sheet: dict[str, dict], preset: dict) -> dict[str, dict]:
    """Наложить пресет на лист. Ключ `шаг.after`, `шаг.ask`, `*` — все шаги."""
    out = {k: dict(v) for k, v in sheet.items()}
    for key, value in preset.items():
        step_id, _, knob = key.partition(".")
        if knob not in ("after", "ask"):
            raise ChainError(f"ключ пресета {key!r}: ожидались .after или .ask")
        targets = list(out) if step_id == "*" else [step_id]
        for target in targets:
            if target not in out:
                raise ChainError(f"ключ пресета {key!r}: нет шага {target!r}")
            out[target][knob] = value
    return out


def parse(text: str, source: str = "") -> Chain:
    # Битый YAML — такая же непригодная цепочка, как цепочка без шагов, и
    # звать её надо тем же именем. Голый `yaml.YAMLError` пролетал мимо всех
    # `except ChainError`: задача с испорченной замороженной цепочкой
    # застревала с `engine_error` вместо внятного «цепочка не читается», а
    # кнопки владельца падали с трассировкой (2026-09-10).
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ChainError(f"{source or 'цепочка'}: не разобрал YAML: {exc}") from None
    if not isinstance(raw, dict):
        raise ChainError(f"{source or 'цепочка'}: ожидался словарь верхнего уровня")
    name = raw.get("name")
    if not name:
        raise ChainError(f"{source or 'цепочка'}: нет обязательного поля name")
    steps_raw = raw.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise ChainError(f"цепочка {name}: steps должен быть непустым списком")
    steps = [_step(item, name) for item in steps_raw]
    chain = Chain(
        name=str(name),
        includes=list(raw.get("includes") or []),
        presets={k: _preset_body(v) for k, v in (raw.get("presets") or {}).items()},
        preset_notes={
            k: str(v.get("when") or "")
            for k, v in (raw.get("presets") or {}).items()
            if isinstance(v, dict) and "set" in v
        },
        steps=steps,
        source=text,
    )
    lint(chain)
    return chain


def _step(raw: dict, chain_name: str) -> Step:
    if not isinstance(raw, dict):
        raise ChainError(f"цепочка {chain_name}: шаг должен быть словарём")
    step_id = raw.get("id")
    if not step_id:
        raise ChainError(f"цепочка {chain_name}: у шага нет id")
    run = raw.get("run") or {}
    if not run.get("agent") or not run.get("model"):
        raise ChainError(f"шаг {step_id}: обязательны run.agent и run.model")
    prompt = raw.get("prompt") or {}
    human = raw.get("human") or {}
    limits = raw.get("limits") or {}

    artifact = raw.get("artifact") or []
    if isinstance(artifact, str):
        artifact = [artifact]

    nxt = raw.get("next")
    if nxt is None:
        raise ChainError(f"шаг {step_id}: обязательно поле next")
    if isinstance(nxt, str):
        next_map = {"*": nxt}
    elif isinstance(nxt, dict):
        next_map = {str(k): str(v) for k, v in nxt.items()}
        if not next_map:
            raise ChainError(f"шаг {step_id}: next пуст")
    else:
        raise ChainError(f"шаг {step_id}: next — строка или словарь исходов")

    return Step(
        id=str(step_id),
        agent=str(run["agent"]),
        model=str(run["model"]),
        effort=run.get("effort"),
        mode=str(run.get("mode", "full")),
        prompt_file=str(prompt.get("file") or f"role-{step_id}"),
        instructions=str(prompt.get("instructions") or ""),
        reads=list(prompt.get("reads") or []),
        includes=list(raw.get("includes") or []),
        context=str(raw.get("context", "fresh")),
        artifact=list(artifact),
        next=next_map,
        human_after=human.get("after", False),
        human_ask=bool(human.get("ask", True)),
        human_moves=list(human.get("moves") or []),
        max_runs=int(limits.get("max_runs", DEFAULT_MAX_RUNS)),
    )


def lint(chain: Chain) -> None:
    """Проверки `PLAN.md` §4. Ошибка — цепочка не грузится, задача не создаётся."""
    ids = [s.id for s in chain.steps]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ChainError(f"цепочка {chain.name}: шаги с одинаковым id: {sorted(dupes)}")
    if DONE in ids:
        raise ChainError(f"цепочка {chain.name}: {DONE!r} — конец цепочки, не шаг")

    known = set(ids) | {DONE}
    for s in chain.steps:
        if s.agent not in VALID_AGENTS:
            raise ChainError(f"шаг {s.id}: агент {s.agent!r}, ожидался один из {VALID_AGENTS}")
        if s.mode not in VALID_MODE:
            raise ChainError(
                f"шаг {s.id}: mode {s.mode!r}. В первой версии только full: "
                "в режиме только чтения роль не может ни писать файл, ни сдать ход "
                "(research/RISKS.md п. 12)"
            )
        if s.context not in VALID_CONTEXT:
            raise ChainError(f"шаг {s.id}: context {s.context!r}, ожидался {VALID_CONTEXT}")
        if s.max_runs < 1:
            raise ChainError(f"шаг {s.id}: max_runs {s.max_runs}, должно быть ≥ 1")
        for outcome, target in s.next.items():
            if target not in known:
                raise ChainError(f"шаг {s.id}: next {outcome!r} → нет шага {target!r}")
        for target in s.human_moves:
            if target not in known:
                raise ChainError(f"шаг {s.id}: human.moves → нет шага {target!r}")
        if s.human_moves and s.human_after is False:
            raise ChainError(
                f"шаг {s.id}: human.moves без human.after — кнопок возврата не будет, "
                "потому что задача на этом шаге не остановится"
            )
        if not isinstance(s.human_after, (bool, list)):
            raise ChainError(f"шаг {s.id}: human.after — false, true или список исходов")
        if isinstance(s.human_after, list):
            unknown = set(s.human_after) - set(s.next)
            if unknown:
                raise ChainError(
                    f"шаг {s.id}: human.after называет исходы {sorted(unknown)}, "
                    f"которых нет в next"
                )

    unreachable = [s.id for s in chain.steps if not _reaches_done(chain, s.id)]
    if unreachable:
        raise ChainError(
            f"цепочка {chain.name}: из шагов {unreachable} не добраться до конца"
        )

    for preset, body in chain.presets.items():
        try:
            apply_preset(chain.default_sheet(), body)
        except ChainError as exc:
            raise ChainError(f"пресет {preset!r}: {exc}") from None


def _reaches_done(chain: Chain, start: str) -> bool:
    seen: set[str] = set()
    stack = [start]
    while stack:
        cur = stack.pop()
        if cur == DONE:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(chain.step(cur).next.values())
    return False


def load(path: str | Path) -> Chain:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ChainError(f"не читается {path}: {exc}") from None
    try:
        return parse(text, source=str(path))
    except yaml.YAMLError as exc:
        raise ChainError(f"{path}: не разобрал YAML: {exc}") from None


def catalog() -> list[dict]:
    """Какие цепочки есть: имя, о чём она, шаги, пресеты, ворота по умолчанию.

    Нужен мастеру: он показывает владельцу выбор вариантами, а не заставляет
    помнить имена файлов. Описание — верхний блок комментариев файла, там оно
    и так написано для человека; отдельного поля в схеме заводить не стали.
    Битая цепочка попадает в список с пометкой, а не роняет весь выбор.
    Правленая владельцем цепочка показывается вместо заводской и помечена
    `custom`: выбор один и тот же, отличается только содержимое.
    """
    out: list[dict] = []
    for name in names():
        path = path_of(name)
        head = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                head.append(line.lstrip("# ").rstrip())
            elif line.strip():
                break
        try:
            chain = load(path)
        except ChainError as exc:
            out.append({"name": name, "error": str(exc), "custom": is_custom(name)})
            continue
        out.append(
            {
                "name": chain.name,
                "custom": is_custom(name),
                "description": " ".join(head).strip(),
                "steps": [s.id for s in chain.steps],
                "edges": [
                    {
                        "step": s.id,
                        "next": dict(s.next),
                        "after": s.human_after,
                        "ask": s.human_ask,
                        "max_runs": s.max_runs,
                        "context": s.context,
                    }
                    for s in chain.steps
                ],
                "presets": sorted(chain.presets),
                "preset_notes": dict(chain.preset_notes),
                "gates": [s.id for s in chain.steps if s.human_after],
            }
        )
    return out


def missing_files(chain: Chain) -> list[str]:
    """Чего цепочке не хватает на диске: файлы ролей и общих правил.

    В линтер это не входит нарочно: он гоняется на замороженных копиях и на
    синтетических цепочках тестов, где ролей нет. А заводским файлам и
    `orch doctor` проверка нужна: роль без файла получает вместо текста
    строку «файл не найден» (`promptbuild._role`), ход идёт впустую, и по
    журналу это не видно.
    """
    prompts = prompts_dir()
    problems: list[str] = []
    for name in chain.includes:
        if not (prompts / f"{name}.md").exists():
            problems.append(f"нет общего файла {name}.md")
    for step in chain.steps:
        if not (prompts / f"{step.prompt_file}.md").exists():
            problems.append(f"шаг {step.id}: нет файла роли {step.prompt_file}.md")
        for name in step.includes:
            if not (prompts / f"{name}.md").exists():
                problems.append(f"шаг {step.id}: нет общего файла {name}.md")
    return problems


def gates_on(after: bool | list[str], outcome: str | None) -> bool:
    """Ждать ли владельца: одно правило для цепочки и для листа автономии."""
    if isinstance(after, bool):
        return after
    if isinstance(after, list):
        return outcome in after
    return False


def chains_dir() -> Path:
    """Каталог `orch/chains/` рядом с исходниками пакета — заводские цепочки."""
    return _repo_dir() / "chains"


def user_chains_dir() -> Path:
    """Каталог правленых владельцем цепочек — рядом с базой, вне репозитория.

    Правки цепочек — настройка машины, а не работа над кодом: в рабочей копии
    они засоряли бы `git status` и уезжали бы в чужие коммиты. Заводской файл
    при этом не трогается никогда, «Сбросить до заводских» = удалить файл
    отсюда (`UX-PLAN.md`, страница «Цепочки»).
    """
    return STATE_DIR / "chains"


def path_of(name: str) -> Path:
    """Файл цепочки, по которому она сейчас едет: правленый, иначе заводской."""
    user = user_chains_dir() / f"{name}.yml"
    return user if user.exists() else chains_dir() / f"{name}.yml"


def is_custom(name: str) -> bool:
    return (user_chains_dir() / f"{name}.yml").exists()


def names() -> list[str]:
    """Имена всех цепочек: заводские плюс те, что владелец завёл сам."""
    found = {p.stem for p in chains_dir().glob("*.yml")}
    if user_chains_dir().exists():
        found |= {p.stem for p in user_chains_dir().glob("*.yml")}
    return sorted(found)


def load_by_name(name: str) -> Chain:
    return load(path_of(name))


def prompts_dir() -> Path:
    return _repo_dir() / "prompts"


def _repo_dir() -> Path:
    """Корень `orch/` — на два уровня выше `src/orch/`."""
    return Path(__file__).resolve().parents[2]
