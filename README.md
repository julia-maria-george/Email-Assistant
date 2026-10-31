# Daily 7:00 AM Email Assistant (Telegram + AI)

Automated Python assistant that:
- Reads previous emails across Gmail accounts via IMAP
- Analyzes and categorizes updates (job interviews, recruiters, bills, urgent alerts) using Google Gemini AI
- Delivers a structured morning briefing directly to Telegram every day at 7:00 AM IST
- Runs interactively on Render with Telegram Webhooks (wakes up on "hi" or button clicks) or via GitHub Actions.

---

## Why Render Sleeps & How the Bot Wakes Up

On Render's free tier, web services sleep after 15 minutes of inactivity.
* **Webhook Auto-Wakeup**: When hosted on Render, the bot automatically configures Telegram Webhooks. When you send "hi", `/digest`, or tap any button in Telegram, Telegram makes an HTTPS POST request to your Render URL (`/webhook`), which **automatically wakes Render from sleep** to process your request.
* **Instant Responses (Zero Wakeup Delay)**: To keep Render awake 24/7 so it responds instantly with 0 cold start delay, create a free monitor on [cron-job.org](https://cron-job.org) or [UptimeRobot](https://uptimerobot.com) pinging your Render URL (`https://your-service.onrender.com/keepalive`) every 10 minutes.

---

## 7:00 AM IST Scheduled Daily Digest (2 Reliable Options)

### Option 1: Free Webhook Schedule via cron-job.org (Recommended)
1. Go to [cron-job.org](https://cron-job.org) (100% free).
2. Create a new cron job:
   - **URL**: `https://your-service.onrender.com/cron_digest`
   - **Execution Schedule**: Every day at `07:00` (Timezone: `Asia/Kolkata` / IST).
3. Whenever 7:00 AM arrives, cron-job.org sends an HTTP ping to Render, wakes the service up, generates the daily digest, and sends it directly to your Telegram!

### Option 2: GitHub Actions (`daily_digest.yml`)
- Runs `digest.py` every morning at 7:03 AM IST.
- Make sure repository secrets are configured in **GitHub Repo Settings -> Secrets and variables -> Actions**:
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`
  - `GEMINI_API_KEY`
  - `GMAIL_1_EMAIL`, `GMAIL_1_PASSWORD`, `GMAIL_1_LABEL`
  - `GMAIL_2_EMAIL`, `GMAIL_2_PASSWORD`, `GMAIL_2_LABEL`

---

## Running Locally

1. Create a `.env` file using `.env.example` as a template.
2. For testing the one-shot daily briefing:
   ```bash
   python digest.py
   ```
3. For running the interactive bot in local polling mode:
   ```bash
   python interactive_bot.py
   ```
