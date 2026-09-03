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
# Наполнение доски — по тому же доводу, что и реестр выше: роль seed
# отдаёт эти файлы Kandev как есть, и опечатка в YAML всплывает не здесь,
# а посреди выкатки, сообщением от чужого API. Заодно ловим шаг, который
# ссылается на роль, которой нет в prompts/: такая ссылка развернётся
# в пустоту молча, и агент получит промпт без половины смысла.
echo ""
echo "→ Проверяю наполнение доски Kandev"
ansible_run python3 -c "
import glob, os, re, sys, yaml

roles = {os.path.splitext(os.path.basename(f))[0] for f in glob.glob('/kandev/prompts/*.md')}
files = sorted(glob.glob('/kandev/workflows/*.yml'))
if not roles or not files:
    print('  \u2716 в /kandev пусто: нет ролей или нет цепочек'); sys.exit(1)

bad = 0
for f in files:
    try:
        d = yaml.safe_load(open(f))
    except Exception as e:
        print(f'  \u2716 {os.path.basename(f)} не разбирается:'); print('   ', e); bad = 1; continue
    if (d or {}).get('type') != 'kandev_workflow' or (d or {}).get('version') != 1:
        print(f'  \u2716 {os.path.basename(f)}: не переносимый формат Kandev (version: 1, type: kandev_workflow)'); bad = 1; continue
    for w in d.get('workflows') or []:
        for step in w.get('steps') or []:
            for ref in re.findall(r'(?:^|\s)@([a-zA-Z0-9_-]+)', step.get('prompt') or ''):
                if ref not in roles:
                    print(f'  \u2716 {os.path.basename(f)}, шаг «{step.get(\"name\")}»: ссылка @{ref}, а роли с таким именем в prompts/ нет'); bad = 1
sys.exit(bad)
"
echo "  ✔ ролей: $(find kandev/prompts -name '*.md' | wc -l), цепочек: $(find kandev/workflows -name '*.yml' | wc -l), ссылки @имя разрешаются"

echo ""
echo "→ Проверяю сценарии Ansible"
ansible_run ansible-lint site.yml

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
