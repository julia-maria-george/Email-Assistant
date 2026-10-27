import os
import re
import sys
import time
import json
import email
import imaplib
import threading
import urllib.request
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from email.header import decode_header
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

MODELS_LIST = [
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-2.5-pro"
]

ACTIVE_MESSAGES = {}

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Daily Email Assistant Bot is Running 24/7 on Render!")

    def log_message(self, format, *args):
        pass

def start_health_check_server():
    port = int(os.getenv("PORT", 10000))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        print(f"Health-check HTTP server listening on port {port} for Render...")
        server.serve_forever()
    except Exception as e:
        print(f"Health server info: {e}")

def send_telegram_raw(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=req_data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass

def delete_message(chat_id, message_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteMessage"
    payload = {"chat_id": chat_id, "message_id": message_id}
    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=req_data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass

def schedule_delete_after_delay(chat_id, message_ids, delay=60):
    def _worker():
        time.sleep(delay)
        for mid in message_ids:
            delete_message(chat_id, mid)
    threading.Thread(target=_worker, daemon=True).start()

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
    return " ".join(lines)[:3000]

def extract_relevant_urls(raw_text):
    """Extract clean application/job URLs, ignoring tracking/unsubscribe links."""
    urls = re.findall(r'https?://[^\s<>"\'\)]+', raw_text)
    clean = []
    ignore_keywords = [
        'unsubscribe', 'optout', 'privacy', 'terms', 'facebook', 'twitter', 
        'instagram', 'youtube', 'linkedin.com/help', 'support', 'pixel', 'logo',
        'schemas.microsoft.com', 'w3.org'
    ]
    for u in urls:
        u_lower = u.lower()
        if not any(k in u_lower for k in ignore_keywords) and len(u) > 15:
            if u not in clean:
                clean.append(u)
    return clean[:4]

def fetch_emails_for_range(email_address, password, timeframe="today"):
    emails_data = []
    now = datetime.now()

    if timeframe == "today":
        search_query = f'(SINCE "{now.strftime("%d-%b-%Y")}")'
    elif timeframe == "yesterday":
        yesterday = now - timedelta(days=1)
        search_query = f'(SINCE "{yesterday.strftime("%d-%b-%Y")}" BEFORE "{now.strftime("%d-%b-%Y")}")'
    elif timeframe == "week":
        week_ago = now - timedelta(days=7)
        search_query = f'(SINCE "{week_ago.strftime("%d-%b-%Y")}")'
    else:
        search_query = f'(SINCE "{now.strftime("%d-%b-%Y")}")'

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email_address, password)
        mail.select("INBOX", readonly=True)

        status, messages = mail.search(None, search_query)
        if status != "OK" or not messages[0]:
            mail.logout()
            return emails_data

        message_ids = messages[0].split()
        limit = 35 if timeframe == "week" else 25
        message_ids = message_ids[-limit:]

        for msg_id in reversed(message_ids):
            try:
                res, data = mail.fetch(msg_id, "(RFC822)")
                if res != "OK":
                    continue
                msg = email.message_from_bytes(data[0][1])
                subject = decode_mime_words(msg.get("Subject", "No Subject"))
                from_ = decode_mime_words(msg.get("From", "Unknown Sender"))
                date_str = msg.get("Date", "")
                message_id_header = msg.get("Message-ID", "").strip("<> ")

                gmail_link = ""
                if message_id_header:
                    gmail_link = f"https://mail.google.com/mail/#search/rfc822msgid%3A{urllib.parse.quote(message_id_header)}"

                body_snippet = ""
                all_text_for_urls = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        content_disposition = str(part.get("Content-Disposition"))
                        if content_type in ["text/plain", "text/html"] and "attachment" not in content_disposition:
                            payload = part.get_payload(decode=True)
                            if payload:
                                text_str = clean_body_text(payload)
                                all_text_for_urls += " " + text_str
                                if not body_snippet and content_type == "text/plain":
                                    body_snippet = text_str
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body_snippet = clean_body_text(payload)
                        all_text_for_urls = body_snippet

                links = extract_relevant_urls(all_text_for_urls)

                emails_data.append({
                    "from": from_,
                    "subject": subject,
                    "date": date_str,
                    "snippet": body_snippet[:1500],
                    "job_apply_link": links[0] if links else "",
                    "gmail_link": gmail_link
                })
            except Exception:
                continue

        mail.logout()
    except Exception as e:
        print(f"Error fetching for {email_address}: {e}")

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

def summarize_with_gemini(all_accounts_emails, timeframe_key):
    prompt = f"""
You are Julia's personal email executive assistant. 
Create an informative, comprehensive, and beautifully formatted email digest for Telegram.

CRITICAL REQUIREMENT - STRICT SEPARATION BY ACCOUNT & CLEAN LINKS:
1. NO MARKDOWN ASTERISKS (*) OR HASHES (#). Use HTML tags: <b>bold</b> and <i>italic</i>.
2. Use the unicode bullet symbol "•" for list items.
3. Clean up timestamps: write simple times like "(14:26 IST)".
4. DO NOT SKIP ANY EMAILS.
5. If an account has NO new emails for this period, write "• No new emails in this period".

CRITICAL HYPERLINK RULES:
- For job matches: If 'job_apply_link' is available, attach a clean, minimal hyperlink to the role title or a tiny tag:
  • <b>Role:</b> Job Title (<a href="URL">View / Apply ↗</a>)
- For alerts: You may optionally add a clean (<a href="GMAIL_URL">Open ↗</a>) if gmail_link is present.
- NEVER display raw, long URLs. ALWAYS use clean anchor text like `<a href="...">View / Apply ↗</a>` or `<a href="...">Open ↗</a>`. Keep it super clean without cluttering the description.

STRUCTURE TEMPLATE:
📬 <b>[Account Label & Email]</b>

🎯 <b>Target QA & Python Job Matches</b>
🔴 <b>Company Name</b> (14:26 IST)
• <b>Role:</b> Job Title (<a href="URL">Apply ↗</a>)
• <b>Details:</b> Drive date, location, remote status.

🔴 <b>Important Alerts</b>
• Google Security: Full explanation (<a href="GMAIL_URL">Open ↗</a>).

🟢 <b>Newsletters & Promos</b>
• Topic description.

Emails separated by account ({timeframe_key}):
{json.dumps(all_accounts_emails, indent=2)}
"""

    result = call_gemini_with_retry(prompt)
    if result:
        return result

    fallback = "<b>Email Overview by Account:</b>\n\n"
    for label, emails in all_accounts_emails.items():
        fallback += f"📬 <b>{label}</b> ({len(emails)} emails):\n"
        if not emails:
            fallback += "• No new emails in this period\n\n"
        else:
            for em in emails[:5]:
                link_part = f" (<a href='{em['job_apply_link']}'>Apply ↗</a>)" if em.get('job_apply_link') else ""
                fallback += f"• <b>{em['subject']}</b>{link_part} ({em['from']})\n"
            fallback += "\n"
    return fallback

# KEYBOARDS
def get_account_keyboard():
    accounts = get_accounts()
    buttons = []
    for idx, acc in enumerate(accounts):
        lbl = acc.get("label", f"Account {idx+1}")
        buttons.append([{"text": f"📬 {lbl} ({acc['email']})", "callback_data": f"pick_acc_{idx}"}])
    if len(accounts) > 1:
        buttons.append([{"text": "🌐 Check Both Accounts", "callback_data": "pick_acc_all"}])
    return {"inline_keyboard": buttons}

def get_timeframe_keyboard(acc_target):
    return {
        "inline_keyboard": [
            [
                {"text": "📅 Today", "callback_data": f"run_{acc_target}_today"},
                {"text": "⏮️ Yesterday", "callback_data": f"run_{acc_target}_yesterday"},
                {"text": "🗓️ Last 7 Days", "callback_data": f"run_{acc_target}_week"}
            ],
            [
                {"text": "🔙 Switch Account", "callback_data": "menu_accounts"}
            ]
        ]
    }

def send_message_with_markup(chat_id, text, keyboard_markup):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    old_mids = ACTIVE_MESSAGES.get(chat_id, [])
    if old_mids:
        schedule_delete_after_delay(chat_id, old_mids, delay=60)

    new_mids = []
    chunk_size = 4000
    chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

    for idx, chunk in enumerate(chunks):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if idx == len(chunks) - 1 and keyboard_markup:
            payload["reply_markup"] = keyboard_markup

        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=req_data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                res_data = json.loads(resp.read().decode())
                if res_data.get("ok"):
                    new_mids.append(res_data["result"]["message_id"])
        except Exception:
            clean_plain = re.sub(r'<[^>]+>', '', chunk)
            payload["text"] = clean_plain
            payload.pop("parse_mode", None)
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=req_data, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    res_data = json.loads(resp.read().decode())
                    if res_data.get("ok"):
                        new_mids.append(res_data["result"]["message_id"])
            except Exception:
                pass

    ACTIVE_MESSAGES[chat_id] = new_mids

def answer_callback(callback_query_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id, "text": text}
    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=req_data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass

def show_accounts_menu(chat_id):
    text = (
        "👋 <b>Hi Julia!</b>\n\n"
        "Which email account would you like to check?"
    )
    send_message_with_markup(chat_id, text, get_account_keyboard())

def show_timeframe_menu(chat_id, acc_target):
    accounts = get_accounts()
    if acc_target == "all":
        acc_name = "Both Accounts"
    else:
        idx = int(acc_target)
        acc_name = f"{accounts[idx].get('label', 'Account')} ({accounts[idx]['email']})"

    text = (
        f"Selected: 📬 <b>{acc_name}</b>\n\n"
        "Which timeframe would you like to summarize?"
    )
    send_message_with_markup(chat_id, text, get_timeframe_keyboard(acc_target))

def execute_summary(chat_id, acc_target, timeframe_key):
    names = {
        "today": "Today",
        "yesterday": "Yesterday",
        "week": "the Last 7 Days"
    }
    desc = names.get(timeframe_key, "Selected Period")

    accounts = get_accounts()
    all_data = {}

    if acc_target == "all":
        target_accounts = accounts
        header_title = f"Both Accounts — {desc}"
    else:
        idx = int(acc_target)
        target_accounts = [accounts[idx]]
        header_title = f"{accounts[idx].get('label', 'Account')} — {desc}"

    for acc in target_accounts:
        label = f"{acc.get('label', 'Account')} ({acc['email']})"
        emails = fetch_emails_for_range(acc["email"], acc["password"], timeframe_key)
        all_data[label] = emails

    summary = summarize_with_gemini(all_data, timeframe_key)
    final_text = f"📊 <b>Email Digest — {header_title}</b>\n\n{summary}"
    send_message_with_markup(chat_id, final_text, get_timeframe_keyboard(acc_target))

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--menu":
        show_accounts_menu(TELEGRAM_CHAT_ID)
    else:
        threading.Thread(target=start_health_check_server, daemon=True).start()
        print(f"Bot listening with link extraction for User ID: {TELEGRAM_CHAT_ID}...")
        offset = 0
        while True:
            try:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={offset}&timeout=20"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode())
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1

                        if "callback_query" in update:
                            cb = update["callback_query"]
                            cb_id = cb["id"]
                            data_key = cb.get("data", "")
                            from_id = cb["from"]["id"]

                            if from_id != TELEGRAM_CHAT_ID:
                                answer_callback(cb_id, "⛔ Access Denied.")
                                continue

                            if data_key == "menu_accounts":
                                answer_callback(cb_id, "Returning to accounts...")
                                show_accounts_menu(from_id)

                            elif data_key.startswith("pick_acc_"):
                                acc_target = data_key.replace("pick_acc_", "")
                                answer_callback(cb_id, "Account selected!")
                                show_timeframe_menu(from_id, acc_target)

                            elif data_key.startswith("run_"):
                                parts = data_key.split("_")
                                acc_target = parts[1]
                                timeframe = parts[2]
                                answer_callback(cb_id, f"Fetching {timeframe}...")
                                execute_summary(from_id, acc_target, timeframe)

                        elif "message" in update:
                            msg = update["message"]
                            chat_id = msg["chat"]["id"]

                            if chat_id != TELEGRAM_CHAT_ID:
                                send_telegram_raw(chat_id, "⛔ Access Denied. Private assistant.")
                                continue

                            show_accounts_menu(chat_id)

            except Exception as e:
                print(f"Polling loop notice: {e}")
                import time
                time.sleep(2)
