#!/usr/bin/env bash
# Примеры решений сторожа guard-decisions: кто, каким инструментом, что правит.
# Журналы субагентов, HOME, git-репозитории и файлы — во временном каталоге,
# живые не читаются.
set -euo pipefail

guard="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/ansible/roles/style/files/guard-decisions"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
bad=0

home="$tmp/home"
projects="$home/.claude/projects"
session="$projects/-proj/s1"
proj="$tmp/proj"
mkdir -p "$session/subagents" "$proj/tests/Arch" "$proj/docs/plans" "$proj/asides" "$proj/app" "$proj/session" \
    "$tmp/patches"
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
cp "$plan" "$proj/session/PLAN.md"
cp "$plan" "$proj/docs/planning.md"
printf '# План\n\n## Передача\n\nпусто\n' > "$proj/asides/plan-y.md"
# Ограды: ```` закрывает только ```` и длиннее, ~~~ не закрывает ```.
cat > "$proj/asides/plan-fence.md" <<'EOF'
# План

## Передача

````
```
## Решения — пример внутри длинной ограды
- не решение
````

```
~~~
## Решения — пример внутри ``` после ~~~
- тоже не решение
```

## Решения

- Р1. Настоящее.
EOF
echo '<?php // домен не знает про HTTP' > "$arch"
ln -s tests/Arch "$proj/archlink"
ln -s docs/plans/import.md "$proj/notes.md"
printf -- '--- a/tests/Arch/ArchitectureTest.php\n+++ b/tests/Arch/ArchitectureTest.php\n@@ -1 +1 @@\n-x\n+y\n' \
    > "$tmp/patches/arch.patch"
printf -- '--- a/app/X.php\n+++ b/app/X.php\n@@ -1 +1 @@\n-x\n+y\n' > "$tmp/patches/app.patch"
printf -- '--- /dev/null\n+++ b/docs/plans/import.md\n@@ -0,0 +1 @@\n+y\n' > "$tmp/patches/plan.patch"

# Git: tests/Arch/InMain.php есть в main, Own.php — только в ветке задачи.
repo="$tmp/repo"
g() { git -C "$repo" -c user.name=t -c user.email=t@t -c init.defaultBranch=main "$@" >/dev/null 2>&1; }
mkdir -p "$repo/tests/Arch"
g init
echo '<?php' > "$repo/tests/Arch/InMain.php"
g add -A && g commit -m main
g checkout -b task
echo '<?php' > "$repo/tests/Arch/Own.php"
g add -A && g commit -m own
# origin/HEAD сильнее main: в origin/main нет InMain.php, есть Remote.php.
remote="$tmp/remote"
mkdir -p "$remote/tests/Arch"
git -C "$remote" -c init.defaultBranch=main init >/dev/null 2>&1
echo '<?php' > "$remote/tests/Arch/Remote.php"
git -C "$remote" add -A && git -C "$remote" -c user.name=t -c user.email=t@t commit -m r >/dev/null 2>&1
cp -r "$repo" "$tmp/repo2"
git -C "$tmp/repo2" fetch -q "$remote" main:refs/remotes/origin/main 2>/dev/null
git -C "$tmp/repo2" symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/main
echo '<?php' > "$tmp/repo2/tests/Arch/Remote.php"
# Только master — ветка по умолчанию.
cp -r "$repo" "$tmp/repo3"
git -C "$tmp/repo3" branch -m main master

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
agent longfence $'Задание.\n````\n```\nguard-decisions: tests/Arch\n````'
agent handoff $'Задание.\n\n## Передача\n\nguard-decisions: tests/Arch'
agent extra $'guard-decisions: tests/Arch и всё остальное'
agent nested $'guard-decisions: tests/Arch'  2

