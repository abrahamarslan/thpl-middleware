#!/usr/bin/env bash
# ==============================================================================
# garage-init — one-time (and safe to re-run) Garage bootstrap for media storage
# ==============================================================================
# Usage: ./manage.sh garage-init          (run from deployment/)
#
# What it does — the whole provisioning story, so the application never has to:
#   1. waits for the `garage` container to answer
#   2. creates the PUBLIC and PRIVATE media buckets if they do not exist
#   3. grants the app's access key read+write on both
#   4. REMOVES the key's permission to create buckets, so a bug (or a compromised
#      app) can never mint a bucket that has none of the intended policy
#
# What it deliberately does NOT do:
#   * layout — `garage server --single-node` (docker-compose.yml) assigns it;
#   * key creation — `--default-access-key` creates the key from
#     GARAGE_DEFAULT_ACCESS_KEY / GARAGE_DEFAULT_SECRET_KEY on first boot, so the
#     credentials are yours (from .env), never scraped from command output.
#
# The backend verifies (HeadBucket) both buckets at startup and refuses to boot
# with MEDIA_STORAGE_DRIVER=garage if either is missing: verify, never provision.
#
# Idempotent: `bucket create` is not, so existence is checked first; `bucket
# allow` and `key deny` are.
# ==============================================================================

set -euo pipefail

GARAGE="${GARAGE_CONTAINER:-garage}"

# Values come from the environment, else from the env file the stack runs with
# (.env.prod first, like manage.sh's prod_compose). Read with grep — never `source`
# a .env (a dirty one breaks the shell; see `manage.sh env-check`).
env_file=""
for f in .env.prod .env; do [ -f "$f" ] && { env_file="$f"; break; }; done

env_val() {
    [ -n "$env_file" ] || return 0
    grep -E "^$1=" "$env_file" | tail -1 | cut -d= -f2- | sed -e "s/^['\"]//" -e "s/['\"]\$//" || true
}

PUBLIC_BUCKET="${S3_BUCKET_PUBLIC:-$(env_val S3_BUCKET_PUBLIC)}"
PUBLIC_BUCKET="${PUBLIC_BUCKET:-core-platform-media-public}"
PRIVATE_BUCKET="${S3_BUCKET_PRIVATE:-$(env_val S3_BUCKET_PRIVATE)}"
PRIVATE_BUCKET="${PRIVATE_BUCKET:-core-platform-media-private}"

if [ "$PUBLIC_BUCKET" = "$PRIVATE_BUCKET" ]; then
    echo "S3_BUCKET_PUBLIC and S3_BUCKET_PRIVATE must be different buckets (both are '$PUBLIC_BUCKET')." >&2
    exit 1
fi

if ! docker inspect "$GARAGE" >/dev/null 2>&1; then
    echo "Container '$GARAGE' not found. Start the stack first (./manage.sh start | dev | prod)." >&2
    exit 1
fi

g() { docker exec "$GARAGE" /garage "$@"; }

# Run a mutating command; on failure show WHY (Garage logs its cluster chatter to stderr,
# which is dropped from the success path but must never hide an error).
run() {
    local out
    if ! out="$("$@" 2>&1)"; then
        echo "FAILED: $*" >&2
        printf '%s\n' "$out" | grep -v "netapp" >&2 || true
        exit 1
    fi
}

# The key Garage itself created on first boot — asking the container is exact;
# re-deriving it from .env could disagree with what the running server holds.
# `docker inspect`, not `docker exec printenv`: the Garage image is scratch-based
# (just /garage), so there is no shell or printenv inside it. tr strips the CR a
# Windows docker.exe appends.
KEY_ID="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$GARAGE" 2>/dev/null \
    | tr -d '\r' | sed -n 's/^GARAGE_DEFAULT_ACCESS_KEY=//p' | head -1)"
if [ -z "$KEY_ID" ]; then
    echo "The garage container has no GARAGE_DEFAULT_ACCESS_KEY, so no default key was created." >&2
    echo "Set GARAGE_DEFAULT_ACCESS_KEY / GARAGE_DEFAULT_SECRET_KEY in .env and recreate it:" >&2
    echo "  docker compose up -d --force-recreate garage" >&2
    exit 1
fi
case "$KEY_ID" in
    GK*) ;;
    *) echo "GARAGE_DEFAULT_ACCESS_KEY must look like GK<hex> (got '$KEY_ID')." >&2; exit 1 ;;
esac

echo "Waiting for Garage..."
for _ in $(seq 1 60); do
    if g status >/dev/null 2>&1; then ready=1; break; fi
    sleep 2
done
if [ "${ready:-0}" != "1" ]; then
    echo "Garage did not become ready within 2 minutes. Check: docker logs $GARAGE" >&2
    exit 1
fi

for bucket in "$PUBLIC_BUCKET" "$PRIVATE_BUCKET"; do
    if g bucket info "$bucket" >/dev/null 2>&1; then
        echo "  bucket $bucket: exists"
    else
        run g bucket create "$bucket"
        echo "  bucket $bucket: created"
    fi
    run g bucket allow --read --write "$bucket" --key "$KEY_ID"
    echo "  bucket $bucket: read+write granted to $KEY_ID"
done

run g key deny --create-bucket "$KEY_ID"
echo "  key $KEY_ID: bucket creation denied"

echo
g key info "$KEY_ID" 2>/dev/null | sed -n '/Can create buckets/,$p'
echo
echo "Done. The backend reads these (docker-compose.yml passes them through):"
echo "  MEDIA_STORAGE_DRIVER=garage     # for NEW uploads; existing media keep their own disk"
echo "  S3_BUCKET_PUBLIC=$PUBLIC_BUCKET"
echo "  S3_BUCKET_PRIVATE=$PRIVATE_BUCKET"
echo "  S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY  default to GARAGE_DEFAULT_ACCESS_KEY / _SECRET_KEY"
