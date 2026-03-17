"""
Telegram Chatbot — The Core Bot
================================

This file is the front door. It handles all commands, tracks the owner,
sends a startup greeting, and lets the user toggle echo mode on/off.

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
# Owner tracking — saves chat_id so the bot can message you on startup
# ---------------------------------------------------------------------------

OWNER_FILE = os.path.join(os.path.dirname(__file__), "owner.json")
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")


def load_owner():
    """Load saved owner chat_id, or None if not yet known."""
    if os.path.exists(OWNER_FILE):
        try:
            with open(OWNER_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def save_owner(chat_id: int, user_id: int, first_name: str, username: str):
    """Save owner info so the bot can greet them on startup."""
    data = {
        "chat_id": chat_id,
        "user_id": user_id,
        "first_name": first_name,
        "username": username,
    }
    with open(OWNER_FILE, "w") as f:
        json.dump(data, f, indent=2)
    return data


def load_settings():
    """Load bot settings (echo mode, etc.)."""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"echo_mode": True}


def save_settings(settings: dict):
    """Save bot settings to disk."""
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)


def _remember_owner(update: Update):
    """Save chat_id on every interaction so we always have it."""
    user = update.effective_user
    chat = update.effective_chat
    if user and chat:
        save_owner(chat.id, user.id, user.first_name, user.username or "")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — Welcome message with full command list."""
    _remember_owner(update)
    user = update.effective_user
    logger.info("Command /start from %s (@%s)", user.first_name, user.username)
    await update.message.reply_text(
        f"Hey {user.first_name}! I'm online and ready.\n\n"
        "Here's everything I can do:\n\n"
        "BASICS\n"
        "/start - This welcome message\n"
        "/help - Full command list\n"
        "/echo <text> - I repeat what you say\n"
        "/info - Your user + chat info\n\n"
        "TOOLS\n"
        "/getit - Problem solver: bridge what you need with what you know\n\n"
        "SETTINGS\n"
        "/echome - Toggle echo replies on/off\n"
        "/settings - View current settings\n\n"
        "UPDATES\n"
        "/version - Current version + changelog\n"
        "/update <note> - Stage a change\n"
        "/changes - View staged changes\n"
        "/deploy - Ship it: bump version, log, reboot\n"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/help — Quick reference card."""
    _remember_owner(update)
    await update.message.reply_text(
        "BASICS\n"
        "/start - Welcome message\n"
        "/help - This list\n"
        "/echo <text> - Echo your message\n"
        "/info - Chat and user info\n\n"
        "TOOLS\n"
        "/getit - Problem solver\n\n"
        "SETTINGS\n"
        "/echome - Toggle: stop/start echoing your messages back\n"
        "/settings - View current settings\n\n"
        "UPDATES\n"
        "/version - Current version + changelog\n"
        "/update <note> - Stage a change\n"
        "/changes - View staged changes\n"
        "/deploy - Ship it\n\n"
        "Send any message and I'll reply (unless echo is off)."
    )


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/echo <text> — Repeat what you say."""
    _remember_owner(update)
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text("Usage: /echo <text>")
        return
    await update.message.reply_text(text)


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/info — Show user and chat info."""
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


async def echome_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/echome — Toggle echo mode on or off."""
    _remember_owner(update)
    settings = load_settings()
    settings["echo_mode"] = not settings.get("echo_mode", True)
    save_settings(settings)
    state = "ON" if settings["echo_mode"] else "OFF"
    await update.message.reply_text(
        f"Echo mode is now {state}.\n\n"
        f"{'I will repeat your messages back.' if settings['echo_mode'] else 'I will stay quiet when you send plain text.'}"
    )


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/settings — Show current bot settings."""
    _remember_owner(update)
    settings = load_settings()
    echo_state = "ON" if settings.get("echo_mode", True) else "OFF"
    owner = load_owner()
    owner_info = f"@{owner['username']}" if owner and owner.get("username") else "Not set"
    await update.message.reply_text(
        "Current settings:\n\n"
        f"Echo mode: {echo_state}\n"
        f"Owner: {owner_info}\n\n"
        "Use /echome to toggle echo on/off."
    )


# ---------------------------------------------------------------------------
# Default message handler
# ---------------------------------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply to any non-command text message (if echo mode is on)."""
    _remember_owner(update)
    user = update.effective_user
    text = update.message.text
    logger.info("Message from %s (@%s, chat_id=%s): %s",
                user.first_name, user.username, update.effective_chat.id, text)

    settings = load_settings()
    if settings.get("echo_mode", True):
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

    deploy_receipt = check_deploy_receipt()
    owner = load_owner()

    async def post_init(application) -> None:
        """
        Runs right after the bot connects to Telegram.
        - Sends startup greeting to owner
        - Sends deploy announcement if we just rebooted after /deploy
        - Registers command menu with Telegram
        """
        # Register commands so they show up in Telegram's menu button
        commands = [
            BotCommand("start", "Welcome message"),
            BotCommand("help", "Full command list"),
            BotCommand("echo", "Echo your text back"),
            BotCommand("info", "Your user + chat info"),
            BotCommand("getit", "Problem solver"),
            BotCommand("echome", "Toggle echo replies on/off"),
            BotCommand("settings", "View current settings"),
            BotCommand("version", "Current version + changelog"),
            BotCommand("update", "Stage a change note"),
            BotCommand("changes", "View staged changes"),
            BotCommand("deploy", "Ship it: bump version, reboot"),
        ]
        await application.bot.set_my_commands(commands)
        logger.info("Registered %d commands with Telegram", len(commands))

        # Deploy announcement takes priority over generic startup
        if deploy_receipt:
            chat_id = deploy_receipt["chat_id"]
            message = format_announcement(deploy_receipt)
            try:
                await application.bot.send_message(chat_id=chat_id, text=message)
                logger.info("Sent deploy announcement to chat %s", chat_id)
            except Exception as e:
                logger.error("Failed to send deploy announcement: %s", e)
        elif owner:
            # Startup greeting — bot messages the owner proactively
            try:
                await application.bot.send_message(
                    chat_id=owner["chat_id"],
                    text=(
                        f"I'm back online, {owner['first_name']}!\n\n"
                        "Type /help to see what I can do,\n"
                        "or just send me a message."
                    ),
                )
                logger.info("Sent startup greeting to %s (chat %s)",
                            owner["first_name"], owner["chat_id"])
            except Exception as e:
                logger.error("Failed to send startup greeting: %s", e)

    app = ApplicationBuilder().token(token).post_init(post_init).build()

    # Register handlers — order matters!
    app.add_handler(getit_handler())
    for h in updater_handlers():
        app.add_handler(h)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("echo", echo))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("echome", echome_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
