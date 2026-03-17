"""
Telegram Chatbot
================
A simple Telegram bot with common commands and conversational features.

Setup:
    1. Talk to @BotFather on Telegram to create a bot and get a token
    2. Copy .env.example to .env and paste your token
    3. pip install -r requirements.txt
    4. python bot.py
"""

import logging
import os
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


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message when /start is issued."""
    user = update.effective_user
    await update.message.reply_text(
        f"Hi {user.first_name}! I'm your Telegram bot.\n\n"
        "Commands:\n"
        "/start  - Show this welcome message\n"
        "/help   - List available commands\n"
        "/echo <text> - I'll repeat what you say\n"
        "/info   - Show info about this chat\n"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a list of available commands."""
    await update.message.reply_text(
        "Available commands:\n"
        "/start  - Welcome message\n"
        "/help   - This help text\n"
        "/echo <text> - Echo your message back\n"
        "/info   - Chat and user info\n\n"
        "You can also just send me any message and I'll reply!"
    )


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Echo the user's text back to them."""
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text("Usage: /echo <text>")
        return
    await update.message.reply_text(text)


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show information about the current chat and user."""
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
# Message handler (responds to plain text)
# ---------------------------------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply to any non-command text message."""
    text = update.message.text
    await update.message.reply_text(f"You said: {text}")


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors."""
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

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("echo", echo))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
