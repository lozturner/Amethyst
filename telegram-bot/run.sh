#!/usr/bin/env bash
# ===========================================================================
# run.sh — The Bot Launcher (with auto-reboot)
# ===========================================================================
#
# Why this exists:
#   A Python process can't cleanly restart itself. So instead of trying to
#   be clever inside bot.py, we wrap it in this shell script. When /deploy
#   is triggered from Telegram, the bot writes a flag file and exits.
#   This script sees the exit, checks the flag, and restarts the bot.
#
# How to use:
#   chmod +x run.sh
#   ./run.sh
#
# What it does:
#   1. Starts bot.py
#   2. Waits for it to exit
#   3. If /tmp/tg_reboot_flag exists → it was a /deploy reboot
#      - Logs the new version
#      - Removes the flag
#      - Restarts the bot (back to step 1)
#   4. If no flag → it was a normal exit or crash
#      - Waits 3 seconds and restarts anyway (crash recovery)
#      - Unless you Ctrl+C, which exits the loop cleanly
#
# To stop the bot completely:
#   Ctrl+C (sends SIGINT, the trap catches it and exits)
#
# ===========================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REBOOT_FLAG="/tmp/tg_reboot_flag"
BOT_SCRIPT="$SCRIPT_DIR/bot.py"

# Trap Ctrl+C so the user can cleanly stop the loop
trap 'echo ""; echo "Bot stopped by user."; exit 0' INT TERM

echo "============================================"
echo "  Bot Launcher — auto-reboot enabled"
echo "============================================"

while true; do
    echo ""
    echo "[$(date)] Starting bot..."
    python3 "$BOT_SCRIPT"
    EXIT_CODE=$?

    # Check if this was a deploy-triggered reboot
    if [ -f "$REBOOT_FLAG" ]; then
        NEW_VERSION=$(cat "$REBOOT_FLAG")
        echo "[$(date)] Deploy reboot detected — now running v${NEW_VERSION}"
        rm -f "$REBOOT_FLAG"
        echo "[$(date)] Restarting in 2 seconds..."
        sleep 2
    else
        echo "[$(date)] Bot exited with code $EXIT_CODE"
        echo "[$(date)] Restarting in 3 seconds... (Ctrl+C to stop)"
        sleep 3
    fi
done
