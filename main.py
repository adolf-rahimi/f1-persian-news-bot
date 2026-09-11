"""
بات خبری فرمول یک فارسی — نسخه رایگان
---------------------------------------
این نسخه هیچ هزینه‌ای ندارد:
- به‌جای Claude API از کتابخانه رایگان ترجمه (Google Translate غیررسمی) استفاده می‌کند
- روی GitHub Actions اجرا می‌شود که برای این نوع کار کاملاً رایگان است

نکته: چون از ترجمه ماشینی ساده استفاده می‌شود (نه بازنویسی هوشمند خبری)،
کیفیت متن فارسی خوب و قابل‌فهم است ولی به روانی نسخه‌ی مبتنی بر Claude نیست.
اگر بعداً خواستید کیفیت را ارتقا دهید، کافی‌ست بگویید تا نسخه‌ی AI را جایگزین کنم.
"""

import os
import json
import time
import re
import html
import feedparser
import requests
from deep_translator import GoogleTranslator

# ---------------------------------------------------------------------------
# تنظیمات - این مقادیر باید به‌صورت Secret در گیت‌هاب ست شوند (رایگان)
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]      # توکن رایگان از BotFather
TELEGRAM_CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]    # مثلا: @your_channel

# منابع خبری فرمول یک (RSS) — رایگان و بدون نیاز به کلید
RSS_FEEDS = [
    "https://www.autosport.com/rss/f1/news/",
    "https://www.motorsport.com/rss/f1/news/",
    "https://feed.racefans.net/",
]

POSTED_IDS_FILE = "posted_ids.json"
MAX_STORED_IDS = 500

translator = GoogleTranslator(source="en", target="fa")


# ---------------------------------------------------------------------------
# مدیریت خبرهای قبلاً منتشرشده
# ---------------------------------------------------------------------------
def load_posted_ids() -> set:
    if os.path.exists(POSTED_IDS_FILE):
        with open(POSTED_IDS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_posted_ids(ids: set):
    ids_list = list(ids)[-MAX_STORED_IDS:]
    with open(POSTED_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(ids_list, f, ensure_ascii=False)


# ---------------------------------------------------------------------------
# گرفتن خبرهای تازه از RSS
# ---------------------------------------------------------------------------
def clean_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_latest_entries():
    entries = []
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:5]:
                entries.append({
                    "id": entry.get("id") or entry.get("link"),
                    "title": entry.get("title", ""),
                    "summary": clean_html(
                        entry.get("summary", entry.get("description", ""))
                    )[:500],
                    "link": entry.get("link", ""),
                    "source": feed.feed.get("title", feed_url),
                })
        except Exception as e:
            print(f"[هشدار] خطا در خواندن {feed_url}: {e}")
    return entries


# ---------------------------------------------------------------------------
# ترجمه رایگان به فارسی و قالب‌بندی خبر
# ---------------------------------------------------------------------------
def translate_safe(text: str) -> str:
    if not text:
        return ""
    try:
        # گوگل‌ترنسلیت غیررسمی محدودیت طول دارد؛ در صورت نیاز تکه‌تکه ترجمه می‌کنیم
        if len(text) > 450:
            text = text[:450]
        return translator.translate(text)
    except Exception as e:
        print(f"[هشدار] خطای ترجمه: {e}")
        return text  # اگر ترجمه ناموفق بود، متن انگلیسی برگردانده می‌شود


def format_message(entry: dict) -> str:
    title_fa = translate_safe(entry["title"])
    summary_fa = translate_safe(entry["summary"])

    message = (
        f"🏎️ {title_fa}\n\n"
        f"{summary_fa}\n\n"
        f"منبع: {entry['source']}\n"
        f"{entry['link']}"
    )
    return message


# ---------------------------------------------------------------------------
# ارسال پیام به کانال تلگرام
# ---------------------------------------------------------------------------
def post_to_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text,
        "disable_web_page_preview": False,
    }
    resp = requests.post(url, data=payload, timeout=20)
    if not resp.ok:
        print(f"[خطا] ارسال به تلگرام ناموفق بود: {resp.status_code} - {resp.text}")
    else:
        print("[موفق] خبر در کانال منتشر شد.")


# ---------------------------------------------------------------------------
# اجرای اصلی
# ---------------------------------------------------------------------------
def run_once():
    posted_ids = load_posted_ids()
    entries = fetch_latest_entries()

    new_entries = [e for e in entries if e["id"] and e["id"] not in posted_ids]

    if not new_entries:
        print("خبر جدیدی برای انتشار وجود ندارد.")
        return

    for entry in new_entries:
        try:
            print(f"در حال پردازش: {entry['title']}")
            message = format_message(entry)
            post_to_telegram(message)
            posted_ids.add(entry["id"])
            save_posted_ids(posted_ids)
            time.sleep(3)
        except Exception as e:
            print(f"[خطا] پردازش خبر ناموفق بود: {e}")


if __name__ == "__main__":
    run_once()
