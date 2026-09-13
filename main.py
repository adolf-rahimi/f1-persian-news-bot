"""
بات خبری فرمول یک فارسی — نسخه رایگان (با بازنویسی خبری واقعی)
------------------------------------------------------------------
این نسخه هیچ هزینه‌ای ندارد:
- از Google Gemini API (رایگان، بدون نیاز به کارت اعتباری) برای بازنویسی خبری حرفه‌ای فارسی استفاده می‌کند
- روی GitHub Actions اجرا می‌شود که برای این نوع کار کاملاً رایگان است

کلید رایگان Gemini را از https://aistudio.google.com/apikey بگیرید.
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
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]           # کلید رایگان از aistudio.google.com/apikey

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

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
    return text[:3500]


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
* متن نهایی (بدون احتساب تیتر و امضا) باید دقیقاً بین ۵ تا ۹ خط کوتاه باشد. این محدودیت جدی و غیرقابل‌نقض است — بیشتر از این حجم قابل‌قبول نیست، حتی اگر خبر منبع طولانی باشد. فقط مهم‌ترین و جذاب‌ترین نکات خبر را انتخاب کن (مثلاً یک یا دو نقل‌قول، نتیجه‌ی اصلی، یک آمار کلیدی) و بقیه‌ی جزئیات را حذف کن — هدف یک پست کوتاه و خوش‌خوان برای کانال تلگرام است، نه گزارش کامل.
* اگر متن منبع، مجموعه‌ای از واکنش‌ها/کامنت‌های غیررسمی کاربران (مثل ردیت یا شبکه‌های اجتماعی) بود، هیچ‌وقت هرکدام را جدا و کلمه‌به‌کلمه ترجمه و نقل‌قول نکن. در عوض، حس و جمع‌بندی کلی واکنش هواداران را در ۱ تا ۲ جمله‌ی روان به زبان خودت خلاصه کن؛ در این حالت هم محدودیت ۵ تا ۹ خط باید کاملاً رعایت شود.
* در کل خروجی، حداکثر ۱ یا ۲ نقل‌قول مستقیم بیاور، نه بیشتر — حتی اگر خبر منبع نقل‌قول‌های زیادی داشته باشد.
* نکات مهم خبر، اعداد، نتایج، نام رانندگان و تیم‌ها حذف نشوند.
* اگر در خبر نقل‌قول مهمی وجود دارد، آن را با 🗣 و به فارسی روان داخل متن بیاور؛ نقل‌قول را بی‌دلیل تغییر نده.
* ابتدای خبر یک تیتر کوتاه و جذاب با 🚨 یا ایموجی مناسب قرار بده.
* در ابتدای هر پاراگراف در صورت نیاز از یک ایموجی مرتبط استفاده کن، اما در استفاده از ایموجی زیاده‌روی نکن.
* از بولد کردن متن استفاده نکن.
* هر نقل‌قول مستقیم را همیشه بین گیومه‌ی « و » قرار بده (نه فقط با ایموجی 🗣، بلکه حتماً داخل « و » هم باشد) تا بعداً به‌صورت جعبه‌ی نقل‌قول جدا نمایش داده شود.
* نام Max Verstappen را همیشه «مکس ورستپن» بنویس.
* نام Isack Hadjar را همیشه «ایزاک هجار» بنویس.
* برای نام‌های زیر (و مشابه آن‌ها) دقیقاً همین املای رایج فارسی رسانه‌های فرمول یک را به‌کار ببر تا اشتباه تایپی یا حدسی رخ ندهد:
  Lewis Hamilton=لوئیس همیلتون, Charles Leclerc=شارل لکلرک, Carlos Sainz=کارلوس ساینز,
  Lando Norris=لندو نوریس, Oscar Piastri=اسکار پیاستری, George Russell=جورج راسل,
  Fernando Alonso=فرناندو آلونسو, Yuki Tsunoda=یوکی تسونودا, Franco Colapinto=فرانکو کولاپینتو,
  Alexander Albon=الکساندر آلبون, Esteban Ocon=استبان اوکان, Pierre Gasly=پی‌یر گاسلی,
  Nico Hulkenberg=نیکو هولکنبرگ, Kimi Antonelli=کیمی آنتونلی, Liam Lawson=لیام لاوسون,
  Arvid Lindblad=آروید لیندبلاد, Gabriel Bortoleto=گابریل بورتولتو,
  Red Bull=رددبول, Ferrari=فراری, Mercedes=مرسدس, McLaren=مک‌لارن, Aston Martin=استون مارتین,
  Williams=ویلیامز, Alpine=آلپاین, Haas=هاس, Racing Bulls=ریسینگ بولز, Sauber=زاوبر, Audi=آئودی
  برای اسامی‌ای که در این لیست نیستند، از نزدیک‌ترین تلفظ رایج فارسی استفاده کن، نه حدس یا ترجمه‌ی اشتباه.
* اصطلاحات تخصصی فرمول یک را دقیقاً با همین معادل رایج ترجمه کن، نه معنی عمومی یا تحت‌اللفظی کلمه:
  circuit/track=پیست, lap=دور, pit stop=پیت‌استاپ, pit lane=لِین پیت, grid=گرید,
  pole position=پول (پوزیشن اول), qualifying=تمرین رسمی (کوالیفای), practice session=جلسه‌ی تمرین,
  paddock=پدوک, podium=سکو, DNF=انصراف از مسابقه, safety car=سیف‌تی‌کار, virtual safety car=سیف‌تی‌کار مجازی,
  DRS=دی‌آراس, undercut=آندرکات, overcut=اورکات, tyre compound=ترکیب لاستیک, stint=استینت,
  penalty=جریمه, drive-through penalty=جریمه‌ی درایو-ترو, yellow flag=پرچم زرد, red flag=پرچم قرمز,
  free practice=تمرین آزاد, sprint race=مسابقه‌ی اسپرینت, constructors' championship=قهرمانی سازندگان,
  drivers' championship=قهرمانی رانندگان
  به‌خصوص مراقب کلمه‌ی «Circuit» باش: همیشه یعنی «پیست»، نه «مدار».
* اگر بخشی از خبر برای مخاطب فارسی‌زبان نیاز به توضیح کوتاه دارد، آن را طبیعی و مختصر توضیح بده.
* از اضافه کردن اطلاعاتی که در متن اصلی وجود ندارد خودداری کن.
* متن باید کاملاً آماده کپی و انتشار در تلگرام باشد.
* در پایان دقیقاً این امضا را قرار بده:

🏎 Persian_Formula1 🏎
فقط متن نهایی خبر را ارائه بده و توضیح اضافه درباره ترجمه یا روند کار نده.
متن خبر:
{full_source}"""

    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 700,
        },
    }
    params = {"key": GEMINI_API_KEY}

    # اگر به محدودیت نرخ Gemini خوردیم (خطای 429)، به‌جای شکست فوری،
    # کمی صبر می‌کنیم و دوباره تلاش می‌کنیم
    max_retries = 3
    for attempt in range(max_retries):
        resp = requests.post(GEMINI_URL, headers=headers, params=params, json=payload, timeout=60)
        if resp.status_code == 429:
            wait_seconds = float(resp.headers.get("retry-after", 15))
            print(f"[هشدار] محدودیت نرخ Gemini (429)؛ {wait_seconds:.0f} ثانیه صبر می‌کنیم (تلاش {attempt + 1}/{max_retries})")
            time.sleep(wait_seconds + 1)
            continue
        resp.raise_for_status()
        break
    else:
        raise RuntimeError("بعد از چند تلاش هم به محدودیت نرخ Gemini خوردیم؛ این خبر رد شد.")

    data = resp.json()
    output = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    return output


