#!/usr/bin/env bash
# ==============================================================================
# sync-env.sh — keep environment variables consistent between the two .env files
# ==============================================================================
# Two .env files must stay in sync:
#   apps/core-platform/backend/.env      used when running the backend directly
#                                        on the host (uvicorn), read by conf.py
#   apps/core-platform/deployment/.env   source for Docker Compose; the running
#                                        container reads THIS one
#
# SOURCE OF TRUTH (configurable):
#   --from backend      backend/.env is canonical  -> apply to deployment/.env  (DEFAULT)
#   --from docker       deployment/.env is canonical -> apply to backend/.env
#   --from deployment   alias for 'docker'
#
# BY DEFAULT this is a DRY-RUN that prints a drift report and exits.
# Pass --apply to write (or -y to skip the confirmation prompt).
#
# SCOPE (which keys to sync):
#   --zoho             (default) every ZOHO_* key in the source; also adds
#                      source-only ZOHO_* keys into the target (--no-add to skip)
#   --shared           every key present in BOTH files (intersection), minus a
#                      small guardlist (CORS_ORIGINS, ENVIRONMENT, DEBUG, TZ)
#                      whose values are intentionally per-environment
#   -k/--keys 'A B C'  an explicit list of keys to sync
#   --prune            (zoho mode) also remove target ZOHO_* keys absent from source
#
# OTHER:
#   -n / --dry-run     print plan, write nothing (default)
#   --diff             show a unified diff of the would-be change
#   --json             machine-readable plan
#   --recreate         after applying, `docker compose up -d backend`
#   -y / --yes         skip confirmation
#
# EXAMPLES:
#   ./scripts/sync-env.sh                                  # dry-run report (src=backend)
#   ./scripts/sync-env.sh --apply                          # write backend -> deployment
#   ./scripts/sync-env.sh --from docker --diff             # show docker -> backend plan
#   ./scripts/sync-env.sh --keys 'ZOHO_CLIENT_ID ZOHO_CLIENT_SECRET' --apply
#   ./scripts/sync-env.sh --zoho --prune --apply --recreate
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_ENV="$DEPLOY_DIR/../backend/.env"
DEPLOY_ENV="$DEPLOY_DIR/.env"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

SRC="backend"; MODE="zoho"; KEYS=""
EXCLUDE="CORS_ORIGINS CORS_CREDENTIALS ENVIRONMENT DEBUG TZ"
APPLY=false; PRUNE=false; ADD_MISSING=true; DIFF=false; JSON=false; RECREATE=false; YES=false

KEYRE='^([A-Za-z_][A-Za-z0-9_]*)=(.*)$'

die() { echo -e "${RED}$*${NC}" >&2; exit 1; }

usage() { sed -n '2,41p' "$0"; exit 0; }

# --- CLI ---------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --from) SRC="$2"; shift 2 ;;
        --zoho) MODE="zoho"; shift ;;
        --shared) MODE="shared"; shift ;;
        -k|--keys) MODE="keys"; KEYS="$2"; shift 2 ;;
        --key) MODE="keys"; KEYS="$KEYS $2"; shift 2 ;;
        --exclude) EXCLUDE="$2"; shift 2 ;;
        --prune) PRUNE=true; shift ;;
        --no-add) ADD_MISSING=false; shift ;;
        --apply) APPLY=true; shift ;;
        -n|--dry-run) APPLY=false; shift ;;
        --diff) DIFF=true; shift ;;
        --json) JSON=true; shift ;;
        --recreate) RECREATE=true; shift ;;
        -y|--yes) YES=true; shift ;;
        -h|--help|help) usage ;;
        *) die "Unknown option: $1" ;;
    esac
done

case "$SRC" in
    backend|backend/.env)  SRC="backend"; TGT="docker"; SRC_FILE="$BACKEND_ENV"; TGT_FILE="$DEPLOY_ENV" ;;
    docker|deployment|deployment/.env) SRC="docker"; TGT="backend"; SRC_FILE="$DEPLOY_ENV"; TGT_FILE="$BACKEND_ENV" ;;
    *) die "Invalid --from: $SRC (expected 'backend' or 'docker')" ;;
esac
[[ -f "$SRC_FILE" ]] || die "Source not found: $SRC_FILE"
[[ -f "$TGT_FILE" ]] || die "Target not found: $TGT_FILE"

