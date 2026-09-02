#!/usr/bin/env bash
#
# Общие части команд управления сервером. Подключается остальными скриптами
# в этом каталоге через `source`.
#
# Почему отдельный файл, а не Makefile: рецепт make — это одна строка для
# оболочки, склеенная из многих обратными слешами. В такой строке нет
# ни set -e, ни номеров строк в сообщениях об ошибках, ни возможности
# проверить кусок отдельно, а каждый знак доллара надо удваивать.

# -e   любая необработанная ошибка останавливает работу
# -u   обращение к незаданной переменной — ошибка, а не пустая строка
# pipefail  ошибка в середине конвейера не теряется
set -euo pipefail

# Корень репозитория. В этом проекте scripts/ лежит прямо в корне,
# а не в infra/, как было в источнике, — поэтому до него один шаг вверх,
# а не два.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly ROOT_DIR

readonly ANSIBLE_IMAGE="vps-dev-ansible"
readonly KNOWN_HOSTS="${ROOT_DIR}/ansible/known_hosts"

# Секреты передаются в контейнер поимённо, а не файлом целиком: список ниже
# и есть полный перечень того, что Ansible вообще видит. Всё, чего в нём нет,
# до контейнера не доезжает — даже если лежит в .env.
#
# Список короче, чем у боевого сервера, и не потому, что что-то забыто.
# Этот сервер не открыт наружу и не обслуживает приложение — поэтому здесь
# нет ни секретов Cloudflare (домены и сертификаты не нужны машине, у которой
# нет ни одного публичного порта), ни токена реестра контейнеров (образы
# сюда никто не выкатывает), ни токена Ubuntu Pro (машина не боевая, платить
# за расширенную поддержку незачем). Пароль root и ключ Tailscale остались
# по той же причине, что и там: без пароля root не попасть в веб-консоль
# провайдера, если сеть недоступна, а без ключа Tailscale машина не войдёт
# в частную сеть — свой единственный вход.
readonly SECRETS=(
    TAILSCALE_AUTHKEY
    VPS_DEV_ROOT_PASSWORD
    VPS_DEV_NTFY_TOPIC
)

die() { echo "✖ $*" >&2; exit 1; }
say() { echo "→ $*"; }

