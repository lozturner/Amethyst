"""
Telegram Chatbot — The Core Bot
================================

Setup:
    1. Open Telegram, search for @BotFather, type /newbot
    2. Follow the prompts — give your bot a name and username
    3. BotFather gives you a token like 123456:ABC-DEF...
    4. Copy .env.example to .env -> paste the token there
    5. pip install -r requirements.txt
    6. python bot.py
"""

import json
import logging
import os
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from skills.getit import create_handler as getit_handler
from skills.updater import create_handlers as updater_handlers, check_deploy_receipt, format_announcement

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Owner tracking
# ---------------------------------------------------------------------------

OWNER_FILE = os.path.join(os.path.dirname(__file__), "owner.json")


def load_owner():
    if os.path.exists(OWNER_FILE):
        try:
            with open(OWNER_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def save_owner(chat_id: int, user_id: int, first_name: str, username: str):
    data = {
        "chat_id": chat_id,
        "user_id": user_id,
        "first_name": first_name,
        "username": username,
    }
    with open(OWNER_FILE, "w") as f:
        json.dump(data, f, indent=2)
    return data


def _remember_owner(update: Update):
    user = update.effective_user
    chat = update.effective_chat
    if user and chat:
        save_owner(chat.id, user.id, user.first_name, user.username or "")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_owner(update)
    user = update.effective_user
    logger.info("Command /start from %s (@%s)", user.first_name, user.username)
    await update.message.reply_text(
        f"Hey {user.first_name}! I'm online and ready.\n\n"
        "Here's what I can do:\n\n"
        "/help - Full command list\n"
        "/info - Your user + chat info\n"
        "/getit - Problem solver\n"
        "/version - Current version\n\n"
        "Send me a message anytime."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_owner(update)
    await update.message.reply_text(
        "BASICS\n"
        "/start - Welcome message\n"
        "/help - This list\n"
        "/info - Chat and user info\n\n"
        "TOOLS\n"
        "/getit - Problem solver\n\n"
        "UPDATES\n"
        "/version - Current version + changelog\n"
        "/update <note> - Stage a change\n"
        "/changes - View staged changes\n"
        "/deploy - Ship it\n"
    )


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_owner(update)
    user = update.effective_user
    chat = update.effective_chat
    await update.message.reply_text(
        f"User: {user.first_name} {user.last_name or ''}\n"
        f"Username: @{user.username or 'N/A'}\n"
        f"User ID: {user.id}\n"
        f"Chat ID: {chat.id}\n"
        f"Chat type: {chat.type}"
    )


# ---------------------------------------------------------------------------
# Default message handler — no echo, just acknowledge
# ---------------------------------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _remember_owner(update)
    user = update.effective_user
    text = update.message.text
    logger.info("Message from %s (@%s, chat_id=%s): %s",
                user.first_name, user.username, update.effective_chat.id, text)
    await update.message.reply_text(
        "Got it. Use /help to see what I can do."
    )


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN not set. "
            "Copy .env.example to .env and add your token."
        )

    deploy_receipt = check_deploy_receipt()
    owner = load_owner()

    async def post_init(application) -> None:
        commands = [
            BotCommand("start", "Welcome message"),
            BotCommand("help", "Full command list"),
            BotCommand("info", "Your user + chat info"),
            BotCommand("getit", "Problem solver"),
            BotCommand("version", "Current version + changelog"),
            BotCommand("update", "Stage a change note"),
            BotCommand("changes", "View staged changes"),
            BotCommand("deploy", "Ship it: bump version, reboot"),
        ]
        await application.bot.set_my_commands(commands)
        logger.info("Registered %d commands with Telegram", len(commands))

        if deploy_receipt:
            chat_id = deploy_receipt["chat_id"]
            message = format_announcement(deploy_receipt)
            try:
                await application.bot.send_message(chat_id=chat_id, text=message)
                logger.info("Sent deploy announcement to chat %s", chat_id)
            except Exception as e:
                logger.error("Failed to send deploy announcement: %s", e)
        elif owner:
            try:
                await application.bot.send_message(
                    chat_id=owner["chat_id"],
                    text=f"I'm back online, {owner['first_name']}! Type /help for commands.",
                )
                logger.info("Sent startup greeting to %s (chat %s)",
                            owner["first_name"], owner["chat_id"])
            except Exception as e:
                logger.error("Failed to send startup greeting: %s", e)

    app = ApplicationBuilder().token(token).post_init(post_init).build()

    app.add_handler(getit_handler())
    for h in updater_handlers():
        app.add_handler(h)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