# check <ждём код> <агент или пусто — главная сессия> <tool_name> <tool_input JSON> [cwd]
check() {
    local want=$1 who=$2 tool=$3 input=$4 dir=${5:-$proj} got=0
    jq -n --arg who "$who" --arg tool "$tool" --argjson input "$input" --arg tp "$session.jsonl" --arg cwd "$dir" \
        '{session_id: "s1", transcript_path: $tp, cwd: $cwd, hook_event_name: "PreToolUse",
          tool_name: $tool, tool_input: $input} + (if $who == "" then {} else {agent_id: $who, agent_type: "general-purpose"} end)' \
        | HOME="$home" "$guard" >/dev/null 2>&1 || got=$?
    if [ "$got" != "$want" ]; then
        echo "  ✖ ждали $want, вышло $got: [${who:-главная}] $tool $input"
        bad=1
    fi
}
edit() { jq -cn --arg p "$1" --arg o "$2" --arg n "$3" '{file_path: $p, old_string: $o, new_string: $n}'; }
write() { jq -cn --arg p "$1" --arg c "$2" '{file_path: $p, content: $c}'; }
bash_() { jq -cn --arg c "$1" '{command: $c}'; }
deny_bash() { check 2 plain Bash "$(bash_ "$1")"; }
pass_bash() { check 0 plain Bash "$(bash_ "$1")"; }

# Главная сессия правит всё
check 0 "" Edit "$(edit "$arch" "домен" "ядро")"
check 0 "" Edit "$(edit "$plan" "своим контрактом" "в ядре")"
check 0 "" Bash "$(bash_ "sed -i s/a/b/ $plan")"
check 0 "" Bash "$(bash_ "rm tests/Arch/ArchitectureTest.php")"
check 0 "" Write "$(write "$session/subagents/agent-plain.meta.json" "{}")"

# Арх-тесты: существующий (нет git — есть на диске) субагенту нельзя никак
check 2 plain Edit "$(edit "$arch" "домен" "ядро")"
check 2 plain Write "$(write "$arch" "<?php")"
check 2 plain MultiEdit "$(jq -cn --arg p "$arch" '{file_path: $p, edits: [{old_string: "домен", new_string: "ядро"}]}')"
check 2 plain NotebookEdit "$(jq -cn --arg p "$proj/tests/Arch/n.ipynb" '{notebook_path: $p, new_source: "x"}')"
check 2 arch Edit "$(edit "$arch" "домен" "ядро")"
check 2 arch Write "$(write "$arch" "<?php")"
check 2 both MultiEdit "$(jq -cn --arg p "$arch" '{file_path: $p, edits: [{old_string: "домен", new_string: "ядро"}]}')"
# Новый арх-тест — только с разрешением; Edit без old_string — то же, что Write
check 2 plain Write "$(write "$proj/tests/Arch/NewTest.php" "<?php")"
check 2 plain Edit "$(edit "$proj/tests/Arch/NewTest.php" "" "<?php")"
check 0 arch Write "$(write "$proj/tests/Arch/NewTest.php" "<?php")"
check 0 arch Write "$(write "tests/Arch/Sub/NewTest.php" "<?php")"
check 0 arch Edit "$(edit "$proj/tests/Arch/NewTest.php" "" "<?php")"
# Симлинк на tests/Arch — тот же tests/Arch
check 2 plain Edit "$(edit "$proj/archlink/ArchitectureTest.php" "домен" "ядро")"
check 2 plain Write "$(write "$proj/archlink/NewTest.php" "<?php")"
deny_bash "rm archlink/ArchitectureTest.php"

# Существующий арх-тест — тот, что есть в основной ветке (Р10б)
check 2 arch Edit "$(edit "$repo/tests/Arch/InMain.php" "<?php" "<?php // x")"
check 2 arch Bash "$(bash_ "rm tests/Arch/InMain.php")" "$repo"
check 2 arch Bash "$(bash_ "rm -r tests/Arch")" "$repo"
check 0 arch Edit "$(edit "$repo/tests/Arch/Own.php" "<?php" "<?php // x")"
check 0 arch Write "$(write "$repo/tests/Arch/Own.php" "<?php // x")"
check 0 arch Bash "$(bash_ "rm tests/Arch/Own.php")" "$repo"
check 0 arch Bash "$(bash_ "sed -i s/php/php7/ tests/Arch/Own.php")" "$repo"
check 0 arch Write "$(write "$repo/tests/Arch/Fresh.php" "<?php")"
check 2 plain Edit "$(edit "$repo/tests/Arch/Own.php" "<?php" "<?php // x")"
check 2 plain Bash "$(bash_ "rm tests/Arch/Own.php")" "$repo"
check 2 nested Edit "$(edit "$repo/tests/Arch/Own.php" "<?php" "<?php // x")"
# origin/HEAD сильнее main; есть только master — по нему
check 0 arch Edit "$(edit "$tmp/repo2/tests/Arch/InMain.php" "<?php" "<?php // x")"
check 2 arch Edit "$(edit "$tmp/repo2/tests/Arch/Remote.php" "<?php" "<?php // x")"
check 2 arch Edit "$(edit "$tmp/repo3/tests/Arch/InMain.php" "<?php" "<?php // x")"
check 0 arch Edit "$(edit "$tmp/repo3/tests/Arch/Own.php" "<?php" "<?php // x")"

