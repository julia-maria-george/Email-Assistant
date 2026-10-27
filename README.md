# Daily 7:00 AM Email Assistant (Telegram + AI)

Automated Python assistant that:
- Reads previous 24 hours of emails across 3 Gmail accounts via IMAP
- Analyzes and categorizes updates (job interviews, recruiters, bills, urgent alerts) using Google Gemini AI
- Delivers a structured morning briefing directly to Telegram every day at 7:00 AM IST
- Runs 100% free with zero maintenance on GitHub Actions (no local computer needed)

## Setup
1. Create a `.env` file using `.env.example` as a template.
2. Run `python digest.py` for immediate local testing.
