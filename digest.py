import os
import re
import sys
import time
import json
import email
import imaplib
import urllib.request
from datetime import datetime, timedelta
from email.header import decode_header
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

MODELS_LIST = [
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-2.5-pro"
]

def get_accounts():
    accounts_json = os.getenv("GMAIL_ACCOUNTS_JSON")
    if accounts_json:
        try:
            return json.loads(accounts_json)
        except Exception:
            pass
    accounts = []
    for i in range(1, 10):
        email_addr = os.getenv(f"GMAIL_{i}_EMAIL")
        password = os.getenv(f"GMAIL_{i}_PASSWORD")
        label = os.getenv(f"GMAIL_{i}_LABEL", f"Account {i}")
        if email_addr and password:
            accounts.append({
                "email": email_addr.strip(),
                "password": password.strip().replace(" ", ""),
                "label": label.strip()
            })
    return accounts

def decode_mime_words(raw_header):
    if not raw_header:
        return ""
    decoded_fragments = decode_header(raw_header)
    text = ""
    for fragment, encoding in decoded_fragments:
        if isinstance(fragment, bytes):
            try:
                text += fragment.decode(encoding or "utf-8", errors="replace")
            except Exception:
                text += fragment.decode("latin1", errors="replace")
        else:
            text += str(fragment)
    return text.strip()

def clean_body_text(payload):
    if isinstance(payload, bytes):
        text = payload.decode("utf-8", errors="replace")
    else:
        text = str(payload)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " ".join(lines)[:2500]

def fetch_recent_emails(email_address, password, hours=24):
    emails_data = []
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email_address, password)
        mail.select("INBOX", readonly=True)

        since_date = (datetime.now() - timedelta(hours=hours)).strftime("%d-%b-%Y")
        status, messages = mail.search(None, f'(SINCE "{since_date}")')

        if status != "OK" or not messages[0]:
            mail.logout()
            return emails_data

        message_ids = messages[0].split()
        message_ids = message_ids[-30:]

        for msg_id in reversed(message_ids):
            try:
                res, data = mail.fetch(msg_id, "(RFC822)")
                if res != "OK":
                    continue
                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)

                subject = decode_mime_words(msg.get("Subject", "No Subject"))
                from_ = decode_mime_words(msg.get("From", "Unknown Sender"))
                date_str = msg.get("Date", "")

                body_snippet = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        content_disposition = str(part.get("Content-Disposition"))
                        if content_type == "text/plain" and "attachment" not in content_disposition:
                            payload = part.get_payload(decode=True)
                            if payload:
                                body_snippet = clean_body_text(payload)
                                break
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body_snippet = clean_body_text(payload)

                emails_data.append({
                    "from": from_,
                    "subject": subject,
                    "date": date_str,
                    "snippet": body_snippet
                })
            except Exception:
                continue

        mail.logout()
    except Exception as e:
        print(f"Error accessing {email_address}: {e}")

    return emails_data

def format_clean_html(text):
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.*?)\*', r'<b>\1</b>', text)
    text = re.sub(r'^\s*[\*\-]\s*', '• ', text, flags=re.MULTILINE)
    return text

def call_gemini_with_retry(prompt):
    req_data = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")

    for model_name in MODELS_LIST:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, data=req_data, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode())
                    raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                    return format_clean_html(raw_text)
            except Exception as e:
                print(f"Model {model_name} attempt {attempt+1} failed: {e}")
                time.sleep(2)

    return None

def summarize_with_gemini(all_accounts_emails):
    prompt = f"""
You are Julia's personal email executive assistant. 
Create an informative, comprehensive, and beautifully formatted email digest for Telegram.

CRITICAL REQUIREMENT - STRICT SEPARATION BY ACCOUNT:
DO NOT mix or blend emails from different accounts together!
The input contains emails keyed by each specific account label.
For EACH account, create its own distinct section header and list its emails underneath it.

FORMATTING RULES:
1. NO MARKDOWN ASTERISKS (*) OR HASHES (#). Use HTML tags: <b>bold</b> and <i>italic</i>.
2. Use the unicode bullet symbol "•" for list items.
3. Clean up timestamps: write simple times like "(14:26 IST)".
4. DO NOT SKIP ANY EMAILS.
5. If an account has NO new emails for this period, write "• No new emails".
6. Separate each account with a clear divider line: `─────────────────────`

STRUCTURE TEMPLATE:
📬 <b>[Account 1 Label & Email]</b>

🎯 <b>Target QA & Python Job Matches</b>
🔴 <b>Company Name</b> (14:26 IST)
• <b>Role:</b> Job Title
• <b>Details:</b> Drive date, location, remote status.

🔴 <b>Important Alerts</b>
• Full explanation.

🟢 <b>Newsletters & Promos</b>
• Topic.

─────────────────────

📬 <b>[Account 2 Label & Email]</b>
• Details for account 2 (or '• No new emails in this period').

Emails separated by account:
{json.dumps(all_accounts_emails, indent=2)}
"""

    result = call_gemini_with_retry(prompt)
    if result:
        return result

    fallback = "<b>Email Overview by Account:</b>\n\n"
    for label, emails in all_accounts_emails.items():
        fallback += f"📬 <b>{label}</b> ({len(emails)} emails):\n"
        if not emails:
            fallback += "• No new emails\n\n"
        else:
            for em in emails[:5]:
                fallback += f"• <b>{em['subject']}</b> ({em['from']})\n"
            fallback += "\n"
    return fallback

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "📅 Today", "callback_data": "range_today"},
                {"text": "⏮️ Yesterday", "callback_data": "range_yesterday"},
                {"text": "🗓️ Last 7 Days", "callback_data": "range_week"}
            ]
        ]
    }
    chunk_size = 4000
    chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

    for idx, chunk in enumerate(chunks):
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML"
        }
        if idx == len(chunks) - 1:
            payload["reply_markup"] = keyboard

        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=req_data, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=15)
        except Exception as e:
            print(f"HTML send failed ({e}), retrying as plain text...")
            clean_plain = re.sub(r'<[^>]+>', '', chunk)
            payload["text"] = clean_plain
            payload.pop("parse_mode", None)
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=req_data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=15)

def main():
    accounts = get_accounts()
    if not accounts:
        return
    all_accounts_data = {}
    for acc in accounts:
        label = f"{acc.get('label', 'Account')} ({acc['email']})"
        emails = fetch_recent_emails(acc["email"], acc["password"], hours=24)
        all_accounts_data[label] = emails

    now_str = datetime.now().strftime("%A, %b %d")
    summary = summarize_with_gemini(all_accounts_data)
    final_text = f"🌅 <b>Daily Briefing — {now_str}</b>\n\n{summary}"
    send_telegram_message(final_text)

if __name__ == "__main__":
    main()
