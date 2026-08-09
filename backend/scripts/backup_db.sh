#!/bin/bash
# ─── SignalMar — Backup quotidien MongoDB ────────────────────────────────
# Dump horodaté de la base dans /app/backups, compressé en .tar.gz.
# Rotation : conserve les 7 sauvegardes les plus récentes.
# Planifié via /etc/cron.d/signalmar-backup (03h00 UTC quotidien).
# Restauration :
#   tar xzf mongo_YYYYMMDD_HHMM.tar.gz
#   mongorestore --uri mongodb://localhost:27017 --db test_database --drop mongo_YYYYMMDD_HHMM/test_database
set -u

BACKUP_DIR="/app/backups"
LOG="$BACKUP_DIR/backup.log"
KEEP=7

# Charge MONGO_URL / DB_NAME depuis le .env backend (valeurs entre guillemets)
MONGO_URL=$(grep -oP '^MONGO_URL="?\K[^"]+' /app/backend/.env)
DB_NAME=$(grep -oP '^DB_NAME="?\K[^"]+' /app/backend/.env)

mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y%m%d_%H%M)
NAME="mongo_${STAMP}"

echo "[$(date -u '+%F %T')] backup start → $NAME (db=$DB_NAME)" >> "$LOG"

if mongodump --uri="$MONGO_URL" --db="$DB_NAME" --out="$BACKUP_DIR/$NAME" >> "$LOG" 2>&1; then
  tar czf "$BACKUP_DIR/$NAME.tar.gz" -C "$BACKUP_DIR" "$NAME" && rm -rf "$BACKUP_DIR/$NAME"
  SIZE=$(du -h "$BACKUP_DIR/$NAME.tar.gz" | cut -f1)
  echo "[$(date -u '+%F %T')] backup OK → $NAME.tar.gz ($SIZE)" >> "$LOG"
else
  echo "[$(date -u '+%F %T')] backup FAILED (mongodump error)" >> "$LOG"
  rm -rf "$BACKUP_DIR/$NAME"
  exit 1
fi

# Rotation : supprime les archives au-delà des $KEEP plus récentes
ls -1t "$BACKUP_DIR"/mongo_*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
  rm -f "$old"
  echo "[$(date -u '+%F %T')] rotation: supprimé $(basename "$old")" >> "$LOG"
done
