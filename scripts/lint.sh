#!/usr/bin/env bash
#
# Проверить сам код настройки: сценарии Ansible и скрипты обвязки.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

# Реестр разбираем первым: битый YAML здесь роняет выкатку в середине
# прогона, а сообщение приходит от Ansible и указывает не туда. Один раз
# так и вышло — осталась строка-заглушка после добавления машины.
echo "→ Проверяю реестр машин"
ansible_run python3 -c "
import sys, yaml
try:
    d = yaml.safe_load(open('/servers.yml'))
except Exception as e:
    print('  ✖ servers.yml не разбирается:'); print('   ', e); sys.exit(1)
hosts = (d or {}).get('all', {}).get('children', {}).get('dev', {}).get('hosts') or {}
print(f'  ✔ разбирается, машин: {len(hosts)}')
for name, h in hosts.items():
    h = h or {}
    if not h.get('dev_public_address'):
        print(f'  ✖ у машины {name} нет dev_public_address'); sys.exit(1)
    if not h.get('dev_host_fingerprint'):
        print(f'  ⚠ у машины {name} нет отпечатка ключа — впишется после первой выкатки')
"
# Цепочки оркестратора — по тому же доводу, что и реестр выше: линтер
# движка читает их при каждой загрузке, и опечатка в `next` всплывает не
# здесь, а посреди живой задачи. Заодно ловим шаг, ссылающийся на роль,
# которой нет в prompts/: такая ссылка развернётся в пустоту молча.
echo ""
echo "→ Проверяю цепочки оркестратора"
python3 - <<'PY'
import glob, os, sys
sys.path.insert(0, "orch/src")
from orch.chain import ChainError, load, prompts_dir

files = sorted(glob.glob("orch/chains/*.yml"))
if not files:
    print("  \u2716 в orch/chains пусто"); sys.exit(1)
bad = 0
for path in files:
    try:
        chain = load(path)
    except ChainError as exc:
        print(f"  \u2716 {os.path.basename(path)}: {exc}"); bad = 1; continue
    for step in chain.steps:
        role = prompts_dir() / f"{step.prompt_file}.md"
        if not role.exists():
            print(f"  \u2716 {chain.name}, шаг «{step.id}»: нет файла роли {role.name}"); bad = 1
    for name in chain.includes:
        if not (prompts_dir() / f"{name}.md").exists():
            print(f"  \u2716 {chain.name}: нет общего промпта {name}.md"); bad = 1
sys.exit(bad)
PY
echo "  ✔ цепочек: $(find orch/chains -name '*.yml' | wc -l), ролей: $(find orch/prompts -name 'role-*.md' | wc -l), файлы ролей на месте"

echo ""
echo "→ Проверяю сценарии Ansible"
ansible_run ansible-lint site.yml

# Роли кладут на машину не только bash-скрипты: служба лимитов — это скрипт
# на Python. Опечатку в нём иначе поймал бы только systemd на машине, уже
# после выкатки. Разбираем деревом, а не py_compile: тот кладёт рядом
# скомпилированный файл, и в репозитории появлялся бы мусор.
echo ""
echo "→ Проверяю python-скрипты ролей"
py_files=()
while IFS= read -r f; do
    head -n1 "$f" | grep -qE '^#!.*python' && py_files+=( "/work/${f#"${ROOT_DIR}/ansible/"}" )
done < <(find "${ROOT_DIR}/ansible" -type f ! -name '*.j2' | sort)

if [ ${#py_files[@]} -eq 0 ]; then
    echo "  скриптов на Python в ролях нет"
else
    ansible_run python3 -c "
import ast, sys
bad = 0
for path in sys.argv[1:]:
    try:
        ast.parse(open(path, encoding='utf-8').read(), filename=path)
    except SyntaxError as e:
        print(f'  \u2716 {path}:{e.lineno}: {e.msg}'); bad = 1
if not bad:
    print(f'  \u2714 разбираются, файлов: {len(sys.argv) - 1}')
sys.exit(bad)
" "${py_files[@]}"
fi

# Сам shellcheck ставить на хост нельзя, поэтому запускаем его в контейнере.
#
# Образ не достался — расходимся по-разному, и это важно. На своей машине
# пропуск уместен: причина обычно бытовая (нет сети, предел частоты у Docker
# Hub), а проверка всё равно повторится в CI.
#
# В CI пропускать нельзя. Раньше пропускалось и там: не скачался образ —
# печаталась строка «shellcheck недоступен» и возвращался ноль. Предел
# частоты Docker Hub — дело обыденное, так что правки во всех скриптах
# обвязки могли уехать в main непроверенными, а единственным следом была
# строка в журнале, которую никто не читает. Молчаливо пропущенная проверка
# хуже отсутствующей: на неё рассчитывают.
# Проверяем не только обвязку: роли кладут на машину bash-скрипты (ports,
# ports-web — вместе больше, чем все scripts/*.sh), и они оставались вне
# проверки. Ищем по shebang, а не списком: добавленный скрипт попадёт под
# проверку сам, без правки этого файла. Шаблоны (*.j2) пропускаем — до
# подстановки Jinja это не разбираемый bash.
# Пути собираем от корня репозитория, а не глобом от текущего каталога:
# иначе результат зависит от того, откуда позвали (из корня зовёт make, но
# не обязан звать человек), а незаданный глоб уехал бы в shellcheck строкой.
shell_files=()
while IFS= read -r f; do
    head -n1 "$f" | grep -qE '^#!.*(bash|sh)\b' && shell_files+=( "${f#"${ROOT_DIR}/"}" )
done < <(find "${ROOT_DIR}/scripts" "${ROOT_DIR}/ansible" -type f ! -name '*.j2' | sort)

if docker image inspect koalaman/shellcheck:stable >/dev/null 2>&1 \
   || docker pull -q koalaman/shellcheck:stable >/dev/null 2>&1; then
    echo ""
    echo "→ Проверяю скрипты обвязки и скрипты ролей"
    docker run --rm -v "${ROOT_DIR}:/mnt" -w /mnt koalaman/shellcheck:stable \
        --external-sources --source-path=/mnt/scripts \
        "${shell_files[@]}" \
        && echo "  без замечаний (проверено файлов: ${#shell_files[@]})"
elif [ -n "${CI:-}" ]; then
    echo ""
    echo "  ✖ shellcheck недоступен: образ koalaman/shellcheck:stable не достался."
    echo "    В CI это отказ, а не пропуск — иначе скрипты уедут непроверенными."
    exit 1
else
    echo "  shellcheck недоступен, пропускаю проверку скриптов"
    echo "  (в CI такой пропуск считается отказом)"
fi
