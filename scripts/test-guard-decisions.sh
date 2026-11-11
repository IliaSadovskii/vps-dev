#!/usr/bin/env bash
# Примеры решений сторожа guard-decisions: кто, каким инструментом, что правит.
# Журналы субагентов и файлы — во временном каталоге, живые не читаются.
set -euo pipefail

guard="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/ansible/roles/style/files/guard-decisions"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
bad=0

session="$tmp/session"
proj="$tmp/proj"
mkdir -p "$session/subagents" "$proj/tests/Arch" "$proj/docs/plans" "$proj/asides" "$proj/app"
plan="$proj/docs/plans/import.md"
aside="$proj/asides/plan-x.md"
arch="$proj/tests/Arch/ArchitectureTest.php"
cat > "$plan" <<'EOF'
# План

## Решения и почему

- Р1. Новый формат — своим контрактом.

```
## Пример заголовка в блоке кода
- строка решения после него
```

## Передача

(пусто)

```
## Решения — пример в передаче, не раздел
- копия
```
EOF
cp "$plan" "$aside"
echo '<?php // домен не знает про HTTP' > "$arch"
ln -s tests/Arch "$proj/archlink"
ln -s docs/plans/import.md "$proj/notes.md"

# Субагент: id, текст задания, глубина запуска (2 — его запустил другой субагент).
agent() {
    local id=$1 task=$2 depth=${3:-1}
    jq -cn --arg t "$task" '{type: "user", message: {role: "user", content: $t}}' > "$session/subagents/agent-$id.jsonl"
    if [ "$depth" = 1 ]; then
        echo '{"agentType":"general-purpose","spawnDepth":1}' > "$session/subagents/agent-$id.meta.json"
    else
        echo "{\"agentType\":\"general-purpose\",\"spawnDepth\":$depth,\"parentAgentId\":\"p\"}" > "$session/subagents/agent-$id.meta.json"
    fi
}
agent plain "Сделай импорт по плану."
agent arch $'Добавь арх-тест к Р1.\nguard-decisions: tests/Arch\nДальше текст.'
agent dec $'guard-decisions: Решения'
agent both $'guard-decisions: tests/Arch, Решения'
agent both2 $'guard-decisions: Решения, tests/Arch'
agent quoted "Разрешение — строкой «guard-decisions: tests/Arch» в задании."
agent indent $'Задание.\n  guard-decisions: tests/Arch'
agent fenced $'Задание.\n```\nguard-decisions: tests/Arch\n```'
agent handoff $'Задание.\n\n## Передача\n\nguard-decisions: tests/Arch'
agent extra $'guard-decisions: tests/Arch и всё остальное'
agent nested $'guard-decisions: tests/Arch'  2

# check <ждём код> <агент или пусто — главная сессия> <tool_name> <tool_input JSON>
check() {
    local want=$1 who=$2 tool=$3 input=$4 got=0
    jq -n --arg who "$who" --arg tool "$tool" --argjson input "$input" --arg tp "$session.jsonl" --arg cwd "$proj" \
        '{session_id: "s", transcript_path: $tp, cwd: $cwd, hook_event_name: "PreToolUse",
          tool_name: $tool, tool_input: $input} + (if $who == "" then {} else {agent_id: $who, agent_type: "general-purpose"} end)' \
        | "$guard" >/dev/null 2>&1 || got=$?
    if [ "$got" != "$want" ]; then
        echo "  ✖ ждали $want, вышло $got: [${who:-главная}] $tool $input"
        bad=1
    fi
}
edit() { jq -cn --arg p "$1" --arg o "$2" --arg n "$3" '{file_path: $p, old_string: $o, new_string: $n}'; }
write() { jq -cn --arg p "$1" --arg c "$2" '{file_path: $p, content: $c}'; }
bash_() { jq -cn --arg c "$1" '{command: $c}'; }

# Главная сессия правит всё
check 0 "" Edit "$(edit "$arch" "домен" "ядро")"
check 0 "" Edit "$(edit "$plan" "своим контрактом" "в ядре")"
check 0 "" Bash "$(bash_ "sed -i s/a/b/ $plan")"
check 0 "" Bash "$(bash_ "rm tests/Arch/ArchitectureTest.php")"

