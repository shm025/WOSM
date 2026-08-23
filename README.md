# WOSM Volunteer Monitor

Automatically checks WOSM pages every 6 hours with GitHub Actions and sends a Telegram notification when a monitored page changes. An optional OpenAI step reviews the changed content and filters for genuine volunteer/open-call opportunities.

The official WOSM volunteer page says global-level volunteers should follow WOSM's channels for upcoming open calls, and WOSM has historically run global volunteer open calls. The monitor therefore watches the official WOSM volunteer/careers pages rather than relying on a single permanent application URL.

## 1. Create a Telegram bot

In Telegram, create a bot using BotFather and obtain its bot token.

Send a message to the bot once, then obtain the chat ID. One simple way is to open:

`https://api.telegram.org/botYOUR_TOKEN/getUpdates`

Use the numeric `chat.id` from the response.

## 2. Create a GitHub repository

Create a private GitHub repository and upload all files from this folder.

## 3. Add GitHub Actions secrets

Repository → Settings → Secrets and variables → Actions → New repository secret

Add:

- `TELEGRAM_BOT_TOKEN` — Telegram bot token
- `TELEGRAM_CHAT_ID` — destination chat ID
- `OPENAI_API_KEY` — optional, for AI filtering
- `OPENAI_MODEL` — optional; defaults to `gpt-5-mini`

If you omit the OpenAI secrets, the monitor still detects page changes and sends a generic Telegram alert.

## 4. Run once manually

Actions → Check WOSM volunteer opportunities → Run workflow.

The first run creates `state.json` as a baseline and intentionally does not send an alert.

After that, the workflow runs every 6 hours.

## Notes

- This monitors official WOSM pages only.
- It does not automatically apply for anything.
- It does not need your WOSM login.
- The AI layer is optional and is only called after a monitored page changes.
- GitHub Actions can occasionally delay scheduled workflows, so the check is not guaranteed to run at the exact minute.
- If WOSM changes its site structure, the URLs/selectors in `monitor.py` may need adjustment.
