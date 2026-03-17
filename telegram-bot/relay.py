"""
Relay Bot — The AI Brain Connector
====================================

Why this file exists:
    Lawrence wanted the bot to be more than an echo machine. He wanted a real
    brain behind it — something that could think, reason, and reply intelligently.

    The problem: Telegram's bot API runs in a loop, and an AI can't live inside
    that loop directly. So we built a relay system.

How it works (the plumbing):
    1. A message arrives on Telegram → the bot catches it
    2. The bot writes the message to /tmp/tg_inbox.jsonl (a simple text file)
    3. An external brain (Claude, a script, anything) reads that file
    4. The brain writes a reply to /tmp/tg_outbox.jsonl
    5. A background thread in this bot watches that file and sends the reply

    It's like a mailbox system. Inbox and outbox. Dead simple.

    The .jsonl format means one JSON object per line — easy to append,
    easy to read, no locking headaches.

How Lawrence uses it:
    - Run: python relay.py
    - Send a message to the bot on Telegram
    - Check /tmp/tg_inbox.jsonl — your message is there
    - Write a reply to /tmp/tg_outbox.jsonl — it gets sent back
    - An AI watching those files becomes the bot's brain

    This is the bridge between Telegram and whatever intelligence
    Lawrence wants to plug in. Minimal effort, maximum flexibility.

Setup:
    Same as bot.py — needs TELEGRAM_BOT_TOKEN in .env.
    Only run ONE of bot.py or relay.py at a time (not both),
    because Telegram only allows one polling connection per bot.
"""

import json
import os
import time
import threading
import requests
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Load environment variables from .env file
load_dotenv()

# Set up logging so we can see what's happening in the terminal
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# The bot token — same one from @BotFather
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# The two mailbox files:
# INBOX  = messages FROM Telegram users (the bot writes here)
# OUTBOX = messages TO Telegram users (the brain writes here)
INBOX = "/tmp/tg_inbox.jsonl"
OUTBOX = "/tmp/tg_outbox.jsonl"

# Make sure the files exist — create them if they don't.
# We append to these, never overwrite, so existing data is safe.
for f in [INBOX, OUTBOX]:
    open(f, "a").close()


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Every text message that arrives gets written to the inbox file.
    The format is one JSON line per message with:
    - chat_id: so the brain knows where to reply
    - user: the sender's first name
    - username: their @handle
    - text: what they said
    - ts: timestamp so we can track ordering
    """
    user = update.effective_user
    msg = {
        "chat_id": update.effective_chat.id,
        "user": user.first_name or "",
        "username": user.username or "",
        "text": update.message.text or "",
        "ts": time.time(),
    }
    with open(INBOX, "a") as f:
        f.write(json.dumps(msg) + "\n")
    logger.info("INBOX <- @%s: %s", msg["username"], msg["text"])


def outbox_sender():
    """
    Background thread that watches the outbox file for new lines.
    When a new line appears (written by the external brain), it parses
    the JSON and sends the message to Telegram via the HTTP API.

    Uses file position tracking (seek) so it only reads new lines,
    not the whole file every time. Checks once per second.
    """
    # Start reading from the end of whatever's already in the file
    # so we don't re-send old messages on restart
    last_pos = os.path.getsize(OUTBOX) if os.path.exists(OUTBOX) else 0
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    while True:
        time.sleep(1)  # Check once per second — fast enough, not wasteful
        try:
            with open(OUTBOX, "r") as f:
                f.seek(last_pos)
                lines = f.readlines()
                last_pos = f.tell()
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                # Each line should be: {"chat_id": 123, "text": "hello"}
                data = json.loads(line)
                resp = requests.post(url, json={
                    "chat_id": data["chat_id"],
                    "text": data["text"],
                })
                logger.info("OUTBOX -> chat %s [%s]: %s",
                            data["chat_id"], resp.status_code, data["text"][:80])
        except Exception as e:
            logger.error("Outbox error: %s", e)


def main() -> None:
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN not set.")

    # Start the outbox sender in a daemon thread.
    # "daemon" means it dies when the main program dies — no zombies.
    t = threading.Thread(target=outbox_sender, daemon=True)
    t.start()

    # Build and run the Telegram polling bot.
    # This handles the inbox side — catching messages and writing them.
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_handler(CommandHandler("start", on_message))

    logger.info("Relay bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
