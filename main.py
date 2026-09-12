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
    full_source = f"{entry['title']}\n\n{source_text}"

    prompt = f"""متن انگلیسی خبر فرمول یک را به فارسی ترجمه و برای انتشار در کانال تلگرامی «Persian_Formula1» بازنویسی کن.
قوانین:

* ترجمه روان، طبیعی و حرفه‌ای باشد؛ ترجمه تحت‌اللفظی نباشد.
* لحن شبیه اخبار Motorsport.com و رسانه‌های معتبر فرمول یک باشد، نه لحن تلویزیونی یا عامیانه.
* متن نهایی حدود ۵ تا ۸ خط/پاراگراف کوتاه باشد و بیش از حد طولانی نشود.
* نکات مهم خبر، اعداد، نتایج، نام رانندگان و تیم‌ها حذف نشوند.
* اگر در خبر نقل‌قول مهمی وجود دارد، آن را با 🗣 و به فارسی روان داخل متن بیاور؛ نقل‌قول را بی‌دلیل تغییر نده.
* ابتدای خبر یک تیتر کوتاه و جذاب با 🚨 یا ایموجی مناسب قرار بده.
* در ابتدای هر پاراگراف در صورت نیاز از یک ایموجی مرتبط استفاده کن، اما در استفاده از ایموجی زیاده‌روی نکن.
* از بولد کردن متن استفاده نکن.
* نام Max Verstappen را همیشه «مکس ورستپن» بنویس.
* نام Isack Hadjar را همیشه «ایزاک هجار» بنویس.
* نام تیم‌ها و اصطلاحات F1 را به شکل رایج و درست فارسی بنویس.
* اگر بخشی از خبر برای مخاطب فارسی‌زبان نیاز به توضیح کوتاه دارد، آن را طبیعی و مختصر توضیح بده.
* از اضافه کردن اطلاعاتی که در متن اصلی وجود ندارد خودداری کن.
* متن باید کاملاً آماده کپی و انتشار در تلگرام باشد.
* در پایان دقیقاً این امضا را قرار بده:

🏎 Persian_Formula1 🏎
فقط متن نهایی خبر را ارائه بده و توضیح اضافه درباره ترجمه یا روند کار نده.
متن خبر:
{full_source}"""

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": 1300,
    }
    resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# ارسال پیام به کانال تلگرام (متن ساده، چون مدل خودش ایموجی و امضا را می‌سازد)
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
            entry["full_text"] = fetch_full_article(entry["link"])
            persian_text = rewrite_in_persian(entry)
            post_to_telegram(persian_text)
            posted_ids.add(entry["id"])
            save_posted_ids(posted_ids)
            time.sleep(2)
        except Exception as e:
            print(f"[خطا] پردازش خبر ناموفق بود: {e}")


if __name__ == "__main__":
    run_once()
