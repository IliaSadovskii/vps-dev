#!/usr/bin/env bash
#
# Применить настройку или показать, что изменится.
#
#   run-playbook.sh [--check] [--host ИМЯ] [--tags ТЕГИ]
#
# Машины обходятся по очереди, а не все сразу: под каким пользователем
# заходить, решается для каждой отдельно.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

CHECK=""
WANTED=""
TAGS=""
while [ $# -gt 0 ]; do
    case "$1" in
        --check) CHECK="--check --diff"; shift ;;
        --host)  WANTED="${2:-}"; shift 2 ;;
        --tags)  TAGS="${2:-}"; shift 2 ;;
        *) die "Неизвестный аргумент: $1" ;;
    esac
done

load_servers

# Меняющая команда не должна применяться ко всем по нажатию Enter,
# поэтому «все машины» предлагается только сухому прогону.
MODE="one"
[ -n "$CHECK" ] && MODE="all"
pick_targets "$WANTED" "$MODE"
TARGETS=("${PICKED[@]}")

# Прерывание посреди обхода оставляет машину в промежуточном состоянии.
# Лечится повторным запуском — надо только сказать об этом вслух.
CURRENT=""
trap 'echo ""; echo "⚠ Прервано на ${CURRENT:-неизвестной машине}. Состояние не гарантировано."; echo "  Повтори: make apply h=${CURRENT}"; exit 130' INT

DONE=()
FAILED=()

# Тело выполняется в отдельной оболочке — скобки, а не фигурные. Так выход
# по ошибке (недоступная машина, неподтверждённый отпечаток) прекращает
# работу только с этой машиной, а обход продолжается. Иначе первая же
# упавшая машина обрывала цикл, и про остальные не было сказано ничего.
run_one() (
    local name="$1" addr as state
    addr="$(server_address "$name")"
    echo ""
    echo "══════ ${name} (${addr}) ══════"
    ensure_known_host "$name" "$addr"
    as="$(connect_flags "$name" "$addr")"
    # Пустой флаг означает «зашли под dev», то есть машина уже настроена
    # и пароль root у неё есть. Непустой — идём под root, машина свежая.
    if [ -n "$as" ]; then state="fresh"; else state="known"; fi
    ensure_machine_secrets "$name" "$state"
    export ANSIBLE_TARGET_MACHINE="$name"

    # Здесь была ещё строка, заводящая для машины отдельный адрес проверки
    # healthchecks.io (healthcheck-url.sh). В этом проекте вместо неё —
    # ntfy: адрес фиксированный, ключ VPS_DEV_NTFY_TOPIC уже в SECRETS
    # и никакого запроса к внешнему API заводить не нужно.

    # Машина уже в частной сети — вводить её туда не надо. Роль Tailscale
    # тогда пропускается целиком (см. ansible/site.yml): ключ ей нужен
    # безусловно, а выпускать новый на каждом прогоне значит каждый раз
    # переподключать машину к сети и терять обещание changed=0.
    #
    # Ключ здесь не выпускается на один прогон через OAuth, как у боевого
    # сервера (см. lib.sh — TAILSCALE_AUTHKEY входит в SECRETS и приходит
    # готовым из окружения или .env): держать отдельного клиента OAuth ради
    # одной машины разработки избыточно, а сам ключ, в отличие от боевого,
    # не обязан жить одноразово — не жалко, если утечёт длиннее живущий.
    local in_tailnet="false"
    if [ -n "$(discover_tailnet_address "$name")" ]; then
        in_tailnet="true"
        export OVERRIDE_TAILSCALE_AUTHKEY=""
    fi
    # Адрес передаём явно: он найден в частной сети по имени машины,
    # а в реестре записан только публичный.
    # shellcheck disable=SC2086  # флаги должны разбиться на слова
    ansible_run ansible-playbook site.yml --limit "$name" \
        -e ansible_host="$addr" -e dev_in_tailnet="$in_tailnet" \
        $CHECK $as ${TAGS:+--tags "$TAGS"}
)

for name in "${TARGETS[@]}"; do
    CURRENT="$name"
    if run_one "$name"; then
        DONE+=("$name")
    else
        FAILED+=("$name")
        [ "${#TARGETS[@]}" -gt 1 ] && echo "  (иду к следующей машине)"
    fi
done
trap - INT

# Сводка нужна, когда машин больше одной: иначе про упавшую посередине
# узнаёшь только по отсутствию её заголовка в выводе.
if [ "${#TARGETS[@]}" -gt 1 ]; then
    echo ""
    echo "══════ Итог ══════"
    [ "${#DONE[@]}"   -gt 0 ] && echo "  получилось: ${DONE[*]}"
    [ "${#FAILED[@]}" -gt 0 ] && echo "  не вышло:   ${FAILED[*]}"
fi

[ "${#FAILED[@]}" -eq 0 ] || exit 1