PERSIAN_CHARS = re.compile(r"[\u0600-\u06FF]")


def is_mostly_persian(text: str) -> bool:
    """بررسی می‌کند آیا خروجی واقعاً فارسی است یا مدل به اشتباه انگلیسی برگردانده."""
    if not text:
        return False
    persian_count = len(PERSIAN_CHARS.findall(text))
    return persian_count > len(text) * 0.3  # حداقل ۳۰٪ کاراکترها باید فارسی باشند


def rewrite_in_persian_safe(entry: dict) -> str:
    """rewrite_in_persian را صدا می‌زند و اگر خروجی فارسی نبود، یک‌بار دیگر تلاش می‌کند."""
    for attempt in range(2):
        output = rewrite_in_persian(entry)
        if is_mostly_persian(output):
            return output
        print(f"[هشدار] خروجی مدل فارسی نبود (تلاش {attempt + 1})، دوباره تلاش می‌شود...")
    raise RuntimeError("مدل نتوانست خروجی فارسی معتبر تولید کند؛ از پست‌شدن این خبر صرف‌نظر شد.")


# ---------------------------------------------------------------------------
# قالب‌بندی: نقل‌قول‌های داخل « و » به جعبه‌ی رسمی Blockquote تلگرام تبدیل می‌شوند
# ---------------------------------------------------------------------------
def format_for_telegram(raw_text: str, article_link: str) -> str:
    safe_text = html.escape(raw_text)

    def to_blockquote(match):
        return f"<blockquote>{match.group(1).strip()}</blockquote>"

    body = re.sub(r"«(.+?)»", to_blockquote, safe_text, flags=re.S)

    # یک لینک نامرئی (با کاراکتر با-عرض-صفر) به ابتدای پیام اضافه می‌شود تا
    # تلگرام خودش عکس خبر را از صفحه‌ی منبع به‌صورت پیش‌نمایش نشان دهد،
    # بدون اینکه لینک قابل‌مشاهده باشد یا خود عکس را دانلود/آپلود کنیم.
    hidden_preview = f'<a href="{html.escape(article_link)}">&#8203;</a>'

    return hidden_preview + body


# ---------------------------------------------------------------------------
# ارسال پیام به کانال تلگرام
# ---------------------------------------------------------------------------
TELEGRAM_MAX_LEN = 4096


def post_to_telegram(text: str):
    if len(text) > TELEGRAM_MAX_LEN:
        print(f"[هشدار] پیام طولانی بود ({len(text)} کاراکتر)، کوتاه شد.")
        # کوتاه‌کردن از انتها و نگه‌داشتن امضا در صورت امکان
        text = text[: TELEGRAM_MAX_LEN - 1].rstrip() + "…"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,  # اجازه می‌دهیم پیش‌نمایش (عکس خبر) نمایش داده شود
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
            persian_text = rewrite_in_persian_safe(entry)
            message = format_for_telegram(persian_text, entry["link"])
            post_to_telegram(message)
            posted_ids.add(entry["id"])
            save_posted_ids(posted_ids)
            time.sleep(2)
        except Exception as e:
            print(f"[خطا] پردازش خبر ناموفق بود: {e}")


if __name__ == "__main__":
    run_once()