# --- Значения из .env --------------------------------------------------------
#
# Здесь нет SOPS и расшифровки: этот проект не хранит зашифрованное
# состояние в репозитории. У каждого своя машина и свои секреты в одном
# экземпляре, поэтому секреты берутся только из окружения — его кладёт
# GitHub Actions из секретов форка — либо из локального .env на своей
# машине. Читаем значения, а не исполняем файл: `source` выполнил бы любой
# код, который туда попадёт.
env_get() {
    local key="$1" line value
    # Переменная окружения сильнее всего: так работает запуск в CI.
    if [ -n "${!key:-}" ]; then printf '%s' "${!key}"; return 0; fi
    # И только потом .env — ручной запасной путь для своей машины.
    #
    # Кавычки снимаем: их ставил прежний писатель этого файла, и без
    # обратного шага пароль со знаком ' доезжал до Ansible искажённым.
    [ -f "${ROOT_DIR}/.env" ] || return 0
    line="$(grep -m1 "^${key}=" "${ROOT_DIR}/.env" || true)"
    [ -n "$line" ] || return 0
    value="${line#*=}"
    if [[ "$value" == \'*\' || "$value" == \"*\" ]]; then
        value="${value:1:${#value}-2}"
        value="${value//\'\\\'\'/\'}"
    fi
    printf '%s' "$value"
}

# Значение для конкретной машины. Правило одно на все секреты: сначала ищем
# КЛЮЧ_ИМЯ_МАШИНЫ, не нашли — берём общий КЛЮЧ.
#
# Раньше «своё на каждую машину» было прибито в коде для двух паролей.
# Теперь любой секрет становится машинным добавлением строки в .env,
# без правки скриптов — скажем, отдельный ключ сети для другого региона.
env_get_for() {
    local name="$1" key="$2" value
    value="$(env_get "${key}_$(machine_key "$name")")"
    [ -n "$value" ] || value="$(env_get "$key")"
    printf '%s' "$value"
}

# --- Ключ SSH ---------------------------------------------------------------
#
# Три источника, по убыванию силы:
#
#   VPS_DEV_SSH_PRIVATE_KEY  сам ключ строкой. Так его отдаёт хранилище CI,
#                            где файлов нет; кладём во временный файл;
#   VPS_DEV_SSH_KEY          путь к файлу. Так удобно на рабочем месте,
#                            где ключ называется по-своему;
#   ~/.ssh/vps_dev           если ничего не задано.
#
# Раньше путь был зашит в коде, и запустить команды с другой машины было
# нельзя, не правя скрипт.
SSH_KEY=""
SSH_KEY_TEMP=""
resolve_ssh_key() {
    local material
    material="$(env_get VPS_DEV_SSH_PRIVATE_KEY)"
    if [ -n "$material" ]; then
        # Права сужаем до владельца: ssh откажется работать с ключом,
        # доступным другим, и это правильно.
        SSH_KEY_TEMP="$(mktemp)"
        chmod 600 "$SSH_KEY_TEMP"
        printf '%s\n' "$material" > "$SSH_KEY_TEMP"
        SSH_KEY="$SSH_KEY_TEMP"
        return 0
    fi
    SSH_KEY="$(env_get VPS_DEV_SSH_KEY)"
    [ -n "$SSH_KEY" ] || SSH_KEY="${HOME}/.ssh/vps_dev"
    return 0
}

# Отсутствие ключа — ошибка только для команд, которым он нужен. Проверка
# кода (make lint) обходится без него, и в CI её задача идёт без секретов
# вовсе: требовать ключ сразу значило бы ронять её на пустом месте.
require_ssh_key() {
    [ -f "$SSH_KEY" ] || die "Не нашёл ключ SSH: ${SSH_KEY}
  Укажи путь в .env: VPS_DEV_SSH_KEY=/путь/к/ключу
  Либо передай сам ключ в VPS_DEV_SSH_PRIVATE_KEY — так его отдаёт CI."
}

# return 0 обязателен: без него обработчик выхода возвращает код последней
# проверки, и скрипт завершался бы с ошибкой, ничего не сделав неправильно.
# Временный файл с секретами. Заводится ansible_run, убирается здесь же,
# вместе с ключом: обработчик EXIT срабатывает и при обычном завершении,
# и при Ctrl-C, и при падении под set -e. Раньше стоял обработчик RETURN,
# и он не срабатывал ни при том, ни при другом — файл со всеми токенами
# оставался в /tmp навсегда. Права 0600 тут не спасали: на общем сервере
# соседние проекты работают под тем же пользователем.
ANSIBLE_ENV_FILE=""

cleanup_ssh_key() {
    [ -n "$SSH_KEY_TEMP" ] && rm -f "$SSH_KEY_TEMP"
    return 0
}
cleanup_ansible_env() {
    [ -n "$ANSIBLE_ENV_FILE" ] && rm -f "$ANSIBLE_ENV_FILE"
    ANSIBLE_ENV_FILE=""
}

cleanup_all() {
    cleanup_ssh_key
    cleanup_ansible_env
}

trap cleanup_all EXIT

# --- Секреты, свои у каждой машины ------------------------------------------
#
# Пароль root у каждой машины СВОЙ. Класть его в .env одним общим именем
# на все машины значило бы, что вторая машина получает пароль первой.
#
# Имя ключа в .env: ПАРОЛЬ_ИМЯ-МАШИНЫ прописными, дефисы заменены на нижнее
# подчёркивание. Скажем, VPS_DEV_ROOT_PASSWORD_VPS_DEV_FSN1.
machine_key() {
    printf '%s' "$1" | tr '[:lower:]-' '[:upper:]_'
}

# Заполняет OVERRIDE_VPS_DEV_ROOT_PASSWORD для указанной машины, создавая
# пароль, если его нет.
#
#   $1  имя машины
#   $2  "fresh" — машину настраивают впервые, пароль можно создать;
#       "known" — машина уже настроена, создавать пароль нельзя
#
# Различать обязательно. Иначе запуск с рабочего места, где нет .env, для
# уже настроенной машины создал бы новый пароль root и поставил его на
# сервер — а человек всего лишь хотел прогнать настройку.
ensure_machine_secrets() {
    local name="$1" state="${2:-known}" key rootvar rp
    key="$(machine_key "$name")"
    rootvar="VPS_DEV_ROOT_PASSWORD_${key}"

    rp="$(env_get_for "$name" VPS_DEV_ROOT_PASSWORD)"
    if [ -z "$rp" ]; then
        local gen="LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32"
        [ "$state" = "fresh" ] || [ "${VPS_DEV_RESET_ROOT_PASSWORD:-}" = "1" ] \
            || die "У машины ${name} нет пароля root, а машина уже настроена.
  Создать новый нельзя: он заменил бы тот, что стоит на сервере,
  и в веб-консоль провайдера ты больше не войдёшь.
  Возьми пароль из менеджера паролей и положи в .env ключом ${rootvar}
  (или в секреты форка на GitHub — тем же именем).
  Если пароль потерян и его правда надо сменить:
    VPS_DEV_RESET_ROOT_PASSWORD=1 make apply h=${name}"

        die "У машины ${name} нет пароля root.
  Он нужен только для веб-консоли провайдера, когда сеть недоступна
  и по SSH не зайти. По SSH бесполезен. У каждой машины он свой.

  Придумай его и положи в ДВА места — менеджер паролей и .env:
    ${gen}
    ${rootvar}=<пароль> в .env (или в секреты форка на GitHub)"
    fi

    export OVERRIDE_VPS_DEV_ROOT_PASSWORD="$rp"
}

# Значение секрета для текущей машины: подмена OVERRIDE_ИМЯ, иначе
# машинный ключ, иначе общий. Одно правило на оба способа запуска.
secret_value() {
    local v="$1" ovr="OVERRIDE_$1"
    if [ -n "${!ovr:-}" ]; then
        printf '%s' "${!ovr}"
    elif [ -n "${ANSIBLE_TARGET_MACHINE:-}" ]; then
        env_get_for "$ANSIBLE_TARGET_MACHINE" "$v"
    else
        env_get "$v"
    fi
}

# Строки «имя=значение» для файла окружения — всех секретов из SECRETS.
secrets_env_lines() {
    local v value
    for v in "${SECRETS[@]}"; do
        value="$(secret_value "$v")"
        # Файл окружения — строки «имя=значение», и перенос строки внутри
        # значения обрезал бы его молча. Сейчас таких секретов нет, но лучше
        # упасть внятно, чем передать половину ключа.
        case "$value" in
            *$'\n'*) die "Значение ${v} содержит перенос строки — так его передать нельзя." ;;
        esac
        printf '%s=%s\n' "$v" "$value"
    done
}

# --- Прогон на самой машине (pull-режим) --------------------------------------
#
# Первый прогон идёт по SSH задача за задачей: на свежей машине иначе никак.
# Он же ставит на машину Ansible (roles/pull). Дальше обвязка присылает
# репозиторий rsync'ом и запускает playbook на месте: задачи по 0,1 с
# вместо 1,5, а вывод идёт в тот же журнал — GitHub остаётся кнопкой
# и местом, где читают ошибки.
#
# Секреты доезжают файлом на tmpfs (/dev/shm) с правами 0600, через stdin
# SSH, и стираются до запуска playbook: в аргументах команды и в `ps`
# их нет. Открытая половина ключа обвязки передаётся переменной — она
# и так публична, а роль base по ней проверяет, что не стирает наш ключ.
# Относительно домашнего каталога dev на машине — и для rsync, и для cd.
readonly PULL_SRC='.vps-dev/src'

ssh_opts() {
    printf '%s' "-o BatchMode=yes -o ConnectTimeout=10 -o IdentitiesOnly=yes -o UserKnownHostsFile=${KNOWN_HOSTS} -i ${SSH_KEY}"
}

# Стоит ли на машине Ansible (его ставит roles/pull на первом прогоне).
remote_has_ansible() {
    local addr="$1"
    # shellcheck disable=SC2046  # флаги должны разбиться на слова
    ssh $(ssh_opts) "dev@${addr}" 'test -x /usr/local/bin/ansible-playbook' >/dev/null 2>&1
}

# ansible_pull_run ИМЯ АДРЕС [аргументы ansible-playbook…]
ansible_pull_run() {
    local name="$1" addr="$2"; shift 2
    require_ssh_key
    local opts; opts="$(ssh_opts)"

    say "${name}: Ansible на самой машине — присылаю репозиторий"
    # shellcheck disable=SC2086  # флаги должны разбиться на слова
    rsync -az --mkpath --delete --exclude .facts --exclude .ansible --exclude known_hosts \
        -e "ssh ${opts}" \
        "${ROOT_DIR}/ansible" "${ROOT_DIR}/servers.yml" "dev@${addr}:${PULL_SRC}/" \
        || die "Не смог прислать репозиторий на ${name}"

    local pubkey; pubkey="$(ssh-keygen -y -f "$SSH_KEY")"
    local env_remote="/dev/shm/vps-dev-$$.env"

    # Аргументы playbook — в одну строку, каждый экранирован для удалённой
    # оболочки: имена машин, метки и -e без пробелов, но %q не даст
    # ошибиться, если что-то появится.
    local args="" a
    for a in "$@" "-e" "dev_pull_mode=true" "-e" "dev_control_pubkey=${pubkey}"; do
        args+=" $(printf '%q' "$a")"
    done

    # shellcheck disable=SC2086,SC2029  # флаги должны разбиться на слова; подстановки — намеренно здесь
    secrets_env_lines | ssh $opts "dev@${addr}" "umask 077; cat > ${env_remote}" \
        || die "Не смог передать секреты на ${name}"

    # Файл окружения читается и тут же стирается — до запуска playbook.
    # shellcheck disable=SC2086,SC2029  # флаги должны разбиться на слова; подстановки — намеренно здесь
    ssh $opts "dev@${addr}" "set -a; . ${env_remote}; set +a; rm -f ${env_remote};
        cd ${PULL_SRC}/ansible &&
        ANSIBLE_CONFIG=ansible.cfg \
        ANSIBLE_COLLECTIONS_PATH=/usr/share/ansible/collections \
        ANSIBLE_FORCE_COLOR=1 \
        /usr/local/bin/ansible-playbook -i ../servers.yml -i inventory -c local site.yml${args}"
}

# --- Запуск Ansible в контейнере ---------------------------------------------
#
# Контейнер работает от текущего пользователя, а не от root: иначе файлы,
# которые Ansible создаёт в каталоге проекта, оказываются принадлежащими root.
# Секрет можно подменить на время одного запуска: положить значение
# в переменную OVERRIDE_ИМЯ. Так пароль конкретной машины доезжает
# до Ansible под общим именем, и сценариям не нужно знать, что паролей
# столько же, сколько машин.
ansible_run() {
    # Значения передаём ФАЙЛОМ, а не флагами -e ИМЯ=значение. Флаги попадают
    # в аргументы команды, а значит видны в `ps aux` любому на машине. Сервер
    # разработки общий: рядом живут другие проекты и другие сессии агентов,
    # и во время прогона им были бы видны пароль root и ключ частной сети.
    #
    # Файл создаётся с правами 0600 до записи, а не после: иначе он на миг
    # существует доступным для чтения всем. Убирается в любом случае, включая
    # прерывание с клавиатуры.
    local env_file
    env_file="$(mktemp "${TMPDIR:-/tmp}/vps-dev-ansible-env.XXXXXX")"
    chmod 600 "$env_file"
    # Запоминаем глобально: убирает его обработчик EXIT вместе с ключом.
    # Обработчик RETURN, который стоял здесь раньше, не срабатывал ни при
    # Ctrl-C, ни при падении под set -e.
    ANSIBLE_ENV_FILE="$env_file"

    # Ansible читает переменные окружения через lookup('env'), поэтому
    # передаём именно окружением, а не через -e: так значение не станет
    # ещё и переменной сценария с тем же именем.
    secrets_env_lines >> "$env_file"

    # Ключ монтируем, только если он есть: иначе Docker создал бы на его
    # месте пустой каталог, а команде вроде make lint он и не нужен.
    local -a key_mount=()
    [ -f "$SSH_KEY" ] && key_mount=(-v "${SSH_KEY}:/ssh/key:ro")

    docker run --rm -i \
        --env-file "$env_file" \
        --user "$(id -u):$(id -g)" \
        -v "${ROOT_DIR}/ansible:/work" \
        -v "${ROOT_DIR}/servers.yml:/servers.yml:ro" \
        "${key_mount[@]}" \
        -v /etc/passwd:/etc/passwd:ro \
        -v /etc/group:/etc/group:ro \
        -w /work \
        -e HOME=/tmp \
        -e ANSIBLE_CONFIG=/work/ansible.cfg \
        -e ANSIBLE_FORCE_COLOR=1 \
        "$ANSIBLE_IMAGE" "$@"
    local rc=$?
    cleanup_ansible_env
    return $rc
}

# --- Реестр машин ------------------------------------------------------------
#
# Строки «имя адрес». Ошибку чтения от пустого реестра отличаем явно: раньше
# вывод ansible-inventory глушился, jq на пустом входе возвращал успех,
# и человеку сообщали «в реестре нет машин» — про файл, где всё правильно.
# Строки «имя публичный-адрес».
SERVERS=""
load_servers() {
    local raw
    raw="$(ansible_run ansible-inventory --list)" || die "Не смог прочитать реестр машин, причина выше"
    SERVERS="$(printf '%s' "$raw" | jq -r '
        ._meta.hostvars as $hv
        | .dev.hosts[]?
        | "\(.) \($hv[.].dev_public_address // "-")"')" \
        || die "Реестр прочитан, но разобрать его не вышло. Проверь servers.yml"
    [ -n "$SERVERS" ] || die "В servers.yml нет ни одной машины в группе dev"
}

# Публичный адрес. Нужен проверкам «что видно снаружи» и как запасной путь.
server_public_address() {
    local name="$1" addr
    addr="$(printf '%s\n' "$SERVERS" | awk -v n="$name" '$1 == n {print $2}')"
    [ -n "$addr" ] && [ "$addr" != "-" ] || die "У машины ${name} в servers.yml нет dev_public_address."
    printf '%s' "$addr"
}

# Адрес машины в частной сети, спрошенный у самой сети по имени машины.
#
# Не храним его в реестре намеренно: хранимая копия однажды разъезжается
# с реальностью — так уже было. Сеть знает правду всегда.
discover_tailnet_address() {
    local name="$1"
    command -v tailscale >/dev/null 2>&1 || return 0
    tailscale status --json 2>/dev/null | jq -r --arg n "$name" '
        (.Peer // {}) | to_entries[]
        | select(.value.HostName == $n or ((.value.DNSName // "") | startswith($n + ".")))
        | .value.TailscaleIPs[0] // empty' 2>/dev/null | head -1
}

# Куда подключаться: частная сеть, если машина там есть, иначе публичный адрес.
server_address() {
    local name="$1" found
    found="$(discover_tailnet_address "$name")"
    if [ -n "$found" ]; then printf '%s' "$found"; return 0; fi
    server_public_address "$name"
}

# Отпечаток ключа машины, записанный в реестре.
server_fingerprint() {
    ansible_run ansible-inventory --host "$1" 2>/dev/null \
        | jq -r '.dev_host_fingerprint // empty'
}

# --- Выбор машин -------------------------------------------------------------
#
# Заполняет глобальный массив PICKED.
#
#   $1  имя машины, если задано заранее (h=)
#   $2  "all" — разрешён ответ «все машины», "one" — нужна ровно одна
#
# Именно массив, а не вывод в поток. Причина: при `mapfile < <(pick_targets)`
# функция выполняется в отдельной оболочке, и выход по ошибке останавливает
# только её. Вызывающий скрипт продолжал работу с пустым списком машин
# и звал Ansible вообще без хостов.
#
# Умолчания «все машины» у команд, которые что-то меняют, нет намеренно:
# нажать Enter проще всего, и это не должно означать «примени на всех».
PICKED=()
# Значение массива PICKED забирают скрипты, которые подключают этот файл, —
# изнутри самого файла оно выглядит неиспользуемым.
# shellcheck disable=SC2034
pick_targets() {
    local wanted="${1:-}" mode="${2:-one}" names count pick
    names="$(printf '%s\n' "$SERVERS" | awk '{print $1}')"
    count="$(printf '%s\n' "$names" | grep -c . || true)"

    # Заданную заранее машину принимаем и по имени, и по номеру из списка.
    # Номера те же, что показывает меню: раз человек их там видит, они должны
    # работать и в аргументе, и в поле у кнопки в GitHub. Раньше номер
    # принимало только меню, и выкатка падала на «машине по имени 1».
    if [ -n "$wanted" ]; then
        local one=""
        case "$wanted" in
            ''|*[!0-9]*) printf '%s\n' "$names" | grep -qx -- "$wanted" && one="$wanted" ;;
            *)           one="$(printf '%s\n' "$names" | sed -n "${wanted}p")" ;;
        esac
        if [ -z "$one" ]; then
            {
                echo "✖ Не нашёл машину «${wanted}». Есть такие:"
                printf '%s\n' "$SERVERS" | nl -w4 -s') ' | awk '{printf "  %s\n", $0}'
                echo "  Можно указать имя или номер."
            } >&2
            exit 1
        fi
        PICKED=("$one")
        return
    fi

    if [ "$count" -eq 1 ]; then
        mapfile -t PICKED <<< "$names"
        return
    fi

    if [ ! -t 0 ]; then
        [ "$mode" = "all" ] || die "Машин несколько, терминала нет. Назови машину: h=имя"
        say "Терминала нет, спросить некого: беру все машины" >&2
        mapfile -t PICKED <<< "$names"
        return
    fi

    {
        echo ""
        echo "Машины в реестре:"
        printf '%s\n' "$SERVERS" | nl -w4 -s') ' | awk '{printf "  %s\n", $0}'
        [ "$mode" = "all" ] && echo "     a) все по очереди"
    } >&2

    while true; do
        if [ "$mode" = "all" ]; then
            read -rp "Куда? (номер или a) " pick
        else
            read -rp "Какая машина? (номер) " pick
        fi
        # Кириллическая «а» тоже принимается: на русском её нажмут обязательно.
        case "$pick" in
            a|A|all|все|а|А)
                if [ "$mode" = "all" ]; then mapfile -t PICKED <<< "$names"; return; fi
                echo "  Эта команда работает с одной машиной. Нужен номер." >&2
                ;;
            ''|*[!0-9]*)
                echo "  Нужен номер из списка." >&2
                ;;
            0)
                echo "  Номера начинаются с единицы." >&2
                ;;
            *)
                local one
                one="$(printf '%s\n' "$names" | sed -n "${pick}p")"
                if [ -n "$one" ]; then PICKED=("$one"); return; fi
                echo "  Нет машины с номером ${pick}." >&2
                ;;
        esac
    done
}

