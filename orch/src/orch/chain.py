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

DONE = "done"
DEFAULT_MAX_RUNS = 3
VALID_CONTEXT = ("fresh", "continue")
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
        """Ждать ли владельца после этого исхода."""
        if isinstance(self.human_after, bool):
            return self.human_after
        return outcome in self.human_after


@dataclass
class Chain:
    name: str
    includes: list[str] = field(default_factory=list)
    presets: dict[str, dict] = field(default_factory=dict)
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
    raw = yaml.safe_load(text)
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
        presets=dict(raw.get("presets") or {}),
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
            raise ChainError(f"шаг {s.id}: human.after — true, false или список исходов")
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
    """
    out: list[dict] = []
    for path in sorted(chains_dir().glob("*.yml")):
        head = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                head.append(line.lstrip("# ").rstrip())
            elif line.strip():
                break
        try:
            chain = load(path)
        except ChainError as exc:
            out.append({"name": path.stem, "error": str(exc)})
            continue
        out.append(
            {
                "name": chain.name,
                "description": " ".join(head).strip(),
                "steps": [s.id for s in chain.steps],
                "presets": sorted(chain.presets),
                "gates": [s.id for s in chain.steps if s.human_after],
            }
        )
    return out


def chains_dir() -> Path:
    """Каталог `orch/chains/` рядом с исходниками пакета."""
    return _repo_dir() / "chains"


def prompts_dir() -> Path:
    return _repo_dir() / "prompts"


def _repo_dir() -> Path:
    """Корень `orch/` — на два уровня выше `src/orch/`."""
    return Path(__file__).resolve().parents[2]
