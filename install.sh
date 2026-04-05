#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

echo ""
echo "=== Research Pipeline Installer ==="
echo ""

# ── 1. Check / install Docker ────────────────────────────────────────────────

if command -v docker &>/dev/null; then
    echo "[1/4] Docker is already installed: $(docker --version)"
else
    echo "[1/4] Docker not found. Installing via get.docker.com ..."
    curl -fsSL https://get.docker.com | sh
    echo "      Adding current user ($USER) to the 'docker' group ..."
    sudo usermod -aG docker "$USER"
    echo ""
    echo "  NOTE: Docker group membership takes effect in a new shell session."
    echo "  If the next step fails with a permissions error, run:"
    echo "    newgrp docker"
    echo "  and then re-run this script."
    echo ""
fi

# ── 2. Prompt for API keys ───────────────────────────────────────────────────

echo "[2/4] Enter API keys (press Enter to leave a key blank — not all are required)."
echo ""

read -sp "  ANTHROPIC_API_KEY : " ANTHROPIC_API_KEY
echo ""
read -sp "  OPENAI_API_KEY    : " OPENAI_API_KEY
echo ""
read -sp "  TAVILY_API_KEY    : " TAVILY_API_KEY
echo ""
echo ""

# ── 3. Write .env file ───────────────────────────────────────────────────────

ENV_FILE="$SCRIPT_DIR/.env"
echo "[3/4] Writing $ENV_FILE ..."

cat > "$ENV_FILE" <<EOF
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
OPENAI_API_KEY=${OPENAI_API_KEY}
TAVILY_API_KEY=${TAVILY_API_KEY}
EOF

echo "      Done."
echo ""

# ── 4. Build and start the app ───────────────────────────────────────────────

echo "[4/4] Running: docker compose up --build -d"
cd "$SCRIPT_DIR"
docker compose up --build -d
echo "      Containers started."
echo ""

# ── Print access URL ─────────────────────────────────────────────────────────

# Try to find the first non-loopback IPv4 address
LOCAL_IP=$(ip -4 addr show scope global | awk '/inet / {print $2}' | cut -d/ -f1 | head -n1 || true)
if [ -z "$LOCAL_IP" ]; then
    LOCAL_IP="<your-pi-ip>"
fi

echo "=========================================="
echo "  App is running!"
echo ""
echo "  Local:   http://localhost:8080"
echo "  Network: http://${LOCAL_IP}:8080"
echo "=========================================="
echo ""