# --- Отпечаток ключа ---------------------------------------------------------

# Ключи машины по адресу, с повторами: сразу после входа в частную сеть
# маршрут готов не мгновенно, и первый запрос возвращает пустоту. Один прогон
# в CI на этом упал — сервер был жив, а команда сказала «не отвечает».
host_keys_at() {
    local addr="$1" out attempt
    for attempt in 1 2 3 4 5 6; do
        out="$(ssh-keyscan "$addr" 2>/dev/null)"
        if [ -n "$out" ]; then printf '%s\n' "$out"; return 0; fi
        [ "$attempt" -lt 6 ] && sleep 5
    done
    return 1
}

# Убедиться, что машина — та самая, и запомнить её ключ.
#
# Сравниваем отпечаток с записанным в servers.yml. Сравнивает машина, а не
# уставший человек: вопрос «Совпадает? [y/N]» через полгода жмут не глядя.
ensure_known_host() {
    local name="$1" addr="$2" scan pinned actual actual_all

    # Раньше здесь стоял ранний выход: адрес уже в known_hosts — и сверки
    # с реестром не происходило вовсе. Это отменяло всю защиту после первого
    # же подключения, а `make trust` отменял её нарочно: он кладёт в
    # known_hosts новый ключ пересозданной машины, реестр при этом хранит
    # отпечаток старой, и разойтись они могли молча и навсегда.
    #
    # Теперь ранний выход применяется только там, где сверять НЕЧЕГО:
    # отпечатка в реестре нет. Есть — сверяем каждый раз, это дёшево.
    pinned="$(server_fingerprint "$name")"
    if [ -z "$pinned" ] && ssh-keygen -F "$addr" -f "$KNOWN_HOSTS" >/dev/null 2>&1; then
        return 0
    fi

    scan="$(host_keys_at "$addr" || true)"
    # Свежая машина в частной сети ещё НЕ состоит: заводит её туда роль
    # tailscale, и происходит это внутри первого же `apply`. Значит первый
    # прогон всегда идёт по публичному адресу и публичному порту 22 —
    # другого пути к новорождённой машине не существует.
    #
    # Отсюда и порядок в site.yml: tailscale раньше firewall. Закрыть 22
    # можно только после того, как запасная дверь открыта и проверена.
    [ -n "$scan" ] || die "Машина ${name} (${addr}) не отвечает на порту 22
  (пробовал полминуты). Если идём через частную сеть — на месте ли машина
  в ней."

    actual_all="$(printf '%s\n' "$scan" | ssh-keygen -lf - 2>/dev/null \
        | awk '$4 == "(ED25519)" {print $2}' | head -1)"

    if [ -z "$pinned" ]; then
        # Отпечатка в реестре нет — значит машину видим впервые.
        #
        # Взять его заранее неоткуда: блок с отпечатками провайдер печатает
        # при первой загрузке, и к моменту, когда откроешь консоль, он уже
        # улетел вверх, а промотать её нечем. Войти в консоль тоже нельзя:
        # пароля root ещё нет, его ставит эта самая настройка.
        #
        # Поэтому первое подключение — с явного разрешения. Оно должно быть
        # именно явным: молча принимать чужой ключ команда не станет никогда.
        [ "${VPS_DEV_TRUST_NEW_HOST:-}" = "1" ] || die "Машину ${name} вижу впервые, а отпечатка её ключа в servers.yml нет.
  Она показывает:
    ${actual_all}

  Если это твоя только что созданная машина — впиши строку в её блок
  в servers.yml и повтори:
    dev_host_fingerprint: \"${actual_all}\"

  Либо разреши разовое доверие: в GitHub отметь «первое подключение»,
  локально — VPS_DEV_TRUST_NEW_HOST=1 make apply h=${name}"

        say "${name}: первое подключение, принимаю ключ ${actual_all}"
        echo ""
        echo "  ВПИШИ ЭТО В servers.yml, в блок машины ${name}:"
        echo ""
        echo "          dev_host_fingerprint: \"${actual_all}\""
        echo ""
        echo "  Дальше подлинность будет проверяться по нему, и разрешение"
        echo "  больше не понадобится."
        printf '%s\n' "$scan" >> "$KNOWN_HOSTS"
        sort -u "$KNOWN_HOSTS" -o "$KNOWN_HOSTS"
        return 0
    fi

    actual="$(printf '%s\n' "$scan" | ssh-keygen -lf - 2>/dev/null | awk '{print $2}')"
    if ! printf '%s\n' "$actual" | grep -qxF "$pinned"; then
        die "Машина ${name} (${addr}) показывает НЕ ТОТ ключ, что записан в servers.yml.
  Записан:  ${pinned}
  Показала: $(printf '%s' "$actual" | tr '\n' ' ')
  Либо машину пересоздали — тогда обнови отпечаток из веб-консоли провайдера,
  либо между тобой и ней кто-то встал."
    fi

    printf '%s\n' "$scan" | ssh-keygen -H -f /dev/stdin >/dev/null 2>&1 || true
    ssh-keyscan -H "$addr" 2>/dev/null >> "$KNOWN_HOSTS"
    sort -u "$KNOWN_HOSTS" -o "$KNOWN_HOSTS"
}

