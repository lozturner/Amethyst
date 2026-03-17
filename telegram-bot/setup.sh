#!/usr/bin/env bash
# ===========================================================================
# setup.sh — One-command bot setup + launch
# ===========================================================================
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh
#
# What it does:
#   1. Checks Python 3 is installed
#   2. Installs pip dependencies
#   3. Checks .env has a real token (not the placeholder)
#   4. Kills any existing bot process so there's no conflict
#   5. Launches the bot via run.sh (with auto-reboot)
#
# ===========================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================"
echo "  Bot Setup"
echo "============================================"
echo ""

# --- Step 1: Check Python 3 ---
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found."
    echo ""
    echo "Install Python 3:"
    echo "  macOS:   brew install python3"
    echo "  Ubuntu:  sudo apt install python3 python3-pip"
    echo "  Windows: https://python.org/downloads"
    exit 1
fi
echo "[OK] Python 3 found: $(python3 --version)"

# --- Step 2: Install dependencies ---
echo ""
echo "Installing dependencies..."
pip3 install -r requirements.txt --quiet
echo "[OK] Dependencies installed"

# --- Step 3: Check .env ---
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo ""
        echo "Created .env from .env.example"
        echo "IMPORTANT: Edit .env and paste your bot token from @BotFather"
        echo ""
        echo "Steps to get a token:"
        echo "  1. Open Telegram, search for @BotFather"
        echo "  2. Type /newbot and follow the prompts"
        echo "  3. Copy the token (looks like 123456:ABC-DEF...)"
        echo "  4. Paste it in .env as: TELEGRAM_BOT_TOKEN=your-token"
        echo ""
        echo "Then run this script again."
        exit 1
    else
        echo "ERROR: No .env file found and no .env.example to copy from."
        exit 1
    fi
fi

# Check the token isn't the placeholder
TOKEN=$(grep -oP 'TELEGRAM_BOT_TOKEN=\K.*' .env 2>/dev/null || true)
if [ -z "$TOKEN" ] || [ "$TOKEN" = "your-bot-token-here" ]; then
    echo ""
    echo "ERROR: TELEGRAM_BOT_TOKEN is not set in .env"
    echo ""
    echo "Edit .env and paste your bot token from @BotFather:"
    echo "  TELEGRAM_BOT_TOKEN=123456:ABC-DEF..."
    exit 1
fi
echo "[OK] Bot token found in .env"

# --- Step 4: Kill any existing bot process ---
echo ""
echo "Checking for existing bot processes..."
# Kill any running bot.py or relay.py to avoid polling conflicts
EXISTING=$(pgrep -f "python.*bot\.py" 2>/dev/null || true)
if [ -n "$EXISTING" ]; then
    echo "Found existing bot process (PID: $EXISTING) — stopping it..."
    kill $EXISTING 2>/dev/null || true
    sleep 2
fi
EXISTING_RELAY=$(pgrep -f "python.*relay\.py" 2>/dev/null || true)
if [ -n "$EXISTING_RELAY" ]; then
    echo "Found existing relay process (PID: $EXISTING_RELAY) — stopping it..."
    kill $EXISTING_RELAY 2>/dev/null || true
    sleep 2
fi
echo "[OK] No conflicting processes"

# --- Step 5: Launch ---
echo ""
echo "============================================"
echo "  Launching bot with auto-reboot..."
echo "  Press Ctrl+C to stop"
echo "============================================"
echo ""

chmod +x run.sh
exec ./run.sh
