#!/usr/bin/env bash
# ==============================================================================
# Local TLS Certificate Setup (mkcert)
# ==============================================================================
# Installs mkcert, creates a local CA, and generates dev certificates.
# Supports: Arch Linux (pacman), Debian/Ubuntu (apt), macOS (brew).
#
# Usage: ./scripts/setup-ssl.sh [domain]
#   Default domain: app.local
# ==============================================================================

set -euo pipefail

DOMAIN="${1:-app.local}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERTS_DIR="$SCRIPT_DIR/../config/traefik/certs"

echo "=== Local TLS Certificate Setup (mkcert) ==="

# ── Detect OS and install mkcert ────────────────────────────────────────────
install_mkcert() {
    echo "mkcert not found. Installing..."

    if command -v pacman &>/dev/null; then
        echo "  Detected: Arch Linux"
        sudo pacman -S --noconfirm mkcert nss
    elif command -v apt-get &>/dev/null; then
        echo "  Detected: Debian/Ubuntu"
        sudo apt-get update -qq
        sudo apt-get install -y -qq libnss3-tools
        # Install from Go binary if not in repos
        if ! apt-cache show mkcert &>/dev/null; then
            curl -JLO "https://dl.filippo.io/mkcert/latest?for=linux/amd64"
            chmod +x mkcert-v*-linux-amd64
            sudo mv mkcert-v*-linux-amd64 /usr/local/bin/mkcert
        else
            sudo apt-get install -y -qq mkcert
        fi
    elif command -v brew &>/dev/null; then
        echo "  Detected: macOS (Homebrew)"
        brew install mkcert nss
    else
        echo "ERROR: Unsupported package manager. Install mkcert manually:"
        echo "  https://github.com/FiloSottile/mkcert"
        exit 1
    fi
}

if ! command -v mkcert &>/dev/null; then
    install_mkcert
fi

echo "  mkcert: $(mkcert --version)"

# ── Install local CA ────────────────────────────────────────────────────────
echo ""
echo "Installing local CA (may require sudo)..."
mkcert -install
echo "  Local CA installed."

# ── Create certs directory ──────────────────────────────────────────────────
mkdir -p "$CERTS_DIR"

# ── Generate certificates ───────────────────────────────────────────────────
echo ""
echo "Generating certificates for:"
echo "  - $DOMAIN"
echo "  - *.$DOMAIN"
echo "  - localhost"
echo "  - 127.0.0.1"

pushd "$CERTS_DIR" > /dev/null
mkcert -cert-file local.pem -key-file local-key.pem \
    "$DOMAIN" "*.$DOMAIN" localhost 127.0.0.1 ::1
popd > /dev/null

# ── Verify ──────────────────────────────────────────────────────────────────
if [[ -f "$CERTS_DIR/local.pem" && -f "$CERTS_DIR/local-key.pem" ]]; then
    echo ""
    echo "=== Success! ==="
    echo "  Certificate: $CERTS_DIR/local.pem"
    echo "  Private key: $CERTS_DIR/local-key.pem"
    echo ""
    echo "Add to /etc/hosts (Windows: C:\\Windows\\System32\\drivers\\etc\\hosts):"
    echo "  127.0.0.1  $DOMAIN"
    echo "  127.0.0.1  auth.$DOMAIN"
    echo "  127.0.0.1  ws.$DOMAIN"
    echo "  127.0.0.1  traefik.$DOMAIN"
else
    echo "ERROR: Certificate files were not created."
    exit 1
fi