# --- Под кем заходить --------------------------------------------------------
#
# На настроенной машине есть пользователь dev, на свежей его ещё нет.
# Проверяем обычным ssh, а не гадаем.
#
# Различаем ТРИ исхода, а не два. Раньше любой сбой — переполненный ssh-agent,
# сетевой всплеск, таймаут — выглядел как «машина свежая», и на боевом сервере
# это приводило к попытке зайти под root, вход которому закрыт.
#
# Печатает флаг для ansible-playbook: пусто — идём под пользователем из
# реестра. Именно -e и именно dev_bootstrap_user, а не ansible_user:
# переменная из инвентаря сильнее -u, а extra-var ansible_user была бы
# сильнее set_fact, которым роль base переключается на dev посреди
# прогона (см. servers.yml, ansible_user).
connect_flags() {
    local name="$1" addr="$2"
    require_ssh_key
    if ssh -o BatchMode=yes -o ConnectTimeout=10 \
           -o IdentitiesOnly=yes -o PreferredAuthentications=publickey \
           -o UserKnownHostsFile="$KNOWN_HOSTS" \
           -i "$SSH_KEY" "dev@${addr}" true >/dev/null 2>&1; then
        say "${name}: настроена, иду под dev" >&2
        return 0
    fi

    if ssh -o BatchMode=yes -o ConnectTimeout=10 \
           -o IdentitiesOnly=yes -o PreferredAuthentications=publickey \
           -o UserKnownHostsFile="$KNOWN_HOSTS" \
           -i "$SSH_KEY" "root@${addr}" true >/dev/null 2>&1; then
        say "${name}: пользователя dev ещё нет, иду под root" >&2
        printf '%s' "-e dev_bootstrap_user=root"
        return 0
    fi

    die "Машина ${name} (${addr}) не пускает ни под dev, ни под root.
  Машина настроена, а dev не отвечает — это НЕ повод считать её свежей.
  Проверь: сеть, брандмауэр провайдера, ключ ${SSH_KEY}."
}

# Ключ определяем в конце: к этому месту все функции уже объявлены.
resolve_ssh_key