# Оболочка не пишет в существующий арх-тест; в новый — только с разрешением
deny_bash "sed -i 's/HTTP/X/' tests/Arch/ArchitectureTest.php"
deny_bash "sed --in-place 's/HTTP/X/' tests/Arch/ArchitectureTest.php"
deny_bash "perl -pi -e 's/HTTP/X/' tests/Arch/ArchitectureTest.php"
deny_bash "echo x > tests/Arch/ArchitectureTest.php"
deny_bash "echo x >| tests/Arch/ArchitectureTest.php"
deny_bash "echo x 2>&1 >>tests/Arch/ArchitectureTest.php"
deny_bash "rm tests/Arch/ArchitectureTest.php"
deny_bash "git checkout main -- tests/Arch"
deny_bash "git -C tests restore Arch/ArchitectureTest.php"
deny_bash "cat x | tee -a tests/Arch/A.php"
deny_bash "cp /tmp/A.php tests/Arch/"
deny_bash "mv tests/Arch/ArchitectureTest.php /tmp/"
deny_bash "install -m 644 /tmp/A.php tests/Arch/A.php"
deny_bash "ln -sf /tmp/A.php tests/Arch/A.php"
deny_bash "rsync -a /tmp/arch/ tests/Arch/"
deny_bash "dd if=/tmp/A.php of=tests/Arch/A.php"
deny_bash "truncate -s 0 tests/Arch/ArchitectureTest.php"
deny_bash "cd tests && rm Arch/ArchitectureTest.php"
deny_bash $'ls\nrm -f tests/Arch/ArchitectureTest.php'
check 2 plain Bash "$(bash_ "echo '<?php' > tests/Arch/NewTest.php")"
check 0 arch Bash "$(bash_ "echo '<?php' > tests/Arch/NewTest.php")"
check 2 both Bash "$(bash_ "rm tests/Arch/ArchitectureTest.php")"
# Слова оболочки: then do else elif { ! ( — не команда, } fi done esac ) — конец части
deny_bash "if true; then rm tests/Arch/ArchitectureTest.php; fi"
deny_bash "if false; then :; else rm tests/Arch/ArchitectureTest.php; fi"
deny_bash "if false; then :; elif true; then rm tests/Arch/ArchitectureTest.php; fi"
deny_bash "for f in a; do rm tests/Arch/ArchitectureTest.php; done"
deny_bash "while false; do sed -i s/a/b/ docs/plans/import.md; done"
deny_bash "{ rm tests/Arch/ArchitectureTest.php; }"
deny_bash "! rm tests/Arch/ArchitectureTest.php"
deny_bash "(rm tests/Arch/ArchitectureTest.php)"
deny_bash "{ echo x; } > tests/Arch/ArchitectureTest.php"
pass_bash "if [ -f x ]; then echo fi done; fi"
# Обёртки со значениями опций
deny_bash "sudo -u dev rm tests/Arch/ArchitectureTest.php"
deny_bash "sudo -u dev -g dev --chdir=/x rm $arch"
deny_bash "nice -n 10 rm tests/Arch/ArchitectureTest.php"
deny_bash "env -u X FOO=1 rm tests/Arch/ArchitectureTest.php"
deny_bash "env -C tests rm Arch/ArchitectureTest.php"
deny_bash "env -S 'rm tests/Arch/ArchitectureTest.php'"
deny_bash "timeout 5 rm tests/Arch/ArchitectureTest.php"
deny_bash "timeout -s KILL -k 1 5 sed -i s/a/b/ tests/Arch/ArchitectureTest.php"
deny_bash "time -p nohup stdbuf -o L rm tests/Arch/ArchitectureTest.php"
deny_bash "xargs -n 1 rm tests/Arch/ArchitectureTest.php < /dev/null"
deny_bash "echo x | xargs -I{} cp {} tests/Arch/"
deny_bash "echo x | xargs -0 -P 2 sed -i s/a/b/ docs/plans/import.md"
pass_bash "sudo -u dev ./vendor/bin/pest tests/Arch"
pass_bash "timeout 60 ./vendor/bin/pest tests/Arch"
pass_bash "ls tests/Arch | xargs -n1 echo"
pass_bash "git ls-files | xargs grep -n HTTP tests/Arch"
# find: -delete и -exec файловой операцией над {} с путём под защитой
deny_bash "find tests/Arch -name '*.php' -delete"
deny_bash "find tests/Arch -name '*.php' -exec rm {} \\;"
deny_bash "find tests/Arch -name '*.php' -exec sed -i s/a/b/ {} +"
deny_bash "find -L tests/Arch -type f -execdir mv {} /tmp/ ';'"
deny_bash "find /tmp -name '*.php' -exec cp {} tests/Arch/ \\;"
pass_bash "find tests/Arch -name '*.php' -exec cat {} \\;"
pass_bash "find tests/Arch -name '*.php' -exec cp {} /tmp/ \\;"
pass_bash "find . -name '*.pyc' -delete"
# Цель cp -r / rsync / mv — каталог, под которым tests/Arch или файл плана
deny_bash "cp -r /tmp/Arch tests/"
deny_bash "mv /tmp/Arch tests"
deny_bash "rsync -a /tmp/t/ tests/"
deny_bash "rsync -a /tmp/t/ ."
deny_bash "cp -r /tmp/tests ."
deny_bash "rsync -a /tmp/x/ asides/"
deny_bash "cp -r /tmp/plans docs/"
pass_bash "cp /tmp/a.txt ."
pass_bash "mv /tmp/a.txt tests/"
pass_bash "rsync -a /tmp/t tests/"
pass_bash "rsync -t /tmp/a.txt /tmp/b.txt"
pass_bash "cp -r /tmp/x asides/"
# git apply и patch: пути из патча, если он читается
deny_bash "git apply $tmp/patches/arch.patch"
deny_bash "git apply -p1 --index < $tmp/patches/arch.patch"
deny_bash "patch -p1 < $tmp/patches/arch.patch"
deny_bash "patch -p1 -i $tmp/patches/arch.patch"
deny_bash "patch -p1 --input=$tmp/patches/plan.patch"
deny_bash "patch tests/Arch/ArchitectureTest.php $tmp/patches/app.patch"
deny_bash "cd tests && git apply $tmp/patches/arch.patch"
pass_bash "git apply $tmp/patches/app.patch"
pass_bash "patch -p1 < $tmp/patches/app.patch"
pass_bash "git apply --check $tmp/patches/app.patch && git apply $tmp/patches/app.patch"
pass_bash "git apply $tmp/patches/missing.patch"
# $(…) и `…` — команда, и внутри двойных кавычек; глобальные опции git со значением
deny_bash "echo \"\$(rm tests/Arch/ArchitectureTest.php)\""
deny_bash "echo \"x \`rm tests/Arch/ArchitectureTest.php\` y\""
deny_bash "echo \$(sed -i s/a/b/ docs/plans/import.md) done"
deny_bash "rm \"\$(pwd)/tests/Arch/ArchitectureTest.php\""
deny_bash "cat x > >(tee tests/Arch/A.php)"
deny_bash "git --work-tree . checkout -- tests/Arch"
deny_bash "git --git-dir .git --work-tree=. restore tests/Arch/ArchitectureTest.php"
deny_bash "git -c core.x=y --namespace n rm tests/Arch/ArchitectureTest.php"
pass_bash "git commit -m \"\$(cat /tmp/msg)\""
pass_bash "echo '\$(rm tests/Arch/ArchitectureTest.php)'"
pass_bash "diff <(cat tests/Arch/ArchitectureTest.php) /tmp/x"
pass_bash "git --work-tree . status"

