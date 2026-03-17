# Telegram Chatbot

A simple Telegram chatbot built with [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot).

## Setup

### 1. Create a bot on Telegram

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the API token you receive

### 2. Configure the token

```bash
cd telegram-bot
cp .env.example .env
```

Edit `.env` and paste your bot token.

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the bot

```bash
python bot.py
```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/help` | List available commands |
| `/echo <text>` | Echo your message back |
| `/info` | Show chat and user info |

Any plain text message will get a reply as well.
