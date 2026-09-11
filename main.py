"""
بات خبری فرمول یک فارسی — نسخه رایگان (با بازنویسی خبری واقعی)
------------------------------------------------------------------
این نسخه هیچ هزینه‌ای ندارد:
- از Groq API (رایگان، بدون نیاز به کارت اعتباری) برای بازنویسی خبری حرفه‌ای فارسی استفاده می‌کند
- روی GitHub Actions اجرا می‌شود که برای این نوع کار کاملاً رایگان است

کلید رایگان Groq را از https://console.groq.com بگیرید.
"""

import os
import json
import time
import re
import html
import feedparser
import requests

# ---------------------------------------------------------------------------
# تنظیمات - این مقادیر باید به‌صورت Secret در گیت‌هاب ست شوند
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]              # کلید رایگان از console.groq.com

GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# منابع خبری فرمول یک (RSS)
RSS_FEEDS = [
    "https://www.motorsport.com/rss/f1/news/",
]

POSTED_IDS_FILE = "posted_ids.json"
MAX_STORED_IDS = 500

# هر اجرا فقط همین تعداد خبر جدید را پست می‌کند
MAX_POSTS_PER_RUN = 1


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
                    ),
                    "link": entry.get("link", ""),
                    "source": feed.feed.get("title", feed_url),
                    "published_parsed": entry.get("published_parsed"),
                })
        except Exception as e:
            print(f"[هشدار] خطا در خواندن {feed_url}: {e}")
    return entries


# ---------------------------------------------------------------------------
# بازنویسی خبری کامل به فارسی با Groq (رایگان)
# ---------------------------------------------------------------------------
def rewrite_in_persian(entry: dict) -> str:
    prompt = f"""تو یک خبرنگار حرفه‌ای فرمول یک هستی که برای یک کانال معتبر تلگرامی فارسی‌زبان می‌نویسی.

خبر منبع (انگلیسی):
عنوان: {entry['title']}
متن: {entry['summary']}

این خبر را به یک مطلب خبری کامل، روان و حرفه‌ای فارسی بازنویسی کن. دقیقاً مثل سبک زیر:

- خط اول: یک جمله‌ی کوتاه و جذاب (می‌تواند نقل‌قول یا نکته‌ی کلیدی خبر باشد) که نقش تیتر را دارد
- بعد از آن، بدون فاصله‌ی اضافه، متن کامل خبر در ۱ تا ۲ پاراگراف پیوسته می‌آید — نه خلاصه و نه ناقص، بلکه بازگویی کامل تمام نکات مهم خبر
- نقل‌قول‌های مستقیم را داخل گیومه «» بیاور
- نام افراد و تیم‌ها را به فارسی رایج بنویس (مثلا: مکس فرستاپن، رددبول، فرناندو آلونسو)
- لحن کاملاً خبری، حرفه‌ای و بدون اغراق یا نظر شخصی
- هیچ خط «منبع» یا لینکی در انتها نیاور — فقط خود متن خبر
- هیچ توضیح اضافه، Markdown، یا مقدمه‌ای ننویس؛ فقط خروجی نهایی فارسی را بده"""

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.6,
        "max_tokens": 900,
    }
    resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# ارسال پیام به کانال تلگرام
# ---------------------------------------------------------------------------
def post_to_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text,
        "disable_web_page_preview": True,
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

    entries.sort(key=lambda e: e.get("published_parsed") or 0, reverse=True)

    new_entries = [e for e in entries if e["id"] and e["id"] not in posted_ids]
    new_entries = new_entries[:MAX_POSTS_PER_RUN]

    if not new_entries:
        print("خبر جدیدی برای انتشار وجود ندارد.")
        return

    for entry in new_entries:
        try:
            print(f"در حال پردازش: {entry['title']}")
            persian_text = rewrite_in_persian(entry)
            post_to_telegram(persian_text)
            posted_ids.add(entry["id"])
            save_posted_ids(posted_ids)
            time.sleep(2)
        except Exception as e:
            print(f"[خطا] پردازش خبر ناموفق بود: {e}")


if __name__ == "__main__":
    run_once()
