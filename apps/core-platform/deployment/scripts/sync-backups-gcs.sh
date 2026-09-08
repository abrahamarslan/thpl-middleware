#!/usr/bin/env bash
# ==============================================================================
# Nightly GCS Backup Sync Script
# ==============================================================================
# Usage: ./sync-backups-gcs.sh [bucket-uri]
#   e.g. ./sync-backups-gcs.sh gs://dlp-prod-backups
#
# Designed to be invoked safely from cron or systemd timer.
# Automatically resolves GCloud path, checks permissions, and uploads.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="$DEPLOY_DIR/backups"

# Find gcloud executable in common Linux paths if not in cron PATH
if ! command -v gcloud &>/dev/null; then
    for p in /usr/bin/gcloud /snap/bin/gcloud /usr/local/bin/gcloud; do
        if [ -x "$p" ]; then
            export PATH="$(dirname "$p"):$PATH"
            break
        fi
    done
fi

if ! command -v gcloud &>/dev/null; then
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] ERROR: gcloud CLI not found in PATH" >&2
    exit 1
fi

# Load bucket from arg, env, or default
BUCKET="${1:-${GCS_BACKUP_BUCKET:-gs://dlp-prod-backups}}"

if [ ! -d "$BACKUP_DIR" ]; then
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] WARNING: Backup directory $BACKUP_DIR does not exist yet. Creating..."
    mkdir -p "$BACKUP_DIR"
fi

TODAY="$(date +%Y-%m-%d)"
TARGET_URI="${BUCKET%/}/${TODAY}/"

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Starting backup sync from $BACKUP_DIR to $TARGET_URI"

# Sync all backup files to the dated destination folder
gcloud storage rsync -r "$BACKUP_DIR" "$TARGET_URI"

echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Backup sync successfully completed."
