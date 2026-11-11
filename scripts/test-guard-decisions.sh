#!/usr/bin/env bash
# Примеры решений сторожа guard-decisions: кто, каким инструментом, что правит.
# Журналы субагентов и файлы — во временном каталоге, живые не читаются.
set -euo pipefail

guard="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/ansible/roles/style/files/guard-decisions"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
bad=0

session="$tmp/session"
mkdir -p "$session/subagents" "$tmp/proj/tests/Arch" "$tmp/proj/docs/plans" "$tmp/proj/asides"
plan="$tmp/proj/docs/plans/import.md"
aside="$tmp/proj/asides/plan-x.md"
arch="$tmp/proj/tests/Arch/ArchitectureTest.php"
cat > "$plan" <<'EOF'
# План

## Решения и почему

- Р1. Новый формат — своим контрактом.

## Передача

(пусто)
EOF
cp "$plan" "$aside"
echo '<?php // домен не знает про HTTP' > "$arch"

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
agent arch $'Почини арх-тест.\nguard-decisions: tests/Arch\nДальше текст.'
agent both $'guard-decisions: tests/Arch, Решения'
agent quoted "Разрешение — строкой «guard-decisions: tests/Arch» в задании."
agent nested $'guard-decisions: tests/Arch'  2

# check <ждём код> <агент или пусто — главная сессия> <tool_name> <tool_input JSON>
check() {
    local want=$1 who=$2 tool=$3 input=$4 got=0
    jq -n --arg who "$who" --arg tool "$tool" --argjson input "$input" --arg tp "$session.jsonl" \
        '{session_id: "s", transcript_path: $tp, cwd: "/", hook_event_name: "PreToolUse",
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

# Арх-тесты: субагенту нельзя
check 2 plain Edit "$(edit "$arch" "домен" "ядро")"
check 2 plain Write "$(write "$tmp/proj/tests/Arch/NewTest.php" "<?php")"
check 2 plain MultiEdit "$(jq -cn --arg p "$arch" '{file_path: $p, edits: [{old_string: "домен", new_string: "ядро"}]}')"
check 2 plain Bash "$(bash_ "sed -i 's/HTTP/X/' tests/Arch/ArchitectureTest.php")"
check 2 plain Bash "$(bash_ "echo x > tests/Arch/ArchitectureTest.php")"
check 2 plain Bash "$(bash_ "rm tests/Arch/ArchitectureTest.php")"
check 2 plain Bash "$(bash_ "git checkout main -- tests/Arch")"
check 2 plain Bash "$(bash_ "cat x | tee -a tests/Arch/A.php")"
# Читать и гонять — можно
check 0 plain Bash "$(bash_ "cat tests/Arch/ArchitectureTest.php 2>/dev/null")"
check 0 plain Bash "$(bash_ "docker compose exec app ./vendor/bin/pest tests/Arch > /tmp/arch.log 2>&1")"
check 0 plain Bash "$(bash_ "grep -rn HTTP tests/Arch >&2")"
check 0 plain Edit "$(edit "$tmp/proj/app/Domain/X.php" "a" "b")"

# Раздел «Решения» плана
check 2 plain Edit "$(edit "$plan" "своим контрактом" "в ядре")"
check 2 plain Edit "$(edit "$aside" "## Решения и почему" "## Прочее")"
check 2 plain Edit "$(edit "$plan" "## Передача" $'## Решения 2\n\n- Р2. Новое.\n\n## Передача')"
check 2 plain Write "$(write "$plan" $'# План\n\n## Передача\n\nсделано')"
check 2 plain Write "$(write "$tmp/proj/docs/plans/new.md" $'# План\n\n## Решения\n\n- Р1.')"
check 2 plain Bash "$(bash_ "sed -i 's/контрактом/ядром/' docs/plans/import.md")"
check 2 plain Bash "$(bash_ "cat >> asides/plan-x.md <<EOF
x
EOF")"
# Остальной план — можно
check 0 plain Edit "$(edit "$plan" "(пусто)" "сделано: Р1 — app/X.php:10")"
check 0 plain Write "$(write "$plan" "$(sed 's/(пусто)/сделано/' "$plan")")"
check 0 plain Write "$(write "$tmp/proj/docs/plans/new.md" $'# План\n\n## Передача\n\nx')"
check 0 plain Edit "$(edit "$tmp/proj/docs/notes.md" "a" "b")"
check 0 plain Bash "$(bash_ "cat docs/plans/import.md > /tmp/plan-copy.txt")"
check 0 plain Bash "$(bash_ "git add asides/plan-x.md && git commit -m x")"

# Разрешение в задании
check 0 arch Edit "$(edit "$arch" "домен" "ядро")"
check 2 arch Edit "$(edit "$plan" "своим контрактом" "в ядре")"
check 0 both Edit "$(edit "$plan" "своим контрактом" "в ядре")"
check 0 both Bash "$(bash_ "rm tests/Arch/ArchitectureTest.php")"
# Строка, процитированная внутри текста, — не разрешение
check 2 quoted Edit "$(edit "$arch" "домен" "ядро")"
# Субагент субагента разрешения не получает: его задание писал исполнитель
check 2 nested Edit "$(edit "$arch" "домен" "ядро")"
# Журнала нет — разрешения нет
check 2 ghost Edit "$(edit "$arch" "домен" "ядро")"

# Кривой вход — тихо пропускаем
check 0 plain Edit '{}'
printf 'не json "agent_id"' | "$guard" >/dev/null 2>&1 || { echo "  ✖ кривой вход не пропущен"; bad=1; }

[ "$bad" -eq 0 ] || exit 1
echo "  ✔ сторож решений: примеры сходятся"
