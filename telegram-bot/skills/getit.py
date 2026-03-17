"""
Skill: /getit — "How does Lawrence get things to him?"
=====================================================

The origin story:
    Lawrence kept running into the same wall: he knew what he needed but
    couldn't see how to get from where he was to where he wanted to be.
    Not because the answer was complicated — but because the gap between
    "what I know" and "what I need" felt like two different worlds.

    So we built /getit. It's a guided conversation that does one thing:
    finds the overlap between what you already have and what you're after,
    then gives you a concrete path to walk.

How it works (the conversation flow):
    1. TRIGGER: User types /getit
    2. GAP TYPE: "What kind of problem?" — pick from 4 categories:
       - Something I don't have (possession)
       - Something I want to do (action)
       - Something I need to get (acquisition)
       - Something I must understand (knowledge)
    3. THE GAP: "Describe it" — user explains what they're missing
    4. THE ANCHOR: "What DO you know?" — user describes something they're
       already good at, something one-click, low-friction, easy access
    5. ANCHOR DETAIL: "How do you use it?" — user gives a real example
    6. THE BRIDGE: AI connects the two — reframes the gap in terms of
       the anchor, then delivers an action arc:
       - Reframe → Map overlaps → One action → Template → Report back

The psychology:
    People don't lack ability. They lack a bridge between what they know
    and what they need. This skill builds that bridge by making the user
    realize their existing strengths are the launchpad, not a separate thing.

    The "arc" is intentionally structured like a story: you have a starting
    point (anchor), a destination (gap), and steps in between. That's why
    it's called an arc — it mirrors how people naturally move through change.

Technical notes:
    - Uses python-telegram-bot's ConversationHandler to manage state
    - Each "state" is a step in the conversation (ASK_GAP, ASK_ANCHOR, etc.)
    - User data is stored in context.user_data — per-user, in-memory
    - /cancel exits the flow at any point
    - The handler must be registered BEFORE the generic message handler
      in bot.py, otherwise plain text messages get caught by the wrong handler

Future:
    Right now the bridge is template-based. The next evolution is to plug
    in an AI that generates truly personalized bridges based on the specific
    gap and anchor. The structure is ready for it — just replace _build_bridge().
"""

