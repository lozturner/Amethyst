"""
Relay bot: writes incoming messages to /tmp/tg_inbox.jsonl
and watches /tmp/tg_outbox.jsonl for replies to send back.
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

load_dotenv()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
INBOX = "/tmp/tg_inbox.jsonl"
OUTBOX = "/tmp/tg_outbox.jsonl"

for f in [INBOX, OUTBOX]:
    open(f, "a").close()


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    """Thread that watches outbox and sends replies via HTTP API."""
    last_pos = os.path.getsize(OUTBOX) if os.path.exists(OUTBOX) else 0
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    while True:
        time.sleep(1)
        try:
            with open(OUTBOX, "r") as f:
                f.seek(last_pos)
                lines = f.readlines()
                last_pos = f.tell()
            for line in lines:
                line = line.strip()
                if not line:
                    continue
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

    # Start outbox sender in background thread
    t = threading.Thread(target=outbox_sender, daemon=True)
    t.start()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_handler(CommandHandler("start", on_message))

    logger.info("Relay bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