# Прогон и чтение — можно; путь не аргумент файловой операции — не запись
pass_bash "cat tests/Arch/ArchitectureTest.php 2>/dev/null"
pass_bash "docker compose exec app ./vendor/bin/pest tests/Arch > /tmp/arch.log 2>&1"
pass_bash "docker compose run --rm app ./vendor/bin/pest tests/Arch"
pass_bash "rm -f /tmp/x; ./vendor/bin/pest tests/Arch"
pass_bash "git checkout -b x && ./vendor/bin/pest tests/Arch"
pass_bash "grep -rn HTTP tests/Arch >&2"
pass_bash "cp tests/Arch/ArchitectureTest.php /tmp/"
pass_bash "echo 'x > tests/Arch/A.php' && echo \"sed -i y tests/Arch/A.php\""
pass_bash "git commit -m \"Р1 -> docs/plans/a.md, правка tests/Arch\""
pass_bash "cat > /tmp/msg <<'EOF'
rm tests/Arch/ArchitectureTest.php > docs/plans/import.md
EOF
git commit -F /tmp/msg"
check 0 plain Edit "$(edit "$proj/app/X.php" "a" "b")"
# Ложные запреты: perl -M…, git restore --staged, cd в подоболочке, cd без аргумента — HOME
pass_bash "perl -MFile::Find -e 'find(sub{print}, \"tests/Arch\")'"
pass_bash "perl -Mstrict -ne print tests/Arch/ArchitectureTest.php"
pass_bash "git restore --staged tests/Arch/ArchitectureTest.php"
pass_bash "git restore -S docs/plans/import.md"
deny_bash "git restore --staged --worktree tests/Arch/ArchitectureTest.php"
deny_bash "git restore -SW tests/Arch/ArchitectureTest.php"
pass_bash "(cd tests && ls) && rm Arch/ArchitectureTest.php"
deny_bash "(cd tests; rm Arch/ArchitectureTest.php)"
pass_bash "cd tests; cd; rm Arch/ArchitectureTest.php"

