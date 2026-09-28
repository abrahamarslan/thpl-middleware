#!/usr/bin/env bash
# ==============================================================================
# garage-backup — mirror the media buckets to deployment/backups/garage/
# ==============================================================================
# Usage: ./manage.sh garage-backup     (from deployment/; safe for cron)
#
# Why: one Garage node has replication_factor 1 — no redundancy, the same single
# point of failure as a local disk. Object data is small (avatars) and the S3 API
# is the one interface that never changes, so the backup is a plain mirror through
# it. `sync-backups-gcs.sh` already ships everything under deployment/backups/ to
# GCS nightly, so this lands in the same place as the Postgres dumps.
#
#   ./manage.sh garage-backup && scripts/sync-backups-gcs.sh gs://<bucket>
#
# Restore (fresh Garage): `./manage.sh garage-init`, then copy each directory
# back with the same rclone image (see docs/media-production-rollout.md §9).
#
# The mirror is one-way and DELETES files that Garage no longer has (the 24 h GC),
# but refuses to delete more than half of what it holds in one run, so an empty or
# broken Garage can never wipe the last good copy.
# ==============================================================================

set -euo pipefail

GARAGE="${GARAGE_CONTAINER:-garage}"
RCLONE_IMAGE="${RCLONE_IMAGE:-rclone/rclone:1.68.2}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${GARAGE_BACKUP_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)/backups/garage}"

docker inspect "$GARAGE" >/dev/null 2>&1 || { echo "Container '$GARAGE' not found." >&2; exit 1; }

# Credentials, network and bucket names come from the running containers, exactly
# what the app uses — nothing is read from (or written to) an env file. The image
# is scratch-based, so `docker inspect` rather than `docker exec printenv`.
genv() {
    docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$1" 2>/dev/null | tr -d '\r' | sed -n "s/^$2=//p" | head -1
}
KEY_ID="$(genv "$GARAGE" GARAGE_DEFAULT_ACCESS_KEY)"
SECRET="$(genv "$GARAGE" GARAGE_DEFAULT_SECRET_KEY)"
NETWORK="$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{println $k}}{{end}}' "$GARAGE" | head -1 | tr -d '\r')"
PUBLIC="$(genv backend S3_BUCKET_PUBLIC)"; PUBLIC="${PUBLIC:-core-platform-media-public}"
PRIVATE="$(genv backend S3_BUCKET_PRIVATE)"; PRIVATE="${PRIVATE:-core-platform-media-private}"
[ -n "$KEY_ID" ] && [ -n "$SECRET" ] && [ -n "$NETWORK" ] || {
    echo "Could not read the Garage key/network from the '$GARAGE' container." >&2; exit 1; }

mkdir -p "$DEST"
ts() { date -u +'%Y-%m-%dT%H:%M:%SZ'; }

rclone_g() {   # rclone against Garage as remote "G:", with $DEST mounted at /backup
    # --user: files land owned by the caller (not root), so cron/gcloud and clean-ups work.
    docker run --rm --user "$(id -u):$(id -g)" --network "$NETWORK" -v "$DEST:/backup" \
        -e RCLONE_CONFIG_G_TYPE=s3 -e RCLONE_CONFIG_G_PROVIDER=Other \
        -e "RCLONE_CONFIG_G_ENDPOINT=http://$GARAGE:3900" -e RCLONE_CONFIG_G_REGION=garage \
        -e "RCLONE_CONFIG_G_ACCESS_KEY_ID=$KEY_ID" -e "RCLONE_CONFIG_G_SECRET_ACCESS_KEY=$SECRET" \
        "$RCLONE_IMAGE" "$@"
}

for bucket in "$PUBLIC" "$PRIVATE"; do
    mirror="$DEST/$bucket"
    mkdir -p "$mirror"
    have="$(find "$mirror" -type f | wc -l)"
    remote="$(rclone_g size --json "G:$bucket" 2>/dev/null | sed -n 's/.*"count":\([0-9]*\).*/\1/p')"
    [ -n "$remote" ] || { echo "[$(ts)] ERROR: cannot list $bucket (is Garage up? was garage-init run?)" >&2; exit 1; }

    # An empty or unreachable-looking bucket must never wipe the last good copy.
    if [ "$remote" -eq 0 ] && [ "$have" -gt 0 ]; then
        echo "[$(ts)] REFUSING to sync $bucket: Garage reports 0 objects but the mirror holds $have." >&2
        echo "          If that is really intended, empty $mirror by hand and re-run." >&2
        exit 1
    fi

    echo "[$(ts)] mirroring $bucket ($remote object(s)) -> $mirror"
    # --max-delete: at most half the mirror (+5) may disappear in one run (the 24 h GC
    # removes a few objects a day, never most of them).
    rclone_g sync "G:$bucket" "/backup/$bucket" --max-delete "$(( have / 2 + 5 ))" --stats-one-line -v 2>&1 \
        | grep -vE "^\s*$" | tail -2
done

echo "[$(ts)] done: $(find "$DEST" -type f | wc -l) file(s), $(du -sh "$DEST" | cut -f1) in $DEST"
