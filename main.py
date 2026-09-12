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
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# تنظیمات - این مقادیر باید به‌صورت Secret در گیت‌هاب ست شوند
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]              # کلید رایگان از console.groq.com

GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# امضایی که آخر هر پست اضافه می‌شود
CHANNEL_SIGNATURE = TELEGRAM_CHANNEL_ID.lstrip("@")

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
# گرفتن متن کامل خود صفحه‌ی خبر (نه فقط خلاصه‌ی RSS)
# ---------------------------------------------------------------------------
def fetch_full_article(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"[هشدار] گرفتن صفحه‌ی کامل خبر ناموفق بود: {e}")
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")

    # حذف بخش‌های غیرمرتبط (اسکریپت، استایل، منو، فوتر، تبلیغات)
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()

    # اول تلاش برای پیدا کردن تگ <article>؛ اگر نبود، همه‌ی پاراگراف‌های صفحه
    container = soup.find("article") or soup

    paragraphs = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    text = " ".join(p for p in paragraphs if len(p) > 30)  # پاراگراف‌های خیلی کوتاه (اغلب تبلیغ/کپشن) حذف شود

    # محدود کردن طول متن برای جلوگیری از عبور از محدودیت توکن مدل
    return text[:6000]


# ---------------------------------------------------------------------------
# بازنویسی خبری کامل به فارسی با Groq (رایگان)
# ---------------------------------------------------------------------------
def rewrite_in_persian(entry: dict) -> str:
    source_text = entry.get("full_text") or entry["summary"]

    prompt = f"""تو یک خبرنگار حرفه‌ای فرمول یک هستی که برای یک کانال معتبر تلگرامی فارسی‌زبان می‌نویسی.

خبر منبع (انگلیسی) — تنها منبع مجاز اطلاعات توست:
عنوان: {entry['title']}
متن کامل خبر: {source_text}

این خبر را کامل بخوان و به یک مطلب خبری فارسی، روان و خلاصه‌شده بازنویسی کن — یعنی تمام نکات مهم خبر (نه فقط جمله‌ی اول) را در قالب چند پاراگراف کوتاه فارسی پوشش بده. خروجی باید دقیقاً این ساختار را داشته باشد:

خط ۱: یک تیتر کوتاه و خبری بر اساس همین خبر (بدون گیومه، بدون ایموجی)
خط خالی
سپس بدنه‌ی خبر در ۲ تا ۴ پاراگراف کوتاه که خلاصه‌ای کامل از کل متن منبع باشد

قوانین حیاتی و غیرقابل‌نقض:
- فقط از اطلاعاتی استفاده کن که عیناً در «متن کامل خبر» بالا آمده. هیچ جزئیات، عدد، تاریخ، مکان، یا نقل‌قولی که در متن منبع نیست، اضافه نکن — حتی اگر به نظر منطقی یا قابل‌قبول برسد
- اگر متن منبع نقل‌قول مستقیم ندارد، تو هم نقل‌قول اختراع نکن — فقط رویداد را روایت کن
- اگر نقل‌قول مستقیم در متن منبع وجود دارد، همان را (به‌صورت ترجمه‌شده و وفادار به معنا، نه کپی کلمه‌به‌کلمه‌ی انگلیسی) داخل گیومه‌ی « و » در یک پاراگراف جدا بیاور
- این کار باید خلاصه‌سازی و بازنویسی کامل به زبان خودت باشد، نه ترجمه‌ی تحت‌اللفظی جمله‌به‌جمله
- نام افراد و تیم‌ها را به فارسی رایج بنویس (مثلا: مکس فرستاپن، رددبول، فرناندو آلونسو، فرمول یک)
- لحن کاملاً خبری، حرفه‌ای، بدون اغراق یا نظر شخصی
- هیچ خط «منبع»، لینک، هشتگ یا ایموجی نیاور
- هیچ توضیح اضافه، Markdown، یا مقدمه‌ای ننویس؛ فقط خروجی نهایی فارسی (تیتر + بدنه) را بده"""

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 1300,
    }
    resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# قالب‌بندی HTML برای تلگرام (تیتر بولد + نقل‌قول‌ها به‌صورت Blockquote + امضا)
# ---------------------------------------------------------------------------
def format_for_telegram(raw_text: str) -> str:
    parts = raw_text.strip().split("\n", 1)
    title = parts[0].strip()
    body = parts[1].strip() if len(parts) > 1 else ""

    # اول کاراکترهای خاص HTML را امن می‌کنیم تا خطای پارس تلگرام رخ ندهد
    title_safe = html.escape(title)
    body_safe = html.escape(body)

    # پاراگراف‌هایی که داخل گیومه‌ی « و » هستند را به Blockquote تبدیل می‌کنیم
    def to_blockquote(match):
        return f"<blockquote>{match.group(1).strip()}</blockquote>"

    body_html = re.sub(r"«(.+?)»", to_blockquote, body_safe, flags=re.S)

    message = f"<b>{title_safe}</b>\n\n{body_html}\n\n🏁 {CHANNEL_SIGNATURE} 🏁"
    return message


# ---------------------------------------------------------------------------
# ارسال پیام به کانال تلگرام
# ---------------------------------------------------------------------------
def post_to_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
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
            entry["full_text"] = fetch_full_article(entry["link"])
            persian_text = rewrite_in_persian(entry)
            message = format_for_telegram(persian_text)
            post_to_telegram(message)
            posted_ids.add(entry["id"])
            save_posted_ids(posted_ids)
            time.sleep(2)
        except Exception as e:
            print(f"[خطا] پردازش خبر ناموفق بود: {e}")


if __name__ == "__main__":
    run_once()
