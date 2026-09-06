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
  tar czf "$DEST/aoe-config-$STAMP.tgz" -C "$CONFIG_DIR" agent-of-empires
  echo "настройки aoe: $DEST/aoe-config-$STAMP.tgz"
fi

find "$DEST" -type f -mtime "+$KEEP_DAYS" -delete
