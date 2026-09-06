#!/usr/bin/env bash
# Снимок базы задач orch вместе с настройками Agent of Empires.
#
# Порознь они бесполезны: база помнит поток задач, настройки — сессии, в
# которых этот поток жил. Забираются вместе и одной командой, чтобы их
# нельзя было развести по времени.
#
# `sqlite3 .backup`, а не копирование файла: база в режиме WAL, и копия
# файла на ходу может оказаться нецелой.
set -euo pipefail

STATE_DIR="${ORCH_STATE_DIR:-$HOME/.local/share/orch}"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}"
DEST="${ORCH_BACKUP_DIR:-/var/backups/vps-dev/orch}"
KEEP_DAYS="${ORCH_BACKUP_KEEP:-14}"
STAMP="$(date +%F)"

mkdir -p "$DEST"

if [[ -f "$STATE_DIR/orch.db" ]]; then
  sqlite3 "$STATE_DIR/orch.db" ".backup '$DEST/orch-$STAMP.db'"
  echo "база задач: $DEST/orch-$STAMP.db"
else
  echo "база задач не найдена ($STATE_DIR/orch.db) — снимать нечего"
fi

if [[ -d "$CONFIG_DIR/agent-of-empires" ]]; then
  # Живые сокеты воркеров и их журналы в снимок не идут: сокет не
  # архивируется вовсе, а каталог воркеров меняется прямо во время чтения —
  # tar на этом ругается и возвращает ненулевой код, из-за чего страница
  # обновлений сочла бы снимок несостоявшимся и отменила бы обновление.
  # Восстанавливать их всё равно нечего: воркеры поднимаются заново.
  # Каталог адаптеров (360 МБ) тоже не наш: это скачанные бинарники агентов,
  # AoE ставит их себе сам. Без него снимок ~50 МБ вместо ~114, и четырнадцать
  # суток хранения перестают стоить полтора гигабайта.
  tar czf "$DEST/aoe-config-$STAMP.tgz" \
    --warning=no-file-changed \
    --exclude='agent-of-empires/acp-workers' \
    --exclude='agent-of-empires/plugin-workers' \
    --exclude='agent-of-empires/artifacts' \
    --exclude='agent-of-empires/acp-worker/adapters' \
    --exclude='*.sock' \
    -C "$CONFIG_DIR" agent-of-empires || [[ $? -eq 1 ]]
  echo "настройки aoe: $DEST/aoe-config-$STAMP.tgz"
fi

find "$DEST" -type f -mtime "+$KEEP_DAYS" -delete
