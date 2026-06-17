#!/bin/bash
# MySQL automatic backup script (Azure MySQL)
# Full database backup with automatic rotation (keep last 7 days)
# Reads DB list from a CSV config file and loops through each entry

set -euo pipefail

# ── Config file (CSV: DB_HOST,DB_PORT,DB_USER,DB_PASSWORD,DB_NAME) ────────────
DB_LIST_FILE="$(dirname "$0")/db-list.csv"

# ── Internal config ────────────────────────────────────────────────────────────
RETENTION_DAYS=7

# ── Validate config file exists ────────────────────────────────────────────────
if [[ ! -f "$DB_LIST_FILE" ]]; then
    echo "ERROR: DB list file not found: $DB_LIST_FILE"
    exit 1
fi

log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# ── Loop through each database entry ──────────────────────────────────────────
while IFS=',' read -r DB_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME; do
    # Skip blank lines and comments
    [[ -z "$DB_HOST" || "$DB_HOST" == \#* ]] && continue

    # Determine backup location based on host
    if [[ "$DB_HOST" == "apptestingmysqlserver.mysql.database.azure.com" ]]; then
        AZURE_STORAGE_BACKUP_DIR="/media/dbbackups/QA/QA_$DB_NAME"
    elif [[ "$DB_HOST" == "surveysaurus-api-mysql-server.mysql.database.azure.com" ]]; then
        AZURE_STORAGE_BACKUP_DIR="/media/dbbackups/PROD/PROD_$DB_NAME"
    else
        echo "ERROR: Unrecognised DB_HOST '$DB_HOST'. Must be a known QA or PROD host. Skipping."
        continue
    fi

    mkdir -p "$AZURE_STORAGE_BACKUP_DIR"

    TIMESTAMP=$(date '+%Y-%m-%d_%H-%M-%S')
    BACKUP_FILE="$AZURE_STORAGE_BACKUP_DIR/${DB_NAME}_$TIMESTAMP.sql.gz"
    LOG_FILE="$AZURE_STORAGE_BACKUP_DIR/backup.log"

    log_message "=== MySQL Backup Started: $DB_NAME @ $DB_HOST ==="
    log_message "Backup file: $BACKUP_FILE"

    # Check if Azure MySQL is reachable
    if ! mysqladmin -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" ping --silent > /dev/null 2>&1; then
        log_message "ERROR: Cannot connect to Azure MySQL at $DB_HOST. Skipping."
        continue
    fi

    log_message "Connected to Azure MySQL successfully"

    # Perform backup
    if mysqldump -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" \
        --single-transaction --routines --triggers --ssl-mode=REQUIRED \
        "$DB_NAME" 2>> "$LOG_FILE" | gzip > "$BACKUP_FILE"; then
        BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
        log_message "✓ Backup completed successfully (Size: $BACKUP_SIZE)"
    else
        log_message "✗ Backup failed for $DB_NAME"
        continue
    fi

    # Cleanup old backups
    log_message "Cleaning up backups older than $RETENTION_DAYS days..."
    CLEANUP_COUNT=$(find "$AZURE_STORAGE_BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -type f -mtime +$RETENTION_DAYS -delete -print | wc -l)
    log_message "✓ Deleted $CLEANUP_COUNT old backup file(s)"

    # Summary
    BACKUP_COUNT=$(find "$AZURE_STORAGE_BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -type f | wc -l)
    TOTAL_SIZE=$(du -sh "$AZURE_STORAGE_BACKUP_DIR" | cut -f1)
    log_message "Backup directory summary: $BACKUP_COUNT backups, $TOTAL_SIZE total size"
    log_message "=== MySQL Backup Completed: $DB_NAME ==="
    log_message ""

done < "$DB_LIST_FILE"

exit 0
