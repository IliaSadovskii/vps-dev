#!/usr/bin/env bash
#
# Печатает ключ, которым машина входит в частную сеть Tailscale.
#
# Два источника, по убыванию силы:
#
#   TAILSCALE_AUTHKEY                    готовый ключ. Так удобно на своей
#                                        машине: положил в .env и забыл;
#   TAILSCALE_OAUTH_SERVER_CLIENT_ID     клиент OAuth. Выпускаем свежий ключ
#   TAILSCALE_OAUTH_SERVER_SECRET        на один раз, прямо сейчас.
#
# Второй способ — основной. Причина: готовый ключ живёт максимум 90 дней,
# а нужен он редко — только когда заводишь машину. То есть лежит без дела
# и протухает ровно к моменту, когда понадобился. Клиент OAuth не истекает,
# а выпущенный им ключ одноразовый и живёт десять минут.
#
# Клиент для машин заводится ОТДЕЛЬНО от того, которым в сеть входит сам CI.
# Тогда доступ к выкатке и право вводить машины отзываются независимо,
# и утечка одного не тянет за собой второе.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

ready="$(env_get TAILSCALE_AUTHKEY)"
if [ -n "$ready" ]; then
    printf '%s' "$ready"
    exit 0
fi

client_id="$(env_get TAILSCALE_OAUTH_SERVER_CLIENT_ID)"
client_secret="$(env_get TAILSCALE_OAUTH_SERVER_SECRET)"
if [ -z "$client_id" ] || [ -z "$client_secret" ]; then
    # Пусто — не ошибка: на уже настроенной машине ключ не нужен, она
    # в сети давно. Ошибку скажет сама роль, если ключ понадобится.
    exit 0
fi

# Ответ и код запрашиваем отдельно: с `curl -fsS` в конвейере ошибка приходит
# голым кодом 22, и разбираться, что именно не понравилось Tailscale,
# приходится вслепую. Один прогон в CI на этом и встал.
response="$(curl -sS -w $'\n%{http_code}' -u "${client_id}:${client_secret}" \
    -d 'grant_type=client_credentials' \
    https://api.tailscale.com/api/v2/oauth/token 2>&1 || true)"
code="$(printf '%s' "$response" | tail -1)"
body="$(printf '%s' "$response" | sed '$d')"

if [ "$code" != "200" ]; then
    die "Tailscale не выдал пропуск клиенту OAuth (код ${code}).
  Ответ: ${body}
  Проверь TAILSCALE_OAUTH_SERVER_CLIENT_ID и TAILSCALE_OAUTH_SERVER_SECRET."
fi

token="$(printf '%s' "$body" | jq -r '.access_token // empty')"
[ -n "$token" ] || die "Tailscale ответил без пропуска. Ответ: ${body}"

# Описание — только буквы, цифры и пробелы. Tailscale отвечает 400
# «description had invalid characters» и на кириллицу, и на двоеточие;
# по коду ошибки этого не угадать, видно только из ответа целиком.
#
# reusable: false и срок в десять минут — ключ переживает ровно один прогон.
# preauthorized: true — иначе узел встанет в очередь на ручное подтверждение
# и настройка зависнет, ожидая, пока кто-то нажмёт кнопку в консоли.
# ephemeral: false — сервер должен остаться в сети после настройки.
response="$(curl -sS -w $'\n%{http_code}' -X POST \
    -H "Authorization: Bearer ${token}" \
    -H "Content-Type: application/json" \
    --data '{
      "capabilities": {
        "devices": {
          "create": {
            "reusable": false,
            "ephemeral": false,
            "preauthorized": true,
            "tags": ["tag:server"]
          }
        }
      },
      "expirySeconds": 600,
      "description": "vps-dev deploy"
    }' \
    https://api.tailscale.com/api/v2/tailnet/-/keys 2>&1 || true)"
code="$(printf '%s' "$response" | tail -1)"
body="$(printf '%s' "$response" | sed '$d')"

if [ "$code" != "200" ] && [ "$code" != "201" ]; then
    die "Tailscale не выпустил ключ (код ${code}).
  Ответ: ${body}

  Частые причины:
    - у клиента OAuth нет права auth_keys на запись;
    - у клиента не указана метка tag:server;
    - метка tag:server не объявлена в Access Controls."
fi

key="$(printf '%s' "$body" | jq -r '.key // empty')"
[ -n "$key" ] || die "Tailscale ответил без ключа. Ответ: ${body}"

printf '%s' "$key"
