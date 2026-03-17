"""
Skill: /update — The Self-Updating Bot
========================================

Why this exists:
    Lawrence wanted a bot that could evolve from inside the chat itself.
    Instead of SSH-ing into a server, editing files, and restarting manually,
    he wanted to type a command in Telegram, describe what changed, and have
    the bot update itself — bump the version, log the change, confirm it,
    and reboot. All from the conversation.

How it works:
    The update system has several commands:

    /version
        Shows the current version number and recent changelog.
        Quick check — "what version am I running?"

    /update <description>
        Stages a change description. You can call this multiple times
        to queue up several change notes before deploying.
        Example: /update Added dark mode support

    /changes
        Shows what's currently staged — the changes queued up but not
        yet deployed. Like "git status" for the bot.

    /deploy
        The big one. This:
        1. Bumps the version number (patch by default: 1.0.0 → 1.0.1)
        2. Writes all staged changes into version.json
        3. Sends the user a confirmation with the new version + changelog
        4. Reboots the bot process so the new code takes effect

    /deploy minor  → bumps minor version (1.0.0 → 1.1.0)
    /deploy major  → bumps major version (1.0.0 → 2.0.0)

    /cancel_update
        Clears all staged changes without deploying.

The reboot mechanism:
    The bot can't restart itself from inside its own process cleanly.
    So /deploy writes a reboot flag file (/tmp/tg_reboot_flag), then
    the launcher script (run.sh) watches for that flag and restarts
    the bot. Simple, reliable, no magic.

Security note:
    Right now ANY user can trigger /deploy. In production you'd want
    to restrict this to specific user IDs (admin list). There's a
    placeholder for that in the ADMIN_IDS list below.

Technical notes:
    - version.json is the single source of truth for version + history
    - Staged changes live in context.bot_data (shared across all users)
    - The version bump follows semver: major.minor.patch
    - The reboot flag is just an empty file — existence = "please restart"
"""

import json
import os
from datetime import date
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Path to the version file — lives next to bot.py
VERSION_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "version.json")

# Reboot flag — the launcher script watches for this file
REBOOT_FLAG = "/tmp/tg_reboot_flag"

# Deploy receipt — written before reboot so the bot can announce
# the new version when it comes back online. Contains JSON with
# the chat_id to message, the new version, and the change list.
DEPLOY_RECEIPT = "/tmp/tg_deploy_receipt.json"

# Admin user IDs — only these users can deploy updates.
# Set to empty list to allow anyone (development mode).
# Find your user ID with /info command.
ADMIN_IDS = []  # e.g. [6315945723]

STAGED_KEY = "staged_changes"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_version():
    """Read version.json and return the dict."""
    with open(VERSION_FILE, "r") as f:
        return json.load(f)


def _save_version(data):
    """Write version.json back to disk."""
    with open(VERSION_FILE, "w") as f:
        json.dump(data, f, indent=4)
        f.write("\n")


def _bump(version_str: str, bump_type: str = "patch") -> str:
    """
    Bump a semver string.
    "1.0.0" + patch → "1.0.1"
    "1.0.0" + minor → "1.1.0"
    "1.0.0" + major → "2.0.0"
    """
    parts = [int(x) for x in version_str.split(".")]
    if bump_type == "major":
        parts[0] += 1
        parts[1] = 0
        parts[2] = 0
    elif bump_type == "minor":
        parts[1] += 1
        parts[2] = 0
    else:  # patch
        parts[2] += 1
    return ".".join(str(x) for x in parts)


def _is_admin(user_id: int) -> bool:
    """Check if a user is allowed to deploy. Empty list = everyone allowed."""
    if not ADMIN_IDS:
        return True
    return user_id in ADMIN_IDS


def _get_staged(context: ContextTypes.DEFAULT_TYPE) -> list:
    """Get the list of staged change descriptions."""
    return context.bot_data.get(STAGED_KEY, [])


def _set_staged(context: ContextTypes.DEFAULT_TYPE, changes: list):
    """Set the staged changes list."""
    context.bot_data[STAGED_KEY] = changes


# ---------------------------------------------------------------------------
# Command: /version — show current version and recent changes
# ---------------------------------------------------------------------------

async def version_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Show the current version number and the last few changelog entries.
    This is the "what am I running?" command.
    """
    data = _load_version()
    current = data["version"]

    # Show up to 3 most recent changelog entries
    recent = data.get("changelog", [])[:3]
    history = ""
    for entry in recent:
        changes = "\n".join(f"  - {c}" for c in entry["changes"])
        history += f"\nv{entry['version']} ({entry['date']}):\n{changes}\n"

    await update.message.reply_text(
        f"Current version: v{current}\n"
        f"{history if history else '(no changelog yet)'}"
    )


# ---------------------------------------------------------------------------
# Command: /update <description> — stage a change note
# ---------------------------------------------------------------------------

async def update_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Add a change description to the staging area.
    These pile up until /deploy is called.
    Example: /update Added new /getit skill for problem solving
    """
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("You don't have permission to stage updates.")
        return

    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text(
            "Usage: /update <description of change>\n\n"
            "Example: /update Added dark mode support\n\n"
            "You can call /update multiple times to stage several changes, "
            "then /deploy to apply them all at once."
        )
        return

    staged = _get_staged(context)
    staged.append(text)
    _set_staged(context, staged)

    await update.message.reply_text(
        f"Staged: \"{text}\"\n\n"
        f"Total staged changes: {len(staged)}\n"
        "Type /changes to review, /deploy to ship, or /cancel_update to clear."
    )


