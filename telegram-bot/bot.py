"""
Telegram Chatbot — The Core Bot
================================

Lawrence's origin story with this file:
    This is where it all started. Lawrence wanted a simple button — something
    he could press that connects him to a system that listens and responds.
    Telegram was that button. It already had the bot framework built in, so
    all he had to do was talk to @BotFather, get a token, paste it into .env,
    and suddenly he had a live wire between his phone and his code.

    This file is the front door. It handles:
    - /start  → first contact, the handshake
    - /help   → what can this thing do?
    - /echo   → proof of life (you talk, it talks back)
    - /info   → who am I, where am I?
    - /getit  → the real magic — the problem-solving skill

    Every command handler below is a tiny subroutine. When Telegram receives
    a message, it hits this file, matches the command, and runs the function.
    If it's not a command, it falls through to handle_message() which just
    echoes back — a safety net so the user always gets a response.

How to set this up from scratch:
    1. Open Telegram, search for @BotFather, type /newbot
    2. Follow the prompts — give your bot a name and username
    3. BotFather gives you a token like 123456:ABC-DEF...
    4. Copy .env.example to .env → paste the token there
    5. pip install -r requirements.txt
    6. python bot.py
    That's it. Your bot is live. Minimal effort, maximum connection.

Where this is going:
    From here Lawrence can bolt on any skill he wants — /getit was the first.
    Each skill lives in the skills/ folder as its own module. This file just
    wires them up. Think of it as the switchboard.
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

# Skills — each one is a self-contained conversation flow
# that gets registered as a handler. The bot doesn't need to know
# the internals, just how to plug them in.
from skills.getit import create_handler as getit_handler
from skills.updater import create_handlers as updater_handlers, check_deploy_receipt, format_announcement

# Load the .env file so we can read TELEGRAM_BOT_TOKEN
# without hardcoding secrets into the source code.
load_dotenv()

# Logging — this prints timestamped messages to the terminal
# so Lawrence can see exactly what's happening when the bot runs.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Command handlers
# Each function below handles one slash command from Telegram.
# The pattern is always the same: receive the update, do something, reply.
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /start — The first thing a user sees when they open the bot.
    This is the handshake. Make it warm, make it clear.
    """
    user = update.effective_user
    logger.info("Command /start from %s (@%s)", user.first_name, user.username)
    await update.message.reply_text(
        f"Hi {user.first_name}! I'm your Telegram bot.\n\n"
        "Commands:\n"
        "/start  - Show this welcome message\n"
        "/help   - List available commands\n"
        "/echo <text> - I'll repeat what you say\n"
        "/info   - Show info about this chat\n"
        "/getit  - Problem solver: bridge what you need with what you know\n\n"
        "Update system:\n"
        "/version - Current version + changelog\n"
        "/update <note> - Stage a change\n"
        "/changes - View staged changes\n"
        "/deploy  - Ship it: bump version, log, reboot\n"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /help — Quick reference card for everything the bot can do.
    Whenever a new skill is added, update this list too.
    """
    await update.message.reply_text(
        "Available commands:\n"
        "/start  - Welcome message\n"
        "/help   - This help text\n"
        "/echo <text> - Echo your message back\n"
        "/info   - Chat and user info\n"
        "/getit  - Problem solver: bridge what you need with what you know\n\n"
        "Update system:\n"
        "/version - Current version + changelog\n"
        "/update <note> - Stage a change\n"
        "/changes - View staged changes\n"
        "/deploy  - Ship it: bump version, log, reboot\n\n"
        "You can also just send me any message and I'll reply!"
    )


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /echo <text> — Proof of life. You say something, it says it back.
    Useful for testing that the bot is actually running and connected.
    """
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text("Usage: /echo <text>")
        return
    await update.message.reply_text(text)


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /info — Shows who you are and where you are in Telegram's world.
    The chat_id is especially useful — you need it if you ever want
    to send messages programmatically to a specific conversation.
    """
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
# Default message handler
# If someone sends plain text (not a command), this catches it.
# Right now it just echoes — but this is where you'd plug in
# a general AI conversation handler later.
# ---------------------------------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply to any non-command text message."""
    user = update.effective_user
    text = update.message.text
    logger.info("Message from %s (@%s): %s", user.first_name, user.username, text)
    await update.message.reply_text(f"You said: {text}")


# ---------------------------------------------------------------------------
# Error handler — catches anything that goes wrong so the bot
# doesn't crash silently. Check the terminal logs to debug.
# ---------------------------------------------------------------------------

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors."""
    logger.error("Exception while handling an update:", exc_info=context.error)


# ---------------------------------------------------------------------------
# Main — the ignition. This is what runs when you type: python bot.py
#
# The order of add_handler matters:
#   - ConversationHandlers (skills) go FIRST so they capture their own flow
#   - Specific command handlers go next
#   - The generic MessageHandler goes LAST as a catch-all
# ---------------------------------------------------------------------------

def main() -> None:
    # Grab the token from .env — this is the key that proves
    # to Telegram's servers that we're authorized to control this bot.
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN not set. "
            "Copy .env.example to .env and add your token."
        )

    # Check if we just rebooted after a /deploy.
    # If so, there's a deploy receipt waiting — read it now and
    # schedule the announcement to be sent once polling starts.
    deploy_receipt = check_deploy_receipt()

    async def post_init(application) -> None:
        """
        Runs right after the bot connects to Telegram.
        If we have a deploy receipt, send the announcement to the chat
        that triggered the deploy. This is the "I'm back!" moment.
        """
        if deploy_receipt:
            chat_id = deploy_receipt["chat_id"]
            message = format_announcement(deploy_receipt)
            try:
                await application.bot.send_message(chat_id=chat_id, text=message)
                logger.info("Sent deploy announcement to chat %s", chat_id)
            except Exception as e:
                logger.error("Failed to send deploy announcement: %s", e)

    # Build the application — this is the python-telegram-bot framework
    # doing the heavy lifting. It handles polling, parsing, routing.
    # post_init is wired in here so the deploy announcement fires
    # right after the bot connects to Telegram.
    app = ApplicationBuilder().token(token).post_init(post_init).build()

    # Register handlers — order matters!
    app.add_handler(getit_handler())  # /getit skill — must be before generic handler
    for h in updater_handlers():      # /version, /update, /deploy, /changes, /cancel_update
        app.add_handler(h)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("echo", echo))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    # Start polling — the bot connects to Telegram and says
    # "give me any new messages" every few seconds. It runs forever
    # until you hit Ctrl+C or kill the process.
    logger.info("Bot is starting...")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