# Раздел «Решения» плана
check 2 plain Edit "$(edit "$plan" "своим контрактом" "в ядре")"
check 2 plain Edit "$(edit "$aside" "## Решения и почему" "## Прочее")"
check 2 plain Edit "$(edit "$plan" "## Передача" $'## Решения 2\n\n- Р2. Новое.\n\n## Передача')"
check 2 plain Write "$(write "$plan" $'# План\n\n## Передача\n\nсделано')"
check 2 plain Write "$(write "$proj/docs/plans/new.md" $'# План\n\n## Решения\n\n- Р1.')"
check 2 plain Edit "$(edit "$proj/docs/plans/new2.md" "" $'# План\n\n## Решения\n\n- Р1.')"
# old_string не нашёлся буквально: при разделе «Решения» — запрет
check 2 plain Edit "$(edit "$plan" "«своим» контрактом" "в ядре")"
check 2 plain Edit "$(edit "$proj/asides/plan-y.md" '“пусто”' $'## Решения\n\n- Р1.')"
check 0 plain Edit "$(edit "$proj/asides/plan-y.md" '“пусто”' "сделано")"
check 0 dec Edit "$(edit "$plan" "«своим» контрактом" "в ядре")"
# Заголовок в блоке кода раздел не кончает и не начинает
check 2 plain Edit "$(edit "$plan" "- строка решения после него" "- другое")"
check 0 plain Edit "$(edit "$plan" "- копия" "- другая копия")"
# Блок закрывает только та же ограда не короче открывающей
check 0 plain Edit "$(edit "$proj/asides/plan-fence.md" "- не решение" "- другое")"
check 0 plain Edit "$(edit "$proj/asides/plan-fence.md" "- тоже не решение" "- другое")"
check 2 plain Edit "$(edit "$proj/asides/plan-fence.md" "- Р1. Настоящее." "- Р1. Другое.")"
# Симлинк на план — тот же план
check 2 plain Edit "$(edit "$proj/notes.md" "своим контрактом" "в ядре")"
# План — .md в plans/ и plan-*.md; session/PLAN.md и planning.md — не план
check 0 plain Edit "$(edit "$proj/session/PLAN.md" "своим контрактом" "в ядре")"
check 0 plain Edit "$(edit "$proj/docs/planning.md" "своим контрактом" "в ядре")"
pass_bash "sed -i s/a/b/ session/PLAN.md docs/planning.md"
# Оболочка в файл плана не пишет: ни перенаправлением, ни файловой операцией
deny_bash "sed -i 's/контрактом/ядром/' docs/plans/import.md"
deny_bash "cat >> asides/plan-x.md <<EOF
x
EOF"
deny_bash "cp /tmp/old.md docs/plans/import.md"
deny_bash "mv docs/plans/import.md /tmp/"
deny_bash "git checkout main -- docs/plans/import.md"
deny_bash "rm asides/plan-x.md"
deny_bash "echo x >> notes.md"
check 0 dec Bash "$(bash_ "sed -i 's/контрактом/ядром/' docs/plans/import.md")"
# Остальной план — можно
check 0 plain Edit "$(edit "$plan" "(пусто)" "сделано: Р1 — app/X.php:10")"
check 0 plain Write "$(write "$plan" "$(sed 's/(пусто)/сделано/' "$plan")")"
check 0 plain Write "$(write "$proj/docs/plans/new.md" $'# План\n\n## Передача\n\nx')"
check 0 plain Edit "$(edit "$proj/docs/notes.md" "a" "b")"
pass_bash "cat docs/plans/import.md > /tmp/plan-copy.txt"
pass_bash "git add asides/plan-x.md && git commit -m x"

