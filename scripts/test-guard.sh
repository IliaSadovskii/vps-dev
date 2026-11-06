#!/usr/bin/env bash
# Примеры решений сторожа guard-destructive-db: код выхода, папка, команда.
# Сторож держится на регулярных выражениях, и правка легко откроет лишнее.
set -euo pipefail

guard="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/ansible/roles/style/files/guard-destructive-db"
crm=/projects/listate-crm
lane=/projects/.stands/listate-crm-b
other=/projects/vps-dev
bad=0

check() {
    local want=$1 cwd=$2 cmd=$3 got=0
    jq -n --arg cwd "$cwd" --arg cmd "$cmd" '{cwd: $cwd, tool_input: {command: $cmd}}' \
        | "$guard" >/dev/null 2>&1 || got=$?
    if [ "$got" != "$want" ]; then
        echo "  ✖ ждали $want, вышло $got: ($cwd) $cmd"
        bad=1
    fi
}

# Тестовые базы CRM
check 0 "$other" "docker exec listate-postgres-1 psql -U listate -d listate_owner -c 'DROP DATABASE bench'"
check 0 "$other" "docker exec listate-b-postgres-1 psql -U listate -c 'drop database if exists \"listate_test_x\" with (force);'"
check 0 "$other" "docker exec -i listate-b-postgres-1 dropdb -U listate --if-exists listate_volume"
check 0 "$crm" "docker compose exec -T postgres dropdb -U listate listate_test_server_test_1_agency_ab12"
check 0 "$lane" "docker compose exec postgres psql -U listate -c \"drop database agency_0123456789abcdef0123456789abcdef\""
check 0 "$crm" "make clean-test"
check 0 "$other" "ls"

# Базы, на которые настроено окружение папки
check 2 "$crm" "docker compose exec postgres psql -U listate -c 'DROP DATABASE listate_owner'"
check 2 "$crm" "docker compose exec postgres psql -U listate -c 'DROP DATABASE \"listate\"'"
check 2 "$crm" "docker compose exec postgres psql -U listate -c \"DROP DATABASE \\\"listate\\\"\""
check 2 "$crm" "docker compose exec postgres dropdb listate"
check 2 "$other" "docker exec listate-postgres-1 dropdb -U listate listate_owner"
check 2 "$crm" "D=listate; docker compose exec postgres psql -c \"drop database \$D\""

# Что ещё стирает, кроме удаления базы
check 2 "$other" "docker exec listate-postgres-1 psql -U listate -d listate_owner -c 'TRUNCATE users'"
check 2 "$crm" "docker compose exec postgres psql -d listate -c 'DROP OWNED BY listate'"

# Контур и платформа
check 2 "$other" "docker exec listate-contour-crm-postgres-1 psql -U postgres -c 'DROP DATABASE listate_test'"
check 2 "$other" "docker exec listate-contour-crm-postgres-1 sh -c \"dropdb -U x agency1\""
check 2 "$crm" "dropdb -h 127.0.0.1 -p 8106 -U postgres listate_test"
check 2 "/projects/listate-platform" "make contour-psql db=server <<< 'DROP DATABASE server'"
check 2 "$crm" "docker exec listate-platform-postgres-1 psql -c 'DROP DATABASE listate_test'"
check 2 "$crm" "cd /projects/listate-platform && docker compose exec postgres dropdb bench"
check 2 "$crm" "ports run listate-platform -- docker compose -p listate-contour down -v"

# Чужие проекты и удалённые машины
check 2 "$crm" "docker exec mz-pg psql -c 'drop database x'"
check 2 "$crm" "cd ../realest && docker compose exec db dropdb x"
check 2 "/projects/realest" "docker compose exec postgres dropdb listate_test"
check 2 "$crm" "ssh prod docker exec listate-postgres-1 dropdb listate_test"
check 2 "$crm" "DOCKER_HOST=ssh://x docker exec listate-postgres-1 dropdb listate_test"
check 2 "$crm" "PGHOST=10.0.0.1 psql -c 'drop database listate_test'"
check 2 "$crm" "psql postgres://u@h/d -c 'drop database listate_test'"

# Склейка: разрешённая часть не открывает соседнюю
check 2 "$other" "docker exec listate-postgres-1 dropdb bench; docker exec mz-pg dropdb y"
check 2 "$other" "docker exec listate-postgres-1 dropdb bench
dropdb other"
check 2 "$crm" "psql -c 'drop
database x'"

# Прежние запреты
check 2 "$crm" "php artisan migrate:fresh"
check 2 "$crm" "php artisan config:cache"
check 2 "$crm" "make fresh"
check 2 "$crm" "docker volume rm x"
check 2 "$crm" "docker compose down -v"
check 0 "$other" "ports run stand -- docker compose down -v"

[ "$bad" -eq 0 ] || exit 1
echo "  ✔ сторож баз: примеры сходятся"