from telegram import Update
from telegram.ext import (
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------------------------------------------------------------------
# Conversation states
# These are just integers that tell the ConversationHandler which step
# the user is on. Think of them as page numbers in a choose-your-own-adventure.
# ---------------------------------------------------------------------------
ASK_GAP, ASK_GAP_TYPE, ASK_ANCHOR, ASK_ANCHOR_DETAIL, DELIVER = range(5)

# The four types of gaps someone might have.
# Key = what the user types (1-4)
# Value = (human-readable label, internal category name)
GAP_TYPES = {
    "1": ("something I don't have", "possession"),
    "2": ("something I want to do", "action"),
    "3": ("something I need to get", "acquisition"),
    "4": ("something I must understand", "knowledge"),
}


# ---------------------------------------------------------------------------
# Step 1: Entry point — the user types /getit
# ---------------------------------------------------------------------------

async def getit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Welcome the user and ask them to categorize their problem.
    We keep it conversational — not like a form, more like a friend asking
    "what's going on?"
    """
    user = update.effective_user
    # Initialize a clean slate for this conversation
    context.user_data["getit"] = {}
    await update.message.reply_text(
        f"Hey {user.first_name}! Welcome to GetIt.\n\n"
        "I'm going to help you bridge the gap between where you are "
        "and where you need to be.\n\n"
        "First — what's the situation? Pick the one that fits best:\n\n"
        "1. Something I don't have\n"
        "2. Something I want to do\n"
        "3. Something I need to get\n"
        "4. Something I must understand\n\n"
        "Reply with 1, 2, 3, or 4."
    )
    return ASK_GAP_TYPE


# ---------------------------------------------------------------------------
# Step 2: User picks a category (1-4)
# ---------------------------------------------------------------------------

async def receive_gap_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Validate the choice and store it. Then ask the real question:
    "OK, so what specifically is it?"

    Each category gets a slightly different prompt to feel natural.
    """
    choice = update.message.text.strip()
    if choice not in GAP_TYPES:
        await update.message.reply_text("Just reply 1, 2, 3, or 4.")
        return ASK_GAP_TYPE

    label, category = GAP_TYPES[choice]
    context.user_data["getit"]["gap_type"] = category
    context.user_data["getit"]["gap_label"] = label

    # Tailor the follow-up question to the category
    prompts = {
        "possession": "What is it you don't have? Describe it — be specific.",
        "action": "What do you want to be able to do? Paint the picture for me.",
        "acquisition": "What do you need to get your hands on? Tell me everything.",
        "knowledge": "What do you need to understand? What's confusing or unclear?",
    }

    await update.message.reply_text(
        f"Got it — {label}.\n\n{prompts[category]}"
    )
    return ASK_GAP


# ---------------------------------------------------------------------------
# Step 3: User describes the gap (what they're missing)
# ---------------------------------------------------------------------------

async def receive_gap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Store the gap description. Now flip the script — ask about their
    strengths. This is the key insight: everyone has SOMETHING they're
    good at or have easy access to. That's the launchpad.
    """
    context.user_data["getit"]["gap"] = update.message.text

    await update.message.reply_text(
        "OK, I hear you. Now flip it.\n\n"
        "Tell me something you DO know well — something you already have "
        "easy access to. A skill, a tool, a connection, a routine. "
        "Something that's one-click, low-friction for you.\n\n"
        "What's your strong suit right now?"
    )
    return ASK_ANCHOR


# ---------------------------------------------------------------------------
# Step 4: User describes their anchor (what they already have)
# ---------------------------------------------------------------------------

async def receive_anchor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Store the anchor. Ask one more question to deepen it —
    how do they actually USE this thing day-to-day?
    This gives us enough detail to build a real bridge.
    """
    context.user_data["getit"]["anchor"] = update.message.text

    await update.message.reply_text(
        "Nice. And how do you usually use that? "
        "Give me a quick example — like, what does a normal day "
        "look like when you're in your element with it?"
    )
    return ASK_ANCHOR_DETAIL


# ---------------------------------------------------------------------------
# Step 5: User gives detail on their anchor → we deliver the bridge + arc
# ---------------------------------------------------------------------------

async def receive_anchor_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    This is the payoff. We now have:
    - What they need (the gap)
    - What they have (the anchor)
    - How they use it (anchor detail)

    We build the bridge — connecting the two — and deliver an action arc
    that gives them concrete next steps.
    """
    data = context.user_data["getit"]
    data["anchor_detail"] = update.message.text

    gap = data["gap"]
    gap_label = data["gap_label"]
    anchor = data["anchor"]
    anchor_detail = data["anchor_detail"]

    # Generate the bridge and action arc
    bridge = _build_bridge(gap_label, gap, anchor, anchor_detail)

    await update.message.reply_text(bridge)

    # Clean up conversation data — fresh slate for next time
    context.user_data.pop("getit", None)
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# The Bridge Builder
# This is where the magic happens. Right now it's template-based.
# Future version: plug in an AI here for truly personalized responses.
# ---------------------------------------------------------------------------

def _build_bridge(gap_label: str, gap: str, anchor: str, anchor_detail: str) -> str:
    """
    Generate the bridge message that connects the gap to the anchor,
    plus a 5-step action arc the user can follow immediately.

    The arc structure:
    1. REFRAME  — see the gap as an extension of the anchor, not a separate world
    2. MAP      — find 3 overlaps between anchor and gap
    3. ONE ACTION — do the smallest thing today (not a plan, an action)
    4. TEMPLATE — slot practice into the existing daily routine
    5. REPORT BACK — come back and iterate (keeps momentum)
    """

    return (
        "— THE BRIDGE —\n\n"
        f"What you need: {gap_label} — \"{gap}\"\n"
        f"What you've got: \"{anchor}\"\n"
        f"How you use it: \"{anchor_detail}\"\n\n"
        "Here's what I see:\n\n"
        f"You already operate with \"{anchor}\" — that's your launchpad. "
        f"The thing you're after (\"{gap}\") isn't as far as it feels. "
        "They share a common thread: you already have the mindset and "
        "the rhythm to get there.\n\n"
        "— YOUR ARC (Next Steps) —\n\n"
        f"Step 1: REFRAME\n"
        f"  Treat \"{gap}\" as an extension of \"{anchor}\" — "
        "not a separate problem, but the next level of what you already do.\n\n"
        f"Step 2: MAP\n"
        f"  Write down 3 things about \"{anchor}\" that overlap with "
        f"what you need. Skills, people, tools, habits — anything.\n\n"
        f"Step 3: ONE ACTION\n"
        f"  Pick the smallest, easiest overlap and do ONE thing today "
        "that moves the needle. Not a plan — an action.\n\n"
        f"Step 4: TEMPLATE\n"
        f"  Take your daily routine with \"{anchor}\" "
        f"and slot in 15 minutes where you practice toward \"{gap}\".\n\n"
        f"Step 5: REPORT BACK\n"
        f"  Come back and type /getit again after you've done Step 3. "
        "We'll tighten the arc.\n\n"
        "You've got more runway than you think."
    )


# ---------------------------------------------------------------------------
# Cancel — escape hatch at any point in the conversation
# ---------------------------------------------------------------------------

async def getit_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Let the user bail out of the flow without guilt."""
    context.user_data.pop("getit", None)
    await update.message.reply_text("No worries — come back anytime with /getit.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Handler factory
# This is what bot.py imports and registers. It packages the whole
# conversation flow into a single handler that the framework manages.
# ---------------------------------------------------------------------------

def create_handler() -> ConversationHandler:
    """
    Return the ConversationHandler to register with the app.

    The flow:
        /getit → pick type → describe gap → describe anchor → detail → bridge

    Each state maps to a handler function. The framework tracks which state
    each user is in, so multiple users can be at different steps simultaneously.
    """
    return ConversationHandler(
        entry_points=[CommandHandler("getit", getit_start)],
        states={
            ASK_GAP_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_gap_type)],
            ASK_GAP: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_gap)],
            ASK_ANCHOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_anchor)],
            ASK_ANCHOR_DETAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_anchor_detail)],
        },
        fallbacks=[CommandHandler("cancel", getit_cancel)],
    )
