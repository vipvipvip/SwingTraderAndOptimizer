#!/bin/bash
# PostgreSQL automatic backup script (Docker-based)
# Full database backup with automatic rotation (keep last 7 days)

set -euo pipefail

# Configuration
BACKUP_DIR="/home/dikesh/data/backups/postgres"
BACKUP_USER="swingtrader"
BACKUP_DB="swingtrader"
DOCKER_CONTAINER="swingtrader-db"
RETENTION_DAYS=7
TIMESTAMP=$(date '+%Y-%m-%d_%H-%M-%S')
BACKUP_FILE="$BACKUP_DIR/swingtrader_$TIMESTAMP.sql.gz"

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Log file
LOG_FILE="$BACKUP_DIR/backup.log"

log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log_message "=== PostgreSQL Backup Started ==="
log_message "Backup file: $BACKUP_FILE"

# Check if Docker container is running
if ! docker ps | grep -q "$DOCKER_CONTAINER"; then
    log_message "ERROR: Docker container '$DOCKER_CONTAINER' is not running."
    exit 1
fi

log_message "Docker container is running"

# Check if PostgreSQL is accessible via Docker
if ! docker exec "$DOCKER_CONTAINER" psql -U "$BACKUP_USER" -d "$BACKUP_DB" -c "SELECT 1" > /dev/null 2>&1; then
    log_message "ERROR: Cannot connect to PostgreSQL in Docker container."
    exit 1
fi

log_message "Connected to PostgreSQL successfully"

# Perform backup via Docker
if docker exec "$DOCKER_CONTAINER" pg_dump -U "$BACKUP_USER" -d "$BACKUP_DB" 2>> "$LOG_FILE" | gzip > "$BACKUP_FILE"; then
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    log_message "✓ Backup completed successfully (Size: $BACKUP_SIZE)"
else
    log_message "✗ Backup failed"
    exit 1
fi

# Cleanup old backups (keep last 7 days)
log_message "Cleaning up backups older than $RETENTION_DAYS days..."
CLEANUP_COUNT=$(find "$BACKUP_DIR" -name "swingtrader_*.sql.gz" -type f -mtime +$RETENTION_DAYS -delete -print | wc -l)
log_message "✓ Deleted $CLEANUP_COUNT old backup file(s)"

# Summary
BACKUP_COUNT=$(find "$BACKUP_DIR" -name "swingtrader_*.sql.gz" -type f | wc -l)
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)
log_message "Backup directory summary: $BACKUP_COUNT backups, $TOTAL_SIZE total size"
log_message "=== PostgreSQL Backup Completed ==="
log_message ""

exit 0