# Арх-тесты: существующий субагенту нельзя никак
check 2 plain Edit "$(edit "$arch" "домен" "ядро")"
check 2 plain Write "$(write "$arch" "<?php")"
check 2 plain MultiEdit "$(jq -cn --arg p "$arch" '{file_path: $p, edits: [{old_string: "домен", new_string: "ядро"}]}')"
check 2 plain NotebookEdit "$(jq -cn --arg p "$proj/tests/Arch/n.ipynb" '{notebook_path: $p, new_source: "x"}')"
check 2 arch Edit "$(edit "$arch" "домен" "ядро")"
check 2 arch Write "$(write "$arch" "<?php")"
check 2 both MultiEdit "$(jq -cn --arg p "$arch" '{file_path: $p, edits: [{old_string: "домен", new_string: "ядро"}]}')"
# Новый арх-тест — только Write и только с разрешением
check 2 plain Write "$(write "$proj/tests/Arch/NewTest.php" "<?php")"
check 0 arch Write "$(write "$proj/tests/Arch/NewTest.php" "<?php")"
check 0 arch Write "$(write "tests/Arch/Sub/NewTest.php" "<?php")"
check 2 arch Edit "$(edit "$proj/tests/Arch/NewTest.php" "" "<?php")"
# Симлинк на tests/Arch — тот же tests/Arch
check 2 plain Edit "$(edit "$proj/archlink/ArchitectureTest.php" "домен" "ядро")"
check 2 plain Write "$(write "$proj/archlink/NewTest.php" "<?php")"
check 2 plain Bash "$(bash_ "rm archlink/ArchitectureTest.php")"

# Оболочка не пишет в tests/Arch, даже с разрешением
check 2 plain Bash "$(bash_ "sed -i 's/HTTP/X/' tests/Arch/ArchitectureTest.php")"
check 2 plain Bash "$(bash_ "sed --in-place 's/HTTP/X/' tests/Arch/ArchitectureTest.php")"
check 2 plain Bash "$(bash_ "perl -pi -e 's/HTTP/X/' tests/Arch/ArchitectureTest.php")"
check 2 plain Bash "$(bash_ "echo x > tests/Arch/ArchitectureTest.php")"
check 2 plain Bash "$(bash_ "echo x >| tests/Arch/ArchitectureTest.php")"
check 2 plain Bash "$(bash_ "echo x 2>&1 >>tests/Arch/ArchitectureTest.php")"
check 2 plain Bash "$(bash_ "rm tests/Arch/ArchitectureTest.php")"
check 2 plain Bash "$(bash_ "git checkout main -- tests/Arch")"
check 2 plain Bash "$(bash_ "git -C tests restore Arch/ArchitectureTest.php")"
check 2 plain Bash "$(bash_ "cat x | tee -a tests/Arch/A.php")"
check 2 plain Bash "$(bash_ "cp /tmp/A.php tests/Arch/")"
check 2 plain Bash "$(bash_ "mv tests/Arch/ArchitectureTest.php /tmp/")"
check 2 plain Bash "$(bash_ "install -m 644 /tmp/A.php tests/Arch/A.php")"
check 2 plain Bash "$(bash_ "ln -sf /tmp/A.php tests/Arch/A.php")"
check 2 plain Bash "$(bash_ "rsync -a /tmp/arch/ tests/Arch/")"
check 2 plain Bash "$(bash_ "dd if=/tmp/A.php of=tests/Arch/A.php")"
check 2 plain Bash "$(bash_ "truncate -s 0 tests/Arch/ArchitectureTest.php")"
check 2 plain Bash "$(bash_ "cd tests && rm Arch/ArchitectureTest.php")"
check 2 plain Bash "$(bash_ $'ls\nrm -f tests/Arch/ArchitectureTest.php')"
check 2 arch Bash "$(bash_ "echo '<?php' > tests/Arch/NewTest.php")"
check 2 both Bash "$(bash_ "rm tests/Arch/ArchitectureTest.php")"