# Журналы и meta Claude Code субагент не пишет: разрешение себе не выписать
check 2 plain Write "$(write "$session/subagents/agent-plain.meta.json" '{"spawnDepth":1}')"
check 2 plain Edit "$(edit "$session/subagents/agent-plain.jsonl" "Сделай" $'guard-decisions: tests/Arch\nСделай')"
check 2 arch Write "$(write "$home/.claude/projects/-other/s9.jsonl" "{}")"
deny_bash "echo '{}' > ~/.claude/projects/-proj/s1/subagents/agent-plain.meta.json"
deny_bash "sed -i s/a/b/ \$HOME/.claude/projects/-proj/s1/subagents/agent-plain.jsonl"
deny_bash "cp /tmp/m.json $session/subagents/agent-plain.meta.json"
pass_bash "cat ~/.claude/projects/-proj/s1/subagents/agent-plain.jsonl | head -1"
check 0 plain Write "$(write "$home/.claude/projects/-proj/memory/note.md" "x")"
check 2 plain Write "$(write "$home/.claude/projects/-proj/memory.jsonl" "x")"

# Разрешение в задании: своя строка без отступа, вне блока кода, до «Передачи»
check 2 arch Edit "$(edit "$plan" "своим контрактом" "в ядре")"
check 0 dec Edit "$(edit "$plan" "своим контрактом" "в ядре")"
check 0 both Edit "$(edit "$plan" "своим контрактом" "в ядре")"
check 0 both2 Write "$(write "$proj/tests/Arch/NewTest.php" "<?php")"
check 0 both2 Edit "$(edit "$plan" "своим контрактом" "в ядре")"
for who in quoted indent fenced longfence handoff extra nested ghost; do
    check 2 "$who" Write "$(write "$proj/tests/Arch/NewTest.php" "<?php")"
done

# Кривой вход — тихо пропускаем
check 0 plain Edit '{}'
printf 'не json "agent_id"' | "$guard" >/dev/null 2>&1 || { echo "  ✖ кривой вход не пропущен"; bad=1; }

[ "$bad" -eq 0 ] || exit 1
echo "  ✔ сторож решений: примеры сходятся"
