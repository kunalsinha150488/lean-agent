# Lean content agent (no n8n, free hosting)

**Weekly flow:** Sunday 7pm IST the agent reads free signals (Google News RSS, Reddit RSS, optional YouTube view counts), Gemini ranks the top 5 lean / process excellence / OpEx topics and sends them to your Telegram bot. You reply with two numbers, e.g. `2 5` (first = Tuesday deck, second = Thursday deck). The agent researches both topics, builds two 10-slide PDFs in one fixed template (signature "Knowledge sharing by Kunal Sinha" on first and last slide) and sends each with a post title and ~100-word caption. You review and post manually on LinkedIn.

## Setup (about 15 minutes, all free)
1. **Gemini key:** https://aistudio.google.com/apikey -> Create API key.
2. **Telegram bot:** in Telegram open @BotFather -> /newbot -> copy the token. Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `"chat":{"id": ...}` = your chat id.
3. **YouTube key (optional, adds view-count signal):** Google Cloud Console -> new project -> enable "YouTube Data API v3" -> Credentials -> API key.
4. **GitHub:** create a **public** repo (public = unlimited free Actions minutes; it holds no secrets), upload this folder. Repo Settings -> Secrets and variables -> Actions -> add: `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `YOUTUBE_API_KEY` (optional).
5. **Test:** Actions tab -> "weekly-topics" -> Run workflow. The top 5 arrive on Telegram. Reply `1 3`. Within ~5-10 minutes both decks arrive.

## Moving to another host later
Nothing is tied to GitHub. It is plain Python:
```
pip install -r requirements.txt
export GEMINI_API_KEY=... TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... YOUTUBE_API_KEY=...
python agent.py topics        # cron: 30 13 * * 0   (Sunday 19:00 IST, if server is UTC)
python agent.py poll          # cron: */5 * * * *
```
Any always-on free Linux box (Oracle Cloud Always Free VM, an old laptop, Raspberry Pi) works. Copy `state.json` if you want to keep a pending topic list. The design lives in `deck.py`; the topic sources and prompts live in `agent.py`.

## Notes
- Offline self-test: `DRY_RUN=1 python agent.py topics` then `DRY_RUN=1 python agent.py decks 2 5`.
- GitHub scheduled runs can start a few minutes late. GitHub pauses schedules after 60 days of no repo activity; weekly state commits keep it active.
- Search interest is a proxy: it is built from news volume, Reddit ranking and YouTube views, not exact Google search counts.
- Gemini free tier has daily limits; one week of use is well inside them.