# Прогон и чтение — можно; путь не аргумент файловой операции — не запись
check 0 plain Bash "$(bash_ "cat tests/Arch/ArchitectureTest.php 2>/dev/null")"
check 0 plain Bash "$(bash_ "docker compose exec app ./vendor/bin/pest tests/Arch > /tmp/arch.log 2>&1")"
check 0 plain Bash "$(bash_ "docker compose run --rm app ./vendor/bin/pest tests/Arch")"
check 0 plain Bash "$(bash_ "rm -f /tmp/x; ./vendor/bin/pest tests/Arch")"
check 0 plain Bash "$(bash_ "git checkout -b x && ./vendor/bin/pest tests/Arch")"
check 0 plain Bash "$(bash_ "grep -rn HTTP tests/Arch >&2")"
check 0 plain Bash "$(bash_ "cp tests/Arch/ArchitectureTest.php /tmp/")"
check 0 plain Bash "$(bash_ "echo 'x > tests/Arch/A.php' && echo \"sed -i y tests/Arch/A.php\"")"
check 0 plain Bash "$(bash_ "git commit -m \"Р1 -> docs/plans/a.md, правка tests/Arch\"")"
check 0 plain Bash "$(bash_ "cat > /tmp/msg <<'EOF'
rm tests/Arch/ArchitectureTest.php > docs/plans/import.md
EOF
git commit -F /tmp/msg")"
check 0 plain Edit "$(edit "$proj/app/X.php" "a" "b")"

# Раздел «Решения» плана
check 2 plain Edit "$(edit "$plan" "своим контрактом" "в ядре")"
check 2 plain Edit "$(edit "$aside" "## Решения и почему" "## Прочее")"
check 2 plain Edit "$(edit "$plan" "## Передача" $'## Решения 2\n\n- Р2. Новое.\n\n## Передача')"
check 2 plain Write "$(write "$plan" $'# План\n\n## Передача\n\nсделано')"
check 2 plain Write "$(write "$proj/docs/plans/new.md" $'# План\n\n## Решения\n\n- Р1.')"
# Заголовок в блоке кода раздел не кончает и не начинает
check 2 plain Edit "$(edit "$plan" "- строка решения после него" "- другое")"
check 0 plain Edit "$(edit "$plan" "- копия" "- другая копия")"
# Симлинк на план — тот же план
check 2 plain Edit "$(edit "$proj/notes.md" "своим контрактом" "в ядре")"
# Оболочка в файл плана не пишет: ни перенаправлением, ни файловой операцией
check 2 plain Bash "$(bash_ "sed -i 's/контрактом/ядром/' docs/plans/import.md")"
check 2 plain Bash "$(bash_ "cat >> asides/plan-x.md <<EOF
x
EOF")"
check 2 plain Bash "$(bash_ "cp /tmp/old.md docs/plans/import.md")"
check 2 plain Bash "$(bash_ "mv docs/plans/import.md /tmp/")"
check 2 plain Bash "$(bash_ "git checkout main -- docs/plans/import.md")"
check 2 plain Bash "$(bash_ "rm asides/plan-x.md")"
check 2 plain Bash "$(bash_ "echo x >> notes.md")"
check 0 dec Bash "$(bash_ "sed -i 's/контрактом/ядром/' docs/plans/import.md")"
# Остальной план — можно
check 0 plain Edit "$(edit "$plan" "(пусто)" "сделано: Р1 — app/X.php:10")"
check 0 plain Write "$(write "$plan" "$(sed 's/(пусто)/сделано/' "$plan")")"
check 0 plain Write "$(write "$proj/docs/plans/new.md" $'# План\n\n## Передача\n\nx')"
check 0 plain Edit "$(edit "$proj/docs/notes.md" "a" "b")"
check 0 plain Bash "$(bash_ "cat docs/plans/import.md > /tmp/plan-copy.txt")"
check 0 plain Bash "$(bash_ "git add asides/plan-x.md && git commit -m x")"

# Разрешение в задании: своя строка без отступа, вне блока кода, до «Передачи»
check 2 arch Edit "$(edit "$plan" "своим контрактом" "в ядре")"
check 0 dec Edit "$(edit "$plan" "своим контрактом" "в ядре")"
check 0 both Edit "$(edit "$plan" "своим контрактом" "в ядре")"
check 0 both2 Write "$(write "$proj/tests/Arch/NewTest.php" "<?php")"
check 0 both2 Edit "$(edit "$plan" "своим контрактом" "в ядре")"
for who in quoted indent fenced handoff extra nested ghost; do
    check 2 "$who" Write "$(write "$proj/tests/Arch/NewTest.php" "<?php")"
done

# Кривой вход — тихо пропускаем
check 0 plain Edit '{}'
printf 'не json "agent_id"' | "$guard" >/dev/null 2>&1 || { echo "  ✖ кривой вход не пропущен"; bad=1; }

[ "$bad" -eq 0 ] || exit 1
echo "  ✔ сторож решений: примеры сходятся"