# --- Env parsing helpers -------------------------------------------------------
norm() { local v="$1" q; if [[ ${#v} -ge 2 ]]; then q="${v:0:1}"; if [[ "$q" == '"' || "$q" == "'" ]] && [[ "${v: -1}" == "$q" ]]; then printf '%s' "${v:1:${#v}-2}"; return; fi; fi; printf '%s' "$v"; }

# load <file> -> NORM/RAW associative arrays
declare -A NS=() RS=() NT=() RT=()          # source + target
declare -a LT=()                            # target lines (ordered)

load() { # $1=file, $2=norm-ref, $3=raw-ref ; mutations via eval are messy; hardcode below
    local file="$1" line key raw nm
    while IFS= read -r line; do
        if [[ "$line" =~ $KEYRE ]]; then
            key="${BASH_REMATCH[1]}"; raw="${BASH_REMATCH[2]}"; nm="$(norm "$raw")"
            if [[ "$2" == NS ]]; then NS["$key"]="$nm"; RS["$key"]="$raw"; else NT["$key"]="$nm"; RT["$key"]="$raw"; fi
        fi
        [[ "$2" == NT ]] && LT+=("$line")
    done < "$file"
    return 0
}
load "$SRC_FILE" NS
load "$TGT_FILE" NT

# --- Key selection -------------------------------------------------------------
SYNC_KEYS=""; ADD_KEYS=""
build_set() {
    local k
    case "$MODE" in
        zoho)
            for k in "${!NS[@]}"; do
                [[ "$k" == ZOHO_* ]] || continue
                if [[ -n "${NT[$k]+set}" ]]; then SYNC_KEYS="$SYNC_KEYS $k"; else ADD_KEYS="$ADD_KEYS $k"; fi
            done
            ;;
        shared)
            for k in "${!NS[@]}"; do
                [[ -n "${NT[$k]+set}" ]] || continue
                echo "$EXCLUDE" | grep -qw -- "$k" && continue
                SYNC_KEYS="$SYNC_KEYS $k"
            done
            ;;
        keys)
            for k in $KEYS; do
                [[ -n "${NS[$k]:-}" ]] || { echo -e "${YELLOW}  warn: '$k' not in source${NC}" >&2; continue; }
                SYNC_KEYS="$SYNC_KEYS $k"
            done
            ;;
    esac
}
build_set
SYNC_KEYS=$(echo $SYNC_KEYS); ADD_KEYS=$(echo $ADD_KEYS)

# --- Plan ---------------------------------------------------------------------
CHANGE_KEYS=""
for k in $SYNC_KEYS; do
    if [[ "${NS[$k]:-}" != "${NT[$k]:-}" ]]; then CHANGE_KEYS="$CHANGE_KEYS $k"; fi
done
PRUNE_KEYS=""
if [[ "$PRUNE" == true ]]; then
    for k in "${!NT[@]}"; do
        [[ "$k" == ZOHO_* ]] || continue
        [[ -n "${NS[$k]+set}" ]] || PRUNE_KEYS="$PRUNE_KEYS $k"
    done
fi

has_changes=false
[[ -n "$CHANGE_KEYS" || -n "$ADD_KEYS" || -n "$PRUNE_KEYS" ]] && has_changes=true

# --- JSON report --------------------------------------------------------------
if [[ "$JSON" == true ]]; then
    python3 - "$SRC" "$TGT" "$CHANGE_KEYS" "$ADD_KEYS" "$PRUNE_KEYS" <<'PY'
import json,sys
print(json.dumps({"source":sys.argv[1],"target":sys.argv[2],
 "updated":sys.argv[3].split(),"added":sys.argv[4].split(),"pruned":sys.argv[5].split()},indent=2))
PY
    exit 0
fi

echo -e "${CYAN}Sync env${NC}   source: ${GREEN}$SRC${NC}  ->  target: ${CYAN}$TGT${NC}"
echo -e "  source file: $SRC_FILE"
echo -e "  target file: $TGT_FILE"
echo ""
if [[ -n "$CHANGE_KEYS" ]]; then
    echo -e "${YELLOW}Values that differ${NC}:"
    for k in $CHANGE_KEYS; do printf '  %-32s %s  ->  %s\n' "$k" "${NT[$k]:-<missing>}" "${NS[$k]}"; done
    echo ""
fi
if [[ -n "$ADD_KEYS" ]]; then
    echo -e "${YELLOW}Keys to ADD to target (source-only):${NC} ${ADD_KEYS}"
    echo ""
fi
if [[ -n "$PRUNE_KEYS" ]]; then
    echo -e "${YELLOW}Keys to REMOVE from target (--prune):${NC} ${PRUNE_KEYS}"
    echo ""
fi
if [[ "$has_changes" == false ]]; then
    echo -e "${GREEN}Already in sync — no changes needed.${NC}"
    exit 0
fi

# --- Render new target content to stdout -------------------------------------
render() {
    declare -A UP=()
    local k line key
    for k in $CHANGE_KEYS; do UP["$k"]=1; done
    declare -A PR=()
    for k in $PRUNE_KEYS; do PR["$k"]=1; done
    for line in "${LT[@]}"; do
        if [[ "$line" =~ $KEYRE ]]; then
            key="${BASH_REMATCH[1]}"
            if [[ -n "${PR[$key]:-}" ]]; then continue; fi
            if [[ -n "${UP[$key]:-}" ]]; then printf '%s\n' "$key=${RS[$key]}"; continue; fi
        fi
        printf '%s\n' "$line"
    done
    if [[ "$ADD_MISSING" == true && -n "$ADD_KEYS" ]]; then
        printf '\n# --- auto-synced from %s (%s) ---\n' "$SRC_FILE" "$(date +%F)"
        for k in $ADD_KEYS; do printf '%s=%s\n' "$k" "${RS[$k]}"; done
    fi
}

# --- Dry-run / diff -----------------------------------------------------------
if [[ "$APPLY" == false ]]; then
    echo -e "${CYAN}Dry-run — pass --apply to write.${NC}"
    if [[ "$DIFF" == true ]]; then
        render > /tmp/sync-env-target.new
        diff -u "$TGT_FILE" /tmp/sync-env-target.new || true
        rm -f /tmp/sync-env-target.new
    fi
    exit 0
fi

# --- Confirm ------------------------------------------------------------------
if [[ "$YES" == false ]]; then
    read -rp "$(echo -e "${YELLOW}Apply changes to $TGT_FILE? [y/N] ${NC}")" ans
    [[ "$ans" == "y" || "$ans" == "Y" ]] || { echo -e "${YELLOW}Aborted.${NC}"; exit 0; }
fi

# --- Write --------------------------------------------------------------------
render > /tmp/sync-env-target.new
mv /tmp/sync-env-target.new "$TGT_FILE"
echo -e "${GREEN}✓ Updated $TGT_FILE${NC}"

if [[ "$RECREATE" == true && "$TGT" == "docker" ]]; then
    echo -e "${CYAN}Recreating backend so the new env takes effect...${NC}"
    (cd "$DEPLOY_DIR" && docker compose -f docker-compose.yml up -d backend)
fi
echo -e "${GREEN}Done.${NC}"