# ---------------------------------------------------------------------------
# Command: /changes — show what's staged
# ---------------------------------------------------------------------------

async def changes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all staged changes that haven't been deployed yet."""
    staged = _get_staged(context)
    if not staged:
        await update.message.reply_text(
            "No changes staged.\n\n"
            "Use /update <description> to stage changes."
        )
        return

    lines = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(staged))
    await update.message.reply_text(
        f"Staged changes ({len(staged)}):\n{lines}\n\n"
        "Type /deploy to ship these, or /cancel_update to clear."
    )


# ---------------------------------------------------------------------------
# Command: /deploy [major|minor|patch] — bump version, log, reboot
# ---------------------------------------------------------------------------

async def deploy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    The big red button. This:
    1. Checks there are staged changes
    2. Bumps the version number
    3. Writes the changelog to version.json
    4. Confirms to the user
    5. Triggers a reboot via flag file
    """
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("You don't have permission to deploy.")
        return

    staged = _get_staged(context)
    if not staged:
        await update.message.reply_text(
            "Nothing to deploy. Use /update <description> first."
        )
        return

    # Determine bump type from args (default: patch)
    bump_type = "patch"
    if context.args:
        arg = context.args[0].lower()
        if arg in ("major", "minor", "patch"):
            bump_type = arg

    # Load current version, bump it, add changelog entry
    data = _load_version()
    old_version = data["version"]
    new_version = _bump(old_version, bump_type)

    entry = {
        "version": new_version,
        "date": str(date.today()),
        "changes": staged,
    }

    # Prepend to changelog (newest first)
    data["changelog"].insert(0, entry)
    data["version"] = new_version

    # Save to disk
    _save_version(data)

    # Clear staged changes
    _set_staged(context, [])

    # Format confirmation message
    change_list = "\n".join(f"  - {c}" for c in staged)
    await update.message.reply_text(
        f"Deploying v{new_version}...\n"
        f"(was v{old_version}, {bump_type} bump)\n\n"
        "Rebooting now — I'll be right back with the full announcement."
    )

    # Write the deploy receipt — when the bot restarts, it reads this
    # and sends a proper announcement to the chat with what's new.
    receipt = {
        "chat_id": update.effective_chat.id,
        "old_version": old_version,
        "new_version": new_version,
        "bump_type": bump_type,
        "changes": staged,
    }
    with open(DEPLOY_RECEIPT, "w") as f:
        json.dump(receipt, f)

    # Write the reboot flag — the launcher script picks this up
    # and restarts the bot process
    with open(REBOOT_FLAG, "w") as f:
        f.write(new_version)

    # Exit the bot process — the launcher will restart it
    os._exit(0)


# ---------------------------------------------------------------------------
# Command: /cancel_update — clear staged changes
# ---------------------------------------------------------------------------

async def cancel_update_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear all staged changes without deploying."""
    staged = _get_staged(context)
    count = len(staged)
    _set_staged(context, [])
    await update.message.reply_text(
        f"Cleared {count} staged change(s). Clean slate."
    )


# ---------------------------------------------------------------------------
# Handler registration
# Returns a list of handlers for bot.py to register.
# ---------------------------------------------------------------------------

def check_deploy_receipt():
    """
    Called once at bot startup. If a deploy receipt exists, it means
    we just rebooted after a /deploy. Returns the receipt dict so
    bot.py can send the announcement, or None if there's no receipt.

    The receipt file is deleted after reading — one-time use.
    """
    if not os.path.exists(DEPLOY_RECEIPT):
        return None
    try:
        with open(DEPLOY_RECEIPT, "r") as f:
            receipt = json.load(f)
        os.remove(DEPLOY_RECEIPT)
        return receipt
    except Exception:
        return None


def format_announcement(receipt: dict) -> str:
    """
    Build the post-reboot announcement message.
    This is what the user sees in chat when the bot comes back online
    after a /deploy. It should feel like good news arriving — friendly,
    clear, and showing exactly what's new and how to use it.
    """
    v = receipt["new_version"]
    old = receipt["old_version"]
    changes = receipt["changes"]

    change_list = "\n".join(f"  \u2022 {c}" for c in changes)

    return (
        f"\U0001f389 Back online! New version installed.\n\n"
        f"\U0001f4E6 v{old} \u2192 v{v}\n\n"
        f"What's new:\n{change_list}\n\n"
        f"This is live right now. Here's what you can do:\n"
        f"  /version  \u2014 see the full changelog\n"
        f"  /help     \u2014 see all available commands\n"
        f"  /getit    \u2014 start the problem-solving flow\n\n"
        f"If anything looks off, type /version to check."
    )


def create_handlers() -> list:
    """
    Return all command handlers for the update system.
    bot.py calls this and registers each one.
    """
    return [
        CommandHandler("version", version_cmd),
        CommandHandler("update", update_cmd),
        CommandHandler("changes", changes_cmd),
        CommandHandler("deploy", deploy_cmd),
        CommandHandler("cancel_update", cancel_update_cmd),
    ]
