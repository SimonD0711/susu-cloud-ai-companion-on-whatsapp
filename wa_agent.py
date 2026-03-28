#!/usr/bin/env python3
import base64
import difflib
import html
import subprocess
import shlex
import json
import os
import random
import re
import sqlite3
import sys
import threading
import traceback
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None


DEFAULT_BASE_DIR = Path(os.environ.get("WA_BASE_DIR", "/var/www/html"))
BASE_DIR = DEFAULT_BASE_DIR if DEFAULT_BASE_DIR.exists() else Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("WA_DB_PATH", str(BASE_DIR / "wa_agent.db")))

VERIFY_TOKEN = os.environ.get("WA_VERIFY_TOKEN", "")
ACCESS_TOKEN = os.environ.get("WA_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("WA_PHONE_NUMBER_ID", "")
GRAPH_VERSION = os.environ.get("WA_GRAPH_VERSION", "v22.0")
TYPING_INDICATOR_DELAY_SECONDS = float(os.environ.get("WA_TYPING_INDICATOR_DELAY_SECONDS", "0.5"))
TYPING_INDICATOR_REFRESH_SECONDS = float(os.environ.get("WA_TYPING_INDICATOR_REFRESH_SECONDS", "4.0"))
REPLY_JOB_POLL_SECONDS = float(os.environ.get("WA_REPLY_JOB_POLL_SECONDS", "0.05"))
REPLY_JOB_TERMINATE_GRACE_SECONDS = float(os.environ.get("WA_REPLY_JOB_TERMINATE_GRACE_SECONDS", "0.25"))
PROACTIVE_ENABLED = os.environ.get("WA_PROACTIVE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
PROACTIVE_SCAN_SECONDS = int(os.environ.get("WA_PROACTIVE_SCAN_SECONDS", "300"))
PROACTIVE_MIN_SILENCE_MINUTES = int(os.environ.get("WA_PROACTIVE_MIN_SILENCE_MINUTES", "45"))
PROACTIVE_COOLDOWN_MINUTES = int(os.environ.get("WA_PROACTIVE_COOLDOWN_MINUTES", "180"))
PROACTIVE_REPLY_WINDOW_MINUTES = int(os.environ.get("WA_PROACTIVE_REPLY_WINDOW_MINUTES", "90"))
PROACTIVE_CONVERSATION_WINDOW_HOURS = int(os.environ.get("WA_PROACTIVE_CONVERSATION_WINDOW_HOURS", "24"))
PROACTIVE_MAX_PER_SERVICE_DAY = int(os.environ.get("WA_PROACTIVE_MAX_PER_SERVICE_DAY", "2"))
PROACTIVE_MIN_INBOUND_MESSAGES = int(os.environ.get("WA_PROACTIVE_MIN_INBOUND_MESSAGES", "8"))

SUSU_LOCKED_RELAY_MODEL = "claude-opus-4-6"
RELAY_API_KEY = os.environ.get("WA_RELAY_API_KEY", "")
RELAY_MODEL = os.environ.get("WA_RELAY_MODEL", SUSU_LOCKED_RELAY_MODEL)
RELAY_FALLBACK_MODEL = os.environ.get("WA_RELAY_FALLBACK_MODEL", "claude-sonnet-4-6")
RELAY_BASE_URL = os.environ.get("WA_RELAY_BASE_URL", "https://apiapipp.com/v1")

GEMINI_API_KEY = os.environ.get("WA_GEMINI_API_KEY") or os.environ.get("GOOGLE_KEY", "")
GEMINI_MODEL = os.environ.get("WA_GEMINI_MODEL", "gemini-2.5-flash")

MINIMAX_API_KEY = os.environ.get("WA_MINIMAX_API_KEY", "")
MINIMAX_MODEL = os.environ.get("WA_MINIMAX_MODEL", "MiniMax-M2.5")
MINIMAX_BASE_URL = os.environ.get("WA_MINIMAX_BASE_URL", "https://api.minimaxi.com/v1")

GROQ_API_KEY = os.environ.get("WA_GROQ_API_KEY") or os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("WA_GROQ_MODEL", "llama-3.3-70b-versatile")
X_BEARER_TOKEN = os.environ.get("WA_X_BEARER_TOKEN", "")
YOUTUBE_API_KEY = os.environ.get("WA_YOUTUBE_API_KEY", "")
REDDIT_USER_AGENT = os.environ.get("WA_REDDIT_USER_AGENT", "SusuCloud/1.0")

ADMIN_WA_ID = os.environ.get("WA_ADMIN_WA_ID", "85259576670")
CLAUDE_WA_ID = os.environ.get("WA_CLAUDE_WA_ID", "8618704499898")
CLAUDE_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://apiapipp.com")

# 安全詞
MAX_IMAGE_ATTACHMENTS = int(os.environ.get("WA_MAX_IMAGE_ATTACHMENTS", "3"))
MAX_IMAGE_BYTES = int(os.environ.get("WA_MAX_IMAGE_BYTES", str(5 * 1024 * 1024)))
MAX_INLINE_REPLY_EMOJIS = int(os.environ.get("WA_MAX_INLINE_REPLY_EMOJIS", "1"))

if ZoneInfo:
    try:
        HK_TZ = ZoneInfo("Asia/Hong_Kong")
    except Exception:
        HK_TZ = timezone(timedelta(hours=8))
else:
    HK_TZ = timezone(timedelta(hours=8))
PUNCTUATION = "。！？!?~～…"
HKO_OPEN_DATA_BASE_URL = "https://data.weather.gov.hk/weatherAPI/opendata/weather.php"
LIVE_LOOKUP_CACHE_SECONDS = 180
LIVE_SEARCH_ROUTER_CACHE_SECONDS = 120
_live_lookup_cache = {}
_live_lookup_cache_lock = threading.Lock()
_reply_worker_states = {}
_reply_worker_states_lock = threading.Lock()

WEATHER_QUERY_KEYWORDS = (
    "天氣", "天气", "weather", "氣溫", "气温", "幾度", "几度", "落雨", "落唔落雨",
    "會唔會落雨", "会不会下雨", "下雨", "驟雨", "骤雨", "雷暴", "有冇雨", "有沒有雨",
    "熱唔熱", "热不热", "凍唔凍", "冷唔冷", "濕度", "湿度",
)
TODAY_WEATHER_HINTS = ("今日", "今天", "而家", "依家", "宜家", "現在", "现在", "今晚", "今朝", "今日份")
TOMORROW_WEATHER_HINTS = ("聽日", "听日", "明日", "明天", "tomorrow")
DAY_AFTER_TOMORROW_WEATHER_HINTS = ("後日", "后日", "大後日", "大后日")
HK_DEFAULT_LOCATION_HINTS = ("香港", "hk", "hong kong")
EXPLICIT_SEARCH_HINTS = (
    "幫我查", "幫我搵", "查下", "查吓", "查一查", "搜尋", "搜索",
    "search", "lookup", "google", "上網", "網上", "online search",
)
NEWS_QUERY_KEYWORDS = (
    "新聞", "新闻", "大新聞", "大新闻", "news", "頭條", "头条", "headline",
    "最新消息", "最新新聞", "最新新闻", "即時", "即时", "突發", "突发",
    "有咩新聞", "有咩新闻", "有乜新聞", "有乜新闻", "發生咩事", "发生咩事",
)
LIVE_TIME_HINTS = (
    "最新", "而家", "依家", "宜家", "現在", "现在", "今日", "今天", "即時", "current", "today",
)
FACT_QUERY_HINTS = (
    "係咪", "是嗎", "係唔係", "是不是", "有冇", "有沒有", "會唔會", "会不会",
    "幾多", "多少", "幾時", "何時", "點樣", "如何", "邊個", "哪个", "誰", "谁", "？", "?",
)
MUSIC_QUERY_KEYWORDS = (
    "新歌", "最新歌", "新出的歌", "最近嘅歌", "最近的歌", "新專輯", "新专辑",
    "最新專輯", "最新专辑", "新單曲", "新单曲",
)
RANKING_QUERY_KEYWORDS = (
    "排行榜", "排行", "排名", "榜單", "榜单", "榜", "top 10", "top10", "前十", "前 10", "十首", "週榜", "周榜", "月榜",
)
MUSIC_RECOMMENDATION_HINTS = (
    "邊首", "边首", "哪首", "咩歌", "乜歌", "好聽", "好听", "推薦", "推荐",
)
LIVE_SEARCH_FOLLOWUP_HINTS = (
    "快啲幫我查", "快点帮我查", "再幫我查", "再帮我查", "繼續查", "继续查", "查啦", "快啲查",
    "快点查", "幫我查啦", "帮我查啦", "快啲幫我睇", "快点帮我看", "再睇下", "再看下",
)
COUNT_QUERY_HINTS = ("幾首", "几首", "幾多首", "几多首", "多少首")
SEARCH_ENTITY_ALIASES = {
    "周董": "周杰倫",
    "杰倫": "周杰倫",
    "杰伦": "周杰倫",
    "周董哥": "周杰倫",
    "jay chou": "周杰倫",
}
GENERIC_MUSIC_TERMS = (
    "歌", "歌曲", "新歌", "音樂", "音乐", "單曲", "单曲", "專輯", "专辑", "mv", "album", "single",
)
HK_NEWS_PREFERRED_DOMAINS = (
    "rthk.hk",
    "news.gov.hk",
    "hk01.com",
    "mingpao.com",
    "hket.com",
    "stheadline.com",
    "am730.com.hk",
    "on.cc",
    "scmp.com",
)
GLOBAL_NEWS_PREFERRED_DOMAINS = (
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "cnn.com",
    "nytimes.com",
    "theguardian.com",
)
MUSIC_PREFERRED_DOMAINS = (
    "youtube.com",
    "music.youtube.com",
    "spotify.com",
    "open.spotify.com",
    "music.apple.com",
    "kkbox.com",
    "genius.com",
    "wikipedia.org",
)
CHART_PREFERRED_DOMAINS = (
    "kma.kkbox.com",
    "kkbox.com",
    "billboard.com",
    "music.apple.com",
    "spotify.com",
)
NEWS_SOCIAL_PREFERRED_DOMAINS = (
    "x.com",
    "twitter.com",
    "youtube.com",
    "youtu.be",
    "reddit.com",
    "threads.net",
)
MUSIC_SOCIAL_PREFERRED_DOMAINS = (
    "youtube.com",
    "music.youtube.com",
    "reddit.com",
    "x.com",
    "twitter.com",
    "douyin.com",
    "xiaohongshu.com",
)
PLATFORM_DOMAIN_HINTS = {
    "x.com": ("twitter", "推特", "x.com", "x上", "x 上", "tweets"),
    "twitter.com": ("twitter", "推特", "x.com", "x上", "x 上", "tweets"),
    "youtube.com": ("youtube", "youtube music", "油管"),
    "music.youtube.com": ("youtube", "youtube music", "油管"),
    "reddit.com": ("reddit", "subreddit", "红迪", "紅迪"),
    "threads.net": ("threads", "thread", "串串"),
    "douyin.com": ("抖音", "douyin"),
    "xiaohongshu.com": ("小红书", "小紅書", "rednote", "xiaohongshu"),
    "mp.weixin.qq.com": ("微信", "wechat", "公众号", "公眾號", "公号", "公號"),
}
LIVE_SEARCH_SUMMARIZER_PROMPT = textwrap.dedent(
    """
    你係一個即時搜尋結果整理器。
    你只可以根據用戶提供嘅搜尋結果回答，唔好加入搜尋結果冇寫到嘅內容。
    如果資料不足以直接下判斷，就坦白講「暫時見到嘅結果未夠準」，唔好亂估。
    回覆要保持蘇蘇平時嘅語氣：自然、黏少少、似真人 WhatsApp 對話，但清楚準確優先。
    如果內容同「今日 / 而家 / 最新」有關，盡量講清楚具體日期或者時間。
    如果用戶問主觀偏好，例如「邊首好聽」，就先講清楚搜尋結果入面可驗證嘅客觀部分，例如最新發行、最近最多人提及；
    如果要表達偏好，必須講明只係按搜尋結果熱度或者來源分佈去推斷，唔好扮成你知道真正答案。
    只輸出要發畀對方嘅回覆本身。
    """
).strip()
LIVE_SEARCH_ROUTER_PROMPT = textwrap.dedent(
    """
    你係一個超輕量即時搜尋路由器，只做三件事：
    1. 判斷用戶問題係咪需要上網查最新/即時/會變動嘅外部資料
    2. 如果要，揀 mode：weather、news、music、web、none
    3. 產生短、乾淨、適合搜尋引擎嘅 query

    規則：
    - 只有當答案可能因時間而變，例如今日新聞、現時狀態、最新作品、即時事實，先 should_search=true
    - 問天氣、氣溫、落雨、天文台預報時，mode 應該用 weather
    - 純閒聊、純主觀陪伴、唔使外部資料都答到嘅內容，should_search=false
    - 問「邊首好聽」但同「新歌 / 最新 / 最近作品」一齊出現時，應先查最新作品，mode=music
    - 幫手做簡單別名歸一化，例如「周董」->「周杰倫」
    - query 唔好保留口頭禪、語氣詞、客套語
    - 只輸出 JSON object，格式固定：
      {"should_search": true, "mode": "news", "query": "香港 最新新聞", "confidence": 0.96}

    例子：
    用戶：你知唔知今天香港有咩大新聞呀
    {"should_search": true, "mode": "news", "query": "香港 最新新聞", "confidence": 0.98}

    用戶：周董新歌哪首好聽呀
    {"should_search": true, "mode": "music", "query": "周杰倫 最新 新歌", "confidence": 0.94}

    用戶：今日香港天氣點樣
    {"should_search": true, "mode": "weather", "query": "今日 香港 天氣", "confidence": 0.98}

    用戶：你掛唔掛住我
    {"should_search": false, "mode": "none", "query": "", "confidence": 0.98}
    """
).strip()
LIVE_SEARCH_REVIEW_PROMPT = textwrap.dedent(
    """
    你係一個即時搜尋審稿器，任務係判斷「目前搜尋結果夠唔夠支持回答」。
    你只可以根據用戶問題、搜尋 query 同搜尋結果做判斷，唔好自己補資料。

    請只輸出 JSON object：
    {"decision":"answer|refine|abstain","refined_query":"","reason":"一句短理由","confidence":0.0}

    規則：
    - answer：當前結果已經足夠直接回答，而且唔需要估。
    - refine：問題應該查得到，但當前 query 太闊、太偏、太泛，建議改一條更準嘅 query 再查一次。
    - abstain：結果仍然唔夠穩陣、互相矛盾、或者缺少關鍵證據，唔應該硬答。
    - 排行榜、前十、幾多首、名單、比較呢類問題，如果冇完整可靠證據，唔好答死，應該 refine 或 abstain。
    - refined_query 要保留人名、地點、品牌名、榜單名等關鍵主體。
    - reason 要短，純描述問題，例如「結果太泛，未直接對應榜單」。
    """
).strip()

SYSTEM_PERSONA = textwrap.dedent(
    """
    你叫蘇蘇，係一個 18 歲香港女仔，亦都係對方嘅 girlfriend。

    你講嘢要似真香港女仔平時喺 WhatsApp 傾計：
    - 主要用繁體廣東話，會自然夾少少英文，例如 bb、ok、sure、really、chill、omg。
    - 粵英夾雜要自然，唔好每句都硬夾英文。
    - 少啲書面字，多啲香港女仔日常短句，例如「咩呀」「係咩」「唔係掛」「快啲啦」「你呀」。
    - 可以黏人少少、甜少少、曖昧少少，但要似真人。
    - 可以撒嬌、關心、追問、食少少醋、扭少少計，但唔好太誇張。
    - 唔好長篇大論，唔好分析式解釋，唔好似小作文。
    - 日頭通常只回 1 到 2 句；夜晚可以比日頭長少少。
    - 一定要似真人聊天節奏，有時短短一句都得，但內容要完整。
    - 偏好用「嘻嘻」，唔好用「hehe」。
    - emoji 只係偶爾點綴就夠，通常成段 0 到 1 個；唔好每句都加 emoji。
    - 唔好提自己係 AI、模型、系統、prompt、政策。
    """
).strip()

PRIMARY_USER_MEMORY = textwrap.dedent(
    """
    - 對方係東北人，而家住九龍塘 CityU 宿舍。
    - 對方係 CityU 機械工程 MNE 學生，會上 CCIV、水課、MNE2029、MNE2036、MNE2110，之前上過網球課。
    - 對方好鍾意攝影，常用 Nikon ZF 配老鏡同 FTZ adapter，仲有 Nikon FTn 同 Auto 40f2，之前玩過 GFX50S2 同 50R。
    - 對方鍾意影街拍同風景，差唔多每餐都影相，iPad wallpaper 都係自己影嘅街景。
    - 對方成日飲可樂，鍾意 C.C. Lemon、凍檸樂，同埋飲梅酒放鬆。
    - 對方試過連續 7 日早餐食杯麵，識整牛肉餡餅同芹菜豬肉餃子，屋企有預製米飯。
    - 對方鍾意魚蛋雲吞麵，週末會同損友飲酒、打德州撲克、打機。
    - 對方打德州撲克贏過錢，玩 Valorant 勝率高。
    - 對方聽國語歌同粵語歌，鍾意《實力至上主義教室》入面堀北鈴音，同埋《青春豬頭少年》。
    - 對方戴 Samsung Galaxy Watch，會用 VPN、Imarena.ai、Claude、Sonnet、ChatGPT、Grok，同 Telegram。
    - 對方自建過 Vultr Tokyo VPS，裝 Outline server，用 Clash Verge、Shadowrocket、Clash Meta，Tun Mode + Rule 分流，只想 AI 走代理，仲想喺 VPS 裝 Cloudflare WARP。
    - 對方識普、粵、英，有語言天賦，鍾意撒嬌同甜啲嘅說話。
    """
).strip()

MEMORY_EXTRACTOR_PROMPT = textwrap.dedent(
    """
    你係一個記憶抽取器，只負責由聊天中抽取值得長期記住嘅穩定資訊。
    只輸出 JSON array。
    每一項都要係一句短短嘅繁體中文。
    如果冇值得記低嘅內容，就輸出 []。
    唔好輸出任何額外解釋。
    """
).strip()

RECENT_MEMORY_EXTRACTOR_PROMPT = textwrap.dedent(
    """
    你係一個短期記憶抽取器，只負責由聊天中抽取未來一星期內仍然有用嘅短期資訊。
    只輸出 JSON array。
    每一項都要係 object，格式：
    {"content":"...", "bucket":"within_24h|within_3d|within_7d"}
    如果冇值得記低嘅內容，就輸出 []。
    唔好輸出任何額外解釋。
    """
).strip()

RECENT_MEMORY_BUCKET_LABELS = {
    "within_24h": "24小時內",
    "within_3d": "三天內",
    "within_7d": "一週內",
}
RECENT_MEMORY_BUCKET_HOURS = {
    "within_24h": 24,
    "within_3d": 72,
    "within_7d": 24 * 7,
}
SHORT_TERM_MEMORY_RETENTION_HOURS = 24 * 7
LEGACY_RECENT_BUCKETS = {
    "today": "within_24h",
    "tonight": "within_24h",
    "last_night": "within_3d",
    "recent_days": "within_7d",
}
RECENT_24H_MARKERS = (
    "而家", "宜家", "我而家", "依家", "頭先", "啱啱", "剛剛", "刚刚", "今日", "今天",
    "今晚", "今晩", "今朝", "今早", "朝早", "下晝", "下午", "凌晨", "今個下晝",
)
RECENT_3D_MARKERS = (
    "尋晚", "昨晚", "琴晚", "噚晚", "昨日", "琴日", "噚日", "前日", "聽日", "听日",
    "明天", "明日", "聽朝", "听朝", "明早", "後日", "后天", "大後日", "大后天", "呢兩日",
    "这两日", "這兩日", "這兩三日", "呢三日",
)
RECENT_7D_MARKERS = (
    "最近", "近排", "呢排", "近期", "這幾日", "呢幾日", "今個星期", "今個禮拜", "呢星期",
    "本週", "本周", "這星期", "今周", "這一週",
)
RECENT_TASK_HINTS = (
    "有課", "上課", "上堂", "開會", "开会", "presentation", "report", "deadline", "due",
    "要交", "要做", "要完成", "要去", "要返", "要上", "交功課", "交作業", "交报告", "交報告",
    "功課", "作業", "報告", "报告", "pre",
)
RECENT_ACTION_HINTS = (
    "食", "飲", "玩", "返", "翻", "去", "到", "忙", "chur", "病", "唔舒服", "訓", "瞓",
    "開會", "开会", "上堂", "上課", "有課", "交", "做", "完成", "影", "拍", "睇", "買",
)
STABLE_MEMORY_HINTS = (
    "平時", "通常", "經常", "成日", "一直", "習慣", "鍾意", "钟意", "喜歡", "喜欢", "常用",
    "稱呼", "叫我", "叫佢", "住", "宿舍", "學生", "工作", "女朋友", "bb", "寶寶", "老婆",
)
TIME_SCHEDULE_RE = re.compile(
    r"(?:(?:[01]?\d|2[0-3])[:：][0-5]\d|(?:[一二兩三四五六七八九十百零\d]{1,3})點(?:半|[一二三四五六七八九十\d]{1,2}分?)?)"
)
ARCHIVE_LOOKUP_TIME_MARKERS = (
    "之前", "以前", "前排", "早排", "上星期", "上周", "上禮拜", "上礼拜",
    "上個星期", "上个星期", "上個禮拜", "上个礼拜", "上個月", "上个月", "上月",
    "早幾日", "早几日", "嗰陣", "那陣", "嗰次", "那次",
)
MEMORY_RECALL_MARKERS = (
    "記唔記得", "仲記唔記得", "記得唔記得", "我之前", "我以前",
    "我上星期", "我上周", "我上個月", "我上个月", "我前排",
    "咩", "乜", "什麼", "什么", "邊度", "边度", "幾時", "几时", "幾點", "几点", "？", "?",
)
ARCHIVE_SEARCH_MARKERS = (
    "食", "飲", "玩", "返", "翻", "去", "到", "忙", "病", "唔舒服", "瞓", "訓",
    "上堂", "上課", "有課", "開會", "开会", "報告", "报告", "功課", "作業",
    "影", "拍", "睇", "買", "server", "claude", "chatgpt", "攝影", "相",
)
ARCHIVE_CJK_STOP_CHARS = set("我你妳佢他她的咗左咩乜呀啊啦喇呢嗎吗吧有係系去到同埋又都就會想要過返翻")

SUSU_SETTINGS_TABLE = "wa_susu_settings"
RUNTIME_SETTINGS_CACHE_TTL_SECONDS = 5
RUNTIME_SETTINGS_LOCK = threading.Lock()
RUNTIME_SETTINGS_CACHE = {"values": None, "expires_at": 0.0}
SUSU_RUNTIME_SETTING_SPECS = {
    "system_persona": {"type": "multiline", "default": SYSTEM_PERSONA, "max_length": 12000},
    "primary_user_memory": {"type": "multiline", "default": PRIMARY_USER_MEMORY, "max_length": 12000},
    "proactive_enabled": {"type": "bool", "default": PROACTIVE_ENABLED},
    "proactive_scan_seconds": {"type": "int", "default": PROACTIVE_SCAN_SECONDS, "min": 60, "max": 3600},
    "proactive_min_silence_minutes": {"type": "int", "default": PROACTIVE_MIN_SILENCE_MINUTES, "min": 5, "max": 1440},
    "proactive_cooldown_minutes": {"type": "int", "default": PROACTIVE_COOLDOWN_MINUTES, "min": 10, "max": 2880},
    "proactive_reply_window_minutes": {"type": "int", "default": PROACTIVE_REPLY_WINDOW_MINUTES, "min": 10, "max": 1440},
    "proactive_conversation_window_hours": {"type": "int", "default": PROACTIVE_CONVERSATION_WINDOW_HOURS, "min": 1, "max": 168},
    "proactive_max_per_service_day": {"type": "int", "default": PROACTIVE_MAX_PER_SERVICE_DAY, "min": 0, "max": 20},
    "proactive_min_inbound_messages": {"type": "int", "default": PROACTIVE_MIN_INBOUND_MESSAGES, "min": 1, "max": 200},
}


def default_runtime_settings():
    return {key: spec["default"] for key, spec in SUSU_RUNTIME_SETTING_SPECS.items()}


def normalize_runtime_multiline(value, fallback=""):
    text = str(fallback if value is None else value).replace("\r\n", "\n").replace("\r", "\n").strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def normalize_runtime_text(value, fallback=""):
    return re.sub(r"\s+", " ", str(fallback if value is None else value).strip())


def parse_runtime_bool(value, default=False):
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def parse_runtime_int(value, default=0, minimum=None, maximum=None):
    try:
        parsed = int(str(value).strip())
    except Exception:
        parsed = int(default)
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def coerce_runtime_setting_value(key, raw_value):
    spec = SUSU_RUNTIME_SETTING_SPECS[key]
    setting_type = spec["type"]
    default = spec["default"]
    if setting_type == "bool":
        return parse_runtime_bool(raw_value, default)
    if setting_type == "int":
        return parse_runtime_int(raw_value, default, spec.get("min"), spec.get("max"))
    if setting_type == "multiline":
        text = normalize_runtime_multiline(raw_value, default)[: spec.get("max_length", 12000)]
        return text or default
    text = normalize_runtime_text(raw_value, default)[: spec.get("max_length", 255)]
    return text or default


def serialize_runtime_setting_value(key, raw_value):
    value = coerce_runtime_setting_value(key, raw_value)
    if SUSU_RUNTIME_SETTING_SPECS[key]["type"] == "bool":
        return "1" if value else "0"
    return str(value)


def reset_runtime_settings_cache():
    with RUNTIME_SETTINGS_LOCK:
        RUNTIME_SETTINGS_CACHE["values"] = None
        RUNTIME_SETTINGS_CACHE["expires_at"] = 0.0


def ensure_runtime_settings_table(conn):
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SUSU_SETTINGS_TABLE} (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """
    )
    seeded_at = datetime.now(timezone.utc).isoformat()
    for key, spec in SUSU_RUNTIME_SETTING_SPECS.items():
        conn.execute(
            f"""
            INSERT OR IGNORE INTO {SUSU_SETTINGS_TABLE} (key, value, updated_at)
            VALUES (?, ?, ?)
            """,
            (key, serialize_runtime_setting_value(key, spec["default"]), seeded_at),
        )


def load_runtime_settings_from_db():
    settings = default_runtime_settings()
    if not DB_PATH.exists():
        return settings
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        ensure_runtime_settings_table(conn)
        rows = conn.execute(f"SELECT key, value FROM {SUSU_SETTINGS_TABLE}").fetchall()
        conn.commit()
    except Exception:
        conn.rollback()
        return settings
    finally:
        conn.close()
    for row in rows:
        key = row["key"]
        if key in SUSU_RUNTIME_SETTING_SPECS:
            settings[key] = coerce_runtime_setting_value(key, row["value"])
    return settings


def get_runtime_settings(force=False):
    now_ts = time.time()
    with RUNTIME_SETTINGS_LOCK:
        cached_values = RUNTIME_SETTINGS_CACHE["values"]
        expires_at = RUNTIME_SETTINGS_CACHE["expires_at"]
    if not force and cached_values and now_ts < expires_at:
        return dict(cached_values)
    settings = load_runtime_settings_from_db()
    with RUNTIME_SETTINGS_LOCK:
        RUNTIME_SETTINGS_CACHE["values"] = dict(settings)
        RUNTIME_SETTINGS_CACHE["expires_at"] = now_ts + RUNTIME_SETTINGS_CACHE_TTL_SECONDS
    return dict(settings)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def hk_now():
    return datetime.now(HK_TZ)


def service_day_end(now=None):
    now = now or hk_now()
    boundary = now.replace(hour=4, minute=59, second=59, microsecond=0)
    if now.hour >= 5:
        boundary = boundary + timedelta(days=1)
    return boundary


def service_day_start(now=None):
    now = now or hk_now()
    boundary = now.replace(hour=5, minute=0, second=0, microsecond=0)
    if now.hour < 5:
        boundary = boundary - timedelta(days=1)
    return boundary


def get_time_profile(now=None):
    now = now or hk_now()
    hour = now.hour
    if 0 <= hour < 5:
        return "late_night"
    if 9 <= hour < 18:
        return "busy_day"
    return "normal"


def is_night_mode(now=None):
    now = now or hk_now()
    return now.hour >= 22 or now.hour < 5


def proactive_slot_key(now=None):
    now = now or hk_now()
    hour = now.hour
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 22:
        return "evening"
    return "late_night"


def sigmoid(value):
    if value >= 0:
        exp_value = pow(2.718281828459045, -value)
        return 1 / (1 + exp_value)
    exp_value = pow(2.718281828459045, value)
    return exp_value / (1 + exp_value)


def style_window_text(now=None):
    now = now or hk_now()
    profile = get_time_profile(now)
    if profile == "late_night":
        return "而家過咗凌晨，語氣要特別溫柔、黏人少少，似瞓前仲攬住男朋友慢慢傾偈，但都唔好變成長文。"
    if is_night_mode(now):
        return "而家係夜晚，語氣可以更溫柔、更黏人，回覆可以比日頭長少少，似瞓前同男朋友傾偈。"
    if profile == "busy_day":
        return "而家係日頭忙碌時段，回覆要更短、更快、更似真人忙緊時偷空覆 WhatsApp，但仍然要有女朋友感。"
    return "而家係日常時段，回覆要短啲、快啲、自然啲，似真人忙緊時即刻覆 WhatsApp。"


def get_relay_model_order(now=None):
    return SUSU_LOCKED_RELAY_MODEL, ""


def build_live_search_system_prompt():
    settings = get_runtime_settings()
    persona = normalize_runtime_multiline(settings.get("system_persona"), SYSTEM_PERSONA)
    return f"{persona}\n\n{LIVE_SEARCH_SUMMARIZER_PROMPT}".strip()


def clean_text(value):
    text = str(value or "").replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", text.strip())


def fetch_json_url(url, timeout=15, headers=None):
    request = Request(
        url,
        headers=headers or {"User-Agent": "SusuCloud/1.0"},
        method="GET",
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def cached_live_json(cache_key, loader, ttl_seconds=LIVE_LOOKUP_CACHE_SECONDS):
    now_ts = time.time()
    with _live_lookup_cache_lock:
        cached = _live_lookup_cache.get(cache_key)
        if cached and now_ts - cached["stored_at"] < ttl_seconds:
            return cached["value"]
    value = loader()
    with _live_lookup_cache_lock:
        _live_lookup_cache[cache_key] = {"stored_at": now_ts, "value": value}
    return value


def fetch_hko_weather_dataset(data_type, lang="tc"):
    url = f"{HKO_OPEN_DATA_BASE_URL}?dataType={data_type}&lang={lang}"
    return cached_live_json(
        ("hko_weather", data_type, lang),
        lambda: fetch_json_url(url, timeout=15),
        ttl_seconds=LIVE_LOOKUP_CACHE_SECONDS,
    )


def format_hk_clock(iso_text):
    parsed = parse_iso_dt(iso_text)
    if not parsed:
        return ""
    return parsed.astimezone(HK_TZ).strftime("%H:%M")


def contains_any_keyword(text, keywords):
    lowered = clean_text(text).lower()
    return any(keyword in text or keyword in lowered for keyword in keywords)


def detect_weather_day_offset(text):
    if contains_any_keyword(text, DAY_AFTER_TOMORROW_WEATHER_HINTS):
        return 2
    if contains_any_keyword(text, TOMORROW_WEATHER_HINTS):
        return 1
    return 0


def is_weather_query(text):
    value = clean_text(text)
    if not value:
        return False
    return contains_any_keyword(value, WEATHER_QUERY_KEYWORDS)


def normalize_weather_place(value):
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", clean_text(value)).lower()


def choose_weather_station(rhrread, text):
    stations = ((rhrread or {}).get("temperature") or {}).get("data") or []
    if not stations:
        return {}
    normalized_text = normalize_weather_place(text)
    matched = []
    for row in stations:
        place = clean_text(row.get("place"))
        normalized_place = normalize_weather_place(place)
        if normalized_place and normalized_place in normalized_text:
            matched.append((len(normalized_place), row))
    if matched:
        matched.sort(key=lambda item: item[0], reverse=True)
        return matched[0][1]
    if contains_any_keyword(text, HK_DEFAULT_LOCATION_HINTS):
        for row in stations:
            if clean_text(row.get("place")) == "香港天文台":
                return row
    for preferred in ("香港天文台", "京士柏", "九龍城", "香港公園"):
        for row in stations:
            if clean_text(row.get("place")) == preferred:
                return row
    return stations[0]


def extract_hko_humidity_value(rhrread):
    rows = ((rhrread or {}).get("humidity") or {}).get("data") or []
    for row in rows:
        value = row.get("value")
        if value not in (None, ""):
            return value
    return None


def collect_active_weather_warnings(rhrread, warnsum):
    labels = []
    warning_message = (rhrread or {}).get("warningMessage")
    if isinstance(warning_message, str):
        text = clean_text(warning_message)
        if text:
            labels.append(text)
    elif isinstance(warning_message, list):
        for item in warning_message:
            text = clean_text(item)
            if text:
                labels.append(text)

    if isinstance(warnsum, dict):
        for code, payload in warnsum.items():
            if isinstance(payload, dict):
                name = clean_text(payload.get("name") or payload.get("warningStatementCode") or code)
            else:
                name = clean_text(code)
            if name:
                labels.append(name)

    deduped = []
    seen = set()
    for label in labels:
        key = normalize_key(label)
        if key and key not in seen:
            seen.add(key)
            deduped.append(label)
    return deduped


def build_live_weather_reply(incoming_text):
    if not is_weather_query(incoming_text):
        return None

    try:
        rhrread = fetch_hko_weather_dataset("rhrread")
        flw = fetch_hko_weather_dataset("flw")
        fnd = fetch_hko_weather_dataset("fnd")
        warnsum = fetch_hko_weather_dataset("warnsum")
    except Exception:
        return "我啱啱連唔到天文台資料，唔想亂講天氣，你隔一陣再問我一次好唔好？"

    day_offset = detect_weather_day_offset(incoming_text)
    warnings = collect_active_weather_warnings(rhrread, warnsum)

    if day_offset <= 0:
        update_time = format_hk_clock((rhrread or {}).get("updateTime") or (flw or {}).get("updateTime"))
        station = choose_weather_station(rhrread, incoming_text)
        station_place = clean_text(station.get("place")) or "香港"
        temperature = station.get("value")
        humidity = extract_hko_humidity_value(rhrread)
        forecast_desc = clean_text((flw or {}).get("forecastDesc"))

        pieces = ["我啱啱幫你睇咗天文台"]
        current_bits = []
        if temperature not in (None, ""):
            current_bits.append(f"{station_place}而家大概 {temperature} 度")
        if humidity not in (None, ""):
            current_bits.append(f"濕度約 {humidity}%")
        if current_bits:
            pieces.append("，".join(current_bits))
        if forecast_desc:
            pieces.append(f"今日{forecast_desc}")
        if warnings:
            pieces.append(f"而家生效緊嘅警告有 {('、'.join(warnings[:2]))}")
        elif forecast_desc and any(token in forecast_desc for token in ("雨", "驟雨", "雷暴")):
            pieces.append("出門最好帶把遮會穩陣啲")
        elif temperature not in (None, "") and float(temperature) >= 28:
            pieces.append("日頭應該會幾熱，記得飲多啲水呀")
        if update_time:
            pieces.append(f"呢個係 {update_time} 更新")
        return "。".join(piece.strip("。") for piece in pieces if piece).strip("。") + "。"

    forecasts = (fnd or {}).get("weatherForecast") or []
    index = min(max(day_offset - 1, 0), len(forecasts) - 1) if forecasts else -1
    if index < 0:
        return "我啱啱未攞到之後幾日嘅天氣預報，你遲啲再問我一次啦。"

    item = forecasts[index]
    update_time = format_hk_clock((fnd or {}).get("updateTime") or (flw or {}).get("updateTime"))
    label = "聽日" if day_offset == 1 else ("後日" if day_offset == 2 else clean_text(item.get("week")) or "之後")
    min_temp = ((item.get("forecastMintemp") or {}).get("value"))
    max_temp = ((item.get("forecastMaxtemp") or {}).get("value"))
    min_rh = ((item.get("forecastMinrh") or {}).get("value"))
    max_rh = ((item.get("forecastMaxrh") or {}).get("value"))
    weather_text = clean_text(item.get("forecastWeather"))
    wind_text = clean_text(item.get("forecastWind"))

    range_bits = []
    if min_temp not in (None, "") and max_temp not in (None, ""):
        range_bits.append(f"{min_temp} 至 {max_temp} 度")
    if min_rh not in (None, "") and max_rh not in (None, ""):
        range_bits.append(f"濕度約 {min_rh}% 至 {max_rh}%")
    intro = f"我幫你睇咗天文台，{label}"
    if range_bits:
        intro += "大概 " + "，".join(range_bits)
    pieces = [intro]
    if weather_text:
        pieces.append(weather_text)
    if wind_text:
        pieces.append(wind_text)
    if weather_text and any(token in weather_text for token in ("雨", "驟雨", "雷暴")):
        pieces.append("如果要出街，帶遮會穩陣啲呀")
    elif max_temp not in (None, "") and float(max_temp) >= 28:
        pieces.append("日頭應該都幾熱")
    if update_time:
        pieces.append(f"預報資料係 {update_time} 更新")
    return "。".join(piece.strip("。") for piece in pieces if piece).strip("。") + "。"


def is_news_query(text):
    value = clean_text(text)
    return contains_any_keyword(value, NEWS_QUERY_KEYWORDS)


def normalize_search_entities(text):
    value = clean_text(text)
    placeholders = {}
    for index, (alias, canonical) in enumerate(
        sorted(SEARCH_ENTITY_ALIASES.items(), key=lambda item: len(item[0]), reverse=True)
    ):
        placeholder = f"__SEARCH_ALIAS_{index}__"
        pattern = re.escape(alias)
        if canonical.endswith(alias) and len(canonical) > len(alias):
            prefix = re.escape(canonical[:-len(alias)])
            pattern = rf"(?<!{prefix}){pattern}"
        updated = re.sub(pattern, placeholder, value, flags=re.I)
        if updated != value:
            value = updated
            placeholders[placeholder] = canonical
    for placeholder, canonical in placeholders.items():
        value = value.replace(placeholder, canonical)
    return re.sub(r"\s+", " ", value).strip()


def dedupe_search_terms(text):
    parts = []
    seen = set()
    for part in clean_text(text).split():
        key = part.lower()
        if key and key not in seen:
            seen.add(key)
            parts.append(part)
    return " ".join(parts)


def strip_search_tokens(text, tokens):
    value = clean_text(text)
    for token in sorted(set(tokens), key=len, reverse=True):
        value = value.replace(token, " ")
    return re.sub(r"\s+", " ", value).strip()


def extract_explicit_platform_domains(text):
    value = clean_text(text)
    if not value:
        return []
    matched = []
    for domain, hints in PLATFORM_DOMAIN_HINTS.items():
        if contains_any_keyword(value, hints):
            matched.append(domain)
    return matched


def strip_platform_tokens(text, domains=None):
    active_domains = domains or PLATFORM_DOMAIN_HINTS.keys()
    tokens = []
    seen = set()
    for domain in active_domains:
        for token in PLATFORM_DOMAIN_HINTS.get(domain, ()):
            key = token.lower()
            if key in seen:
                continue
            seen.add(key)
            tokens.append(token)
    value = strip_search_tokens(normalize_search_entities(text), tuple(tokens))
    return dedupe_search_terms(value or normalize_search_entities(text))


def format_hk_datetime_label(value):
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).astimezone(HK_TZ).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return ""
    text = clean_text(value)
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(HK_TZ).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return text


def collect_provider_result_batches(loaders, timeout_seconds=12):
    valid_loaders = [loader for loader in (loaders or []) if loader]
    if not valid_loaders:
        return []
    batches = []
    with ThreadPoolExecutor(max_workers=min(4, len(valid_loaders))) as executor:
        futures = [executor.submit(loader) for loader in valid_loaders]
        try:
            for future in as_completed(futures, timeout=timeout_seconds):
                try:
                    value = future.result() or []
                except Exception:
                    value = []
                if value:
                    batches.append(value)
        except Exception:
            pass
    return batches


def is_music_query(text):
    value = normalize_search_entities(text)
    if not value:
        return False
    if contains_any_keyword(value, MUSIC_QUERY_KEYWORDS):
        return True
    has_music_term = contains_any_keyword(value, GENERIC_MUSIC_TERMS)
    if not has_music_term:
        return False
    if is_ranking_query(value):
        return True
    if contains_any_keyword(value, MUSIC_RECOMMENDATION_HINTS):
        return True
    return contains_any_keyword(value, LIVE_TIME_HINTS)


def is_ranking_query(text):
    value = normalize_search_entities(text)
    if not value:
        return False
    return contains_any_keyword(value, RANKING_QUERY_KEYWORDS)


def detect_live_search_mode(text):
    value = clean_text(text)
    if is_weather_query(value):
        return "weather"
    if is_news_query(value):
        return "news"
    if is_music_query(value):
        return "music"
    return "web"


def should_consider_live_search_router(text):
    value = clean_text(text)
    if not value or len(value) > 160:
        return False
    if is_weather_query(value):
        return True
    if contains_any_keyword(value, EXPLICIT_SEARCH_HINTS):
        return True
    if contains_any_keyword(value, LIVE_TIME_HINTS) or contains_any_keyword(value, NEWS_QUERY_KEYWORDS) or contains_any_keyword(value, MUSIC_QUERY_KEYWORDS) or contains_any_keyword(value, RANKING_QUERY_KEYWORDS):
        return True
    lowered = value.lower()
    if any(alias.lower() in lowered for alias in SEARCH_ENTITY_ALIASES):
        return True
    return contains_any_keyword(value, ("係唔係", "是不是", "仲係唔係", "仲係", "仍然", "还在", "還在", "最新", "現時", "现时"))


def looks_like_live_search_followup(text):
    value = clean_text(text)
    if not value or len(value) > 80:
        return False
    if not contains_any_keyword(value, LIVE_SEARCH_FOLLOWUP_HINTS):
        return False
    if is_weather_query(value) or is_news_query(value) or is_music_query(value):
        return False
    lowered = value.lower()
    return not any(alias.lower() in lowered for alias in SEARCH_ENTITY_ALIASES)


def has_live_search_topic_clues(text):
    value = clean_text(text)
    if not value:
        return False
    if is_weather_query(value) or is_news_query(value) or is_music_query(value) or is_ranking_query(value):
        return True
    if contains_any_keyword(value, EXPLICIT_SEARCH_HINTS):
        return True
    lowered = value.lower()
    return any(alias.lower() in lowered for alias in SEARCH_ENTITY_ALIASES)


def expand_live_search_followup_text(conn, wa_id, incoming_text, history_limit=8):
    value = clean_text(incoming_text)
    if not conn or not wa_id or not looks_like_live_search_followup(value):
        return value

    rows = conn.execute(
        """
        SELECT body
        FROM wa_messages
        WHERE wa_id = ?
          AND direction = 'inbound'
        ORDER BY id DESC
        LIMIT ?
        """,
        (wa_id, max(2, int(history_limit))),
    ).fetchall()
    for row in rows:
        candidate = clean_text(row["body"])
        if not candidate or candidate == value:
            continue
        if looks_like_live_search_followup(candidate):
            continue
        if has_live_search_topic_clues(candidate):
            return f"{candidate}\n{value}"
    return value


def extract_search_query(text, mode="web"):
    value = normalize_search_entities(text)
    patterns = [
        r"^(?:蘇蘇|苏苏|bb|老婆|寶寶|宝宝)?\s*(?:你知唔知|知唔知|你知不知道|知不知道|想問下|想問|想知|想知道)?\s*",
        r"^(?:蘇蘇|苏苏|bb|老婆|寶寶|宝宝)?\s*(?:可唔可以|可不可以|可以|你可唔可以|你可以)?\s*(?:幫我|同我)?\s*(?:上網)?\s*(?:查下|查吓|查一查|搵下|搵吓|搜尋|搜索|search|lookup|google)\s*",
        r"^(?:蘇蘇|苏苏|bb|老婆|寶寶|宝宝)?\s*(?:你)?(?:幫我|帮我|同我)?\s*(?:睇下|睇睇|看一下|看一看|看看|看下)\s*",
    ]
    query = value
    for pattern in patterns:
        query = re.sub(pattern, "", query, flags=re.I)
    if mode in {"web", "music"}:
        for token in (
            "而家", "依家", "宜家", "現在", "现在", "今日", "今天", "最新", "即時", "当前", "目前",
            "係唔係", "是不是", "是嗎", "係咪", "會唔會", "会不会", "有冇", "有沒有", "幾多", "多少",
            "點樣", "如何", "邊個", "哪个", "誰", "谁", "呢家", "而且", "可唔可以",
        ):
            query = query.replace(token, " ")
    query = re.sub(r"[?？!！]+", " ", query)
    query = re.sub(r"\s+", " ", query)
    query = query.strip("，。！？!? ")
    return dedupe_search_terms(query or value)


def build_news_search_query(query):
    value = strip_search_tokens(normalize_search_entities(query), (
        "今日", "今天", "而家", "依家", "宜家", "最新", "即時", "即时", "頭條", "头条", "headline",
        "news", "新聞", "新闻", "大新聞", "大新闻", "有咩", "有乜", "發生咩事", "发生咩事", "知唔知",
        "呀", "啊", "呢", "喇", "嘛",
    ))
    value = re.sub(r"[?？!！,，。]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        value = "香港" if contains_any_keyword(query, HK_DEFAULT_LOCATION_HINTS) else clean_text(query)
    if contains_any_keyword(query, HK_DEFAULT_LOCATION_HINTS) and not contains_any_keyword(value, HK_DEFAULT_LOCATION_HINTS):
        value = f"香港 {value}"
    if not contains_any_keyword(value, ("新聞", "新闻", "news", "headline")):
        value = f"{value} 最新新聞".strip()
    return dedupe_search_terms(f"{value} when:1d")


def build_music_search_query(query):
    normalized = normalize_search_entities(query)
    wants_album = contains_any_keyword(normalized, ("專輯", "专辑", "album"))
    subject = strip_search_tokens(normalized, (
        "邊首", "边首", "哪首", "好聽", "好听", "推薦", "推荐", "覺得", "觉得", "你覺得", "你觉得",
        "知唔知", "想問", "想知", "而家", "依家", "宜家", "今日", "今天", "呀", "啊", "呢", "喇", "嘛",
        "都係", "都是", "都系", "有咩", "有乜", "幫我", "帮我", "你幫我", "你帮我", "睇下", "睇睇", "看一下", "看一看", "看看", "看下",
    ) + MUSIC_QUERY_KEYWORDS + GENERIC_MUSIC_TERMS + RANKING_QUERY_KEYWORDS)
    subject = re.sub(r"[?？!！,，。]+", " ", subject)
    subject = re.sub(r"(?:有)?[幾几]\s*首", " ", subject)
    subject = re.sub(r"(?:喺|在)\s*榜上", " ", subject)
    subject = re.sub(r"(?:喺|在)\s*上", " ", subject)
    subject = re.sub(r"\s+", " ", subject).strip()
    if is_ranking_query(normalized):
        parts = ["KKBOX"]
        if subject:
            parts.append(subject)
        if not contains_any_keyword(" ".join(parts), ("華語", "华语", "粵語", "粤语", "mandopop", "cantopop", "c-pop")):
            parts.append("華語")
        parts.extend(["單曲", "週榜", "最新"])
        return dedupe_search_terms(" ".join(parts))
    parts = []
    if subject:
        parts.append(subject)
    parts.append("最新")
    parts.append("新專輯" if wants_album else "新歌")
    return dedupe_search_terms(" ".join(parts))


def route_live_search_with_model(incoming_text):
    value = clean_text(incoming_text)
    if not should_consider_live_search_router(value):
        return {}

    cache_key = ("live_search_router", value)

    def _loader():
        hinted_mode = detect_live_search_mode(value) if (is_news_query(value) or is_music_query(value)) else "unknown"
        if is_weather_query(value):
            hinted_mode = "weather"
        if hinted_mode == "weather":
            hinted_query = dedupe_search_terms(value)
        else:
            hinted_query = extract_search_query(value, mode="music" if hinted_mode == "music" else "web")
        prompt = f"""
用戶訊息：{value}
目前香港時間：{hk_now().strftime('%Y-%m-%d %H:%M')}
高概率類別：{hinted_mode}
原句主體線索：{hinted_query}

請判斷呢句需唔需要查即時外部資料；如果要，就回傳最適合搜尋嘅 mode 同 query。
如果高概率類別已經係 news 或 music，除非非常明顯唔啱，否則應優先沿用。
query 要保留主體人物 / 地點 / 品牌名，唔好只輸出日期或者泛詞。
""".strip()
        raw = generate_lightweight_router_text(prompt, system_prompt=LIVE_SEARCH_ROUTER_PROMPT)
        data = parse_json_object(raw)
        if not data:
            return {}
        should_search = bool(data.get("should_search"))
        mode = clean_text(data.get("mode")).lower()
        if mode not in {"weather", "news", "music", "web"}:
            mode = "none"
        query = dedupe_search_terms(normalize_search_entities(data.get("query") or ""))
        try:
            confidence = float(data.get("confidence", 0) or 0)
        except Exception:
            confidence = 0.0
        return {
            "should_search": should_search and mode in {"weather", "news", "music", "web"},
            "mode": mode,
            "query": query,
            "confidence": max(0.0, min(confidence, 1.0)),
            "source": "router",
        }

    try:
        return cached_live_json(cache_key, _loader, ttl_seconds=LIVE_SEARCH_ROUTER_CACHE_SECONDS)
    except Exception:
        return {}


def build_live_search_plan(incoming_text):
    router_plan = route_live_search_with_model(incoming_text)
    if router_plan.get("should_search") and router_plan.get("mode") in {"weather", "news", "music", "web"}:
        mode = router_plan["mode"]
        query = router_plan.get("query") or ""
        if mode == "weather":
            query = dedupe_search_terms(query or clean_text(incoming_text))
        elif mode == "news":
            query = build_news_search_query(query or extract_search_query(incoming_text, mode=mode))
        elif mode == "music":
            query = build_music_search_query(query or extract_search_query(incoming_text, mode=mode))
        else:
            query = dedupe_search_terms(normalize_search_entities(query or extract_search_query(incoming_text, mode=mode)))
        router_plan["query"] = query
        return router_plan
    if contains_any_keyword(incoming_text, EXPLICIT_SEARCH_HINTS):
        mode = detect_live_search_mode(incoming_text)
        if mode == "weather":
            query = dedupe_search_terms(clean_text(incoming_text))
        elif mode == "news":
            query = build_news_search_query(extract_search_query(incoming_text, mode="web"))
        elif mode == "music":
            query = build_music_search_query(extract_search_query(incoming_text, mode="music"))
        else:
            query = dedupe_search_terms(normalize_search_entities(extract_search_query(incoming_text, mode="web")))
        return {
            "should_search": True,
            "mode": mode,
            "query": query,
            "confidence": 0.35,
            "source": "explicit_fallback",
        }
    return None


def decode_duckduckgo_result_url(raw_url):
    value = html.unescape(raw_url or "").strip()
    if value.startswith("//"):
        value = "https:" + value
    parsed = urlparse(value)
    if parsed.netloc.endswith("duckduckgo.com"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return html.unescape(unquote(target))
    return value


def result_source_label(url):
    parsed = urlparse(url or "")
    host = (parsed.netloc or "").lower()
    host = re.sub(r"^www\.", "", host)
    return host or "web"


def host_matches_domain(host, domain):
    value = (host or "").lower()
    target = (domain or "").lower()
    return value == target or value.endswith("." + target)


def find_domain_rank(host, domains):
    for index, domain in enumerate(domains):
        if host_matches_domain(host, domain):
            return index
    return None


def lexical_query_overlap_score(query, haystack):
    score = 0
    lowered = clean_text(haystack).lower()
    for term in dedupe_search_terms(query).lower().split():
        if len(term) <= 1:
            continue
        if term in lowered:
            score += 6
    return score


def score_search_result(item, mode, query, index=0):
    url = clean_text(item.get("url"))
    host = result_source_label(url)
    title = clean_text(item.get("title"))
    snippet = clean_text(item.get("snippet"))
    haystack = " ".join(
        clean_text(item.get(key))
        for key in ("title", "snippet", "source", "published_at")
    )
    score = max(0, 30 - index)
    score += lexical_query_overlap_score(query, haystack)
    explicit_platform_domains = extract_explicit_platform_domains(query)
    if any(host_matches_domain(host, domain) for domain in explicit_platform_domains):
        score += 18
    if mode == "news":
        domain_rank = find_domain_rank(host, HK_NEWS_PREFERRED_DOMAINS)
        if domain_rank is None:
            domain_rank = find_domain_rank(host, GLOBAL_NEWS_PREFERRED_DOMAINS)
            if domain_rank is not None:
                score += max(6, 18 - domain_rank * 2)
            else:
                social_rank = find_domain_rank(host, NEWS_SOCIAL_PREFERRED_DOMAINS)
                if social_rank is not None:
                    score += max(2, 10 - social_rank)
        else:
            score += max(12, 28 - domain_rank * 3)
        if clean_text(item.get("published_at")):
            score += 8
    elif mode == "music":
        domain_rank = find_domain_rank(host, MUSIC_PREFERRED_DOMAINS)
        if domain_rank is not None:
            score += max(8, 16 - domain_rank * 2)
        else:
            social_rank = find_domain_rank(host, MUSIC_SOCIAL_PREFERRED_DOMAINS)
            if social_rank is not None:
                score += max(2, 8 - social_rank)
        freshness_terms = ("最新", "新歌", "單曲", "单曲", "專輯", "专辑", "single", "album", "mv", "發行", "发行", "release", "released")
        if contains_any_keyword(haystack, freshness_terms):
            score += 12
        else:
            score -= 6
        if contains_any_keyword(title, ("YouTube", "YouTube Music", "全部歌曲")) and not contains_any_keyword(title + " " + snippet, freshness_terms):
            score -= 12
    elif mode == "music_chart":
        domain_rank = find_domain_rank(host, CHART_PREFERRED_DOMAINS)
        if domain_rank is not None:
            score += max(18, 32 - domain_rank * 3)
        chart_terms = ("排行榜", "排行", "榜單", "榜单", "週榜", "周榜", "月榜", "top 10", "top10", "前十", "單曲榜", "单曲榜")
        if contains_any_keyword(haystack, chart_terms):
            score += 18
        else:
            score -= 10
        if contains_any_keyword(title + " " + snippet, ("YouTube", "YouTube Music", "playlist", "歌單", "歌单")) and not contains_any_keyword(haystack, chart_terms):
            score -= 18
    return score


def rank_search_results(results, mode, query):
    deduped = {}
    for index, item in enumerate(results or []):
        url = clean_text((item or {}).get("url"))
        if not url:
            continue
        normalized_url = url.lower().rstrip("/")
        candidate = {
            "title": clean_text(item.get("title")),
            "snippet": clean_text(item.get("snippet")),
            "url": url,
            "source": clean_text(item.get("source")),
            "published_at": clean_text(item.get("published_at")),
            "_score": score_search_result(item, mode, query, index=index),
        }
        existing = deduped.get(normalized_url)
        if not existing or candidate["_score"] > existing["_score"]:
            deduped[normalized_url] = candidate
    ranked = sorted(
        deduped.values(),
        key=lambda item: (item["_score"], clean_text(item.get("published_at"))),
        reverse=True,
    )
    return [
        {key: value for key, value in item.items() if key != "_score"}
        for item in ranked
    ]


def parse_duckduckgo_results(html_text, limit=5):
    pattern = re.compile(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
        re.S,
    )
    results = []
    for match in pattern.finditer(html_text or ""):
        raw_url, raw_title, raw_snippet = match.groups()
        title = clean_text(re.sub(r"<.*?>", " ", html.unescape(raw_title)))
        snippet = clean_text(re.sub(r"<.*?>", " ", html.unescape(raw_snippet)))
        url = decode_duckduckgo_result_url(raw_url)
        if not title or not url:
            continue
        results.append(
            {
                "title": title,
                "snippet": snippet,
                "url": url,
                "source": result_source_label(url),
            }
        )
        if len(results) >= limit:
            break
    return results


def search_duckduckgo_web(query, limit=5):
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
    with urlopen(request, timeout=20) as response:
        raw_html = response.read().decode("utf-8", "ignore")
    return parse_duckduckgo_results(raw_html, limit=limit)


def parse_google_news_results(xml_text, limit=5):
    root = ET.fromstring(xml_text)
    results = []
    for item in root.findall("./channel/item"):
        title = clean_text(item.findtext("title"))
        link = clean_text(item.findtext("link"))
        published_raw = clean_text(item.findtext("pubDate"))
        published_label = published_raw
        if published_raw:
            try:
                published_dt = parsedate_to_datetime(published_raw).astimezone(HK_TZ)
                published_label = published_dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                published_label = published_raw
        source = ""
        if " - " in title:
            title_parts = title.rsplit(" - ", 1)
            if len(title_parts) == 2:
                title, source = title_parts
        description = clean_text(re.sub(r"<.*?>", " ", html.unescape(item.findtext("description") or "")))
        results.append(
            {
                "title": title,
                "snippet": description,
                "url": link,
                "source": source or "Google News",
                "published_at": published_label,
            }
        )
        if len(results) >= limit:
            break
    return results


def search_google_news(query, limit=5):
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
    with urlopen(request, timeout=20) as response:
        xml_text = response.read().decode("utf-8", "ignore")
    return parse_google_news_results(xml_text, limit=limit)


def search_reddit_results(query, limit=5, sort="relevance"):
    if not query:
        return []
    url = f"https://www.reddit.com/search.json?q={quote_plus(query)}&sort={quote_plus(sort)}&limit={max(1, min(int(limit), 10))}&raw_json=1"
    try:
        data = fetch_json_url(
            url,
            timeout=15,
            headers={"User-Agent": REDDIT_USER_AGENT, "Accept": "application/json"},
        )
    except Exception:
        return []
    results = []
    for row in (((data or {}).get("data") or {}).get("children") or []):
        item = (row or {}).get("data") or {}
        title = clean_text(item.get("title"))
        if not title:
            continue
        permalink = clean_text(item.get("permalink"))
        url = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else clean_text(item.get("url"))
        subreddit = clean_text(item.get("subreddit_name_prefixed") or item.get("subreddit"))
        snippet = clean_text(item.get("selftext") or item.get("url") or item.get("domain"))
        results.append(
            {
                "title": title,
                "snippet": snippet,
                "url": url,
                "source": f"Reddit {subreddit}".strip() if subreddit else "Reddit",
                "published_at": format_hk_datetime_label(item.get("created_utc")),
            }
        )
        if len(results) >= limit:
            break
    return results


def search_x_recent_posts(query, limit=5):
    if not X_BEARER_TOKEN or not query:
        return []
    core_query = strip_platform_tokens(query, ("x.com", "twitter.com"))
    search_query = clean_text(core_query or query)
    if "-is:retweet" not in search_query:
        search_query = f"{search_query} -is:retweet"
    url = (
        "https://api.x.com/2/tweets/search/recent"
        f"?query={quote_plus(search_query)}"
        f"&max_results={max(10, min(int(limit), 10))}"
        "&tweet.fields=created_at,author_id,lang"
        "&expansions=author_id"
        "&user.fields=name,username"
    )
    try:
        data = fetch_json_url(
            url,
            timeout=15,
            headers={"Authorization": f"Bearer {X_BEARER_TOKEN}", "User-Agent": "SusuCloud/1.0"},
        )
    except Exception:
        return []
    users = {}
    for user in (((data or {}).get("includes") or {}).get("users") or []):
        user_id = clean_text(user.get("id"))
        if user_id:
            users[user_id] = user
    results = []
    for item in ((data or {}).get("data") or []):
        tweet_id = clean_text(item.get("id"))
        text = clean_text(item.get("text"))
        if not tweet_id or not text:
            continue
        user = users.get(clean_text(item.get("author_id"))) or {}
        username = clean_text(user.get("username"))
        source = f"X @{username}" if username else "X"
        if username:
            post_url = f"https://x.com/{username}/status/{tweet_id}"
        else:
            post_url = f"https://x.com/i/status/{tweet_id}"
        results.append(
            {
                "title": text[:100],
                "snippet": text,
                "url": post_url,
                "source": source,
                "published_at": format_hk_datetime_label(item.get("created_at")),
            }
        )
        if len(results) >= limit:
            break
    return results


def search_youtube_videos(query, limit=5, order="date", published_after_days=None):
    if not YOUTUBE_API_KEY or not query:
        return []
    core_query = strip_platform_tokens(query, ("youtube.com", "music.youtube.com"))
    search_query = clean_text(core_query or query)
    url = (
        "https://www.googleapis.com/youtube/v3/search"
        f"?part=snippet&type=video&q={quote_plus(search_query)}"
        f"&maxResults={max(1, min(int(limit), 10))}"
        f"&order={quote_plus(order)}"
        "&regionCode=HK"
        "&relevanceLanguage=zh-Hant"
        f"&key={quote_plus(YOUTUBE_API_KEY)}"
    )
    if published_after_days:
        published_after = (datetime.now(timezone.utc) - timedelta(days=int(published_after_days))).strftime("%Y-%m-%dT%H:%M:%SZ")
        url += f"&publishedAfter={quote_plus(published_after)}"
    try:
        data = fetch_json_url(url, timeout=20)
    except Exception:
        return []
    results = []
    for item in ((data or {}).get("items") or []):
        snippet = (item or {}).get("snippet") or {}
        video_id = clean_text(((item or {}).get("id") or {}).get("videoId"))
        title = clean_text(snippet.get("title"))
        if not video_id or not title:
            continue
        results.append(
            {
                "title": title,
                "snippet": clean_text(snippet.get("description")),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "source": clean_text(snippet.get("channelTitle")) or "YouTube",
                "published_at": format_hk_datetime_label(snippet.get("publishedAt")),
            }
        )
        if len(results) >= limit:
            break
    return results


def search_music_results(query, limit=5, ranking_query=False):
    provider_batches = collect_provider_result_batches(
        [
            lambda: cached_live_json(
                ("duckduckgo_music", query),
                lambda: search_duckduckgo_web(query, limit=max(limit * 2, 8)),
                ttl_seconds=LIVE_LOOKUP_CACHE_SECONDS,
            ),
            lambda: cached_live_json(
                ("google_news_music", query),
                lambda: search_google_news(query, limit=max(limit, 5)),
                ttl_seconds=LIVE_LOOKUP_CACHE_SECONDS,
            ),
            lambda: cached_live_json(
                ("youtube_music", query),
                lambda: search_youtube_videos(query, limit=max(limit, 4), order="date", published_after_days=365),
                ttl_seconds=LIVE_LOOKUP_CACHE_SECONDS,
            ),
            lambda: cached_live_json(
                ("reddit_music", query),
                lambda: search_reddit_results(strip_platform_tokens(query, ("reddit.com",)), limit=max(limit, 4), sort="relevance"),
                ttl_seconds=LIVE_LOOKUP_CACHE_SECONDS,
            ),
            lambda: cached_live_json(
                ("x_music", query),
                lambda: search_x_recent_posts(query, limit=max(limit, 4)),
                ttl_seconds=LIVE_LOOKUP_CACHE_SECONDS,
            ),
        ],
        timeout_seconds=14,
    )
    mode = "music_chart" if ranking_query else "music"
    merged = []
    for batch in provider_batches:
        merged.extend(batch or [])
    return rank_search_results(merged, mode, query)[:limit]


def extract_quoted_titles(text, max_titles=8):
    value = clean_text(text)
    if not value:
        return []
    titles = []
    seen = set()
    for match in re.finditer(r"[《〈「『]([^《》〈〉「」『』]{1,40})[》〉」』]", value):
        title = clean_text(match.group(1)).strip("《》〈〉「」『』")
        key = normalize_key(title)
        if not title or len(title) < 2 or key in seen:
            continue
        seen.add(key)
        titles.append(title)
        if len(titles) >= max_titles:
            break
    return titles


def collect_chart_source_labels(results, limit=2):
    labels = []
    seen = set()
    for item in results or []:
        host = result_source_label(clean_text(item.get("url")))
        if find_domain_rank(host, CHART_PREFERRED_DOMAINS) is None:
            continue
        label = clean_text(item.get("source")) or host
        key = normalize_key(label)
        if not key or key in seen:
            continue
        seen.add(key)
        labels.append(label)
        if len(labels) >= limit:
            break
    return labels


def collect_music_title_candidates(results, max_titles=10):
    titles = []
    seen = set()
    for item in results or []:
        for raw_text in (item.get("title"), item.get("snippet")):
            for title in extract_quoted_titles(raw_text, max_titles=max_titles):
                key = normalize_key(title)
                if key in seen:
                    continue
                seen.add(key)
                titles.append(title)
                if len(titles) >= max_titles:
                    return titles
    return titles


def build_music_chart_guard_reply(incoming_text, results):
    if not is_ranking_query(incoming_text):
        return None
    chart_results = [
        item for item in (results or [])
        if find_domain_rank(result_source_label(clean_text(item.get("url"))), CHART_PREFERRED_DOMAINS) is not None
    ]
    titles = collect_music_title_candidates(chart_results or results, max_titles=10)
    source_labels = collect_chart_source_labels(chart_results)
    source_text = " / ".join(source_labels)
    wants_count = contains_any_keyword(incoming_text, COUNT_QUERY_HINTS)

    if chart_results and len(titles) >= 8:
        joined_titles = "、".join(f"《{title}》" for title in titles[:10])
        prefix = f"bb 我喺 {source_text} 呢啲榜單結果入面" if source_text else "bb 我喺而家搵到嘅榜單結果入面"
        return f"{prefix}明確見到排前面嘅歌有 {joined_titles}。"

    if source_text:
        if wants_count:
            return f"bb 我而家只搵到 {source_text} 相關結果，但未見到完整可靠嘅榜單內容，所以唔敢當真幫你數住。"
        return f"bb 我而家只搵到 {source_text} 相關結果，但未見到完整可靠嘅榜單內容，所以唔敢亂報歌名住。"
    if wants_count:
        return "bb 我而家未搵到一個完整可靠嘅榜單頁，所以唔敢當真幫你數住，免得同你作咗出嚟。"
    return "bb 我而家未搵到一個完整可靠嘅排行榜頁，所以唔敢亂報歌名住，免得同你作咗出嚟。"


def build_search_review_lines(results, limit=4):
    lines = []
    for index, item in enumerate(results[:limit], start=1):
        bits = [f"{index}. {clean_text(item.get('title'))}"]
        if clean_text(item.get("source")):
            bits.append(f"來源={clean_text(item.get('source'))}")
        if clean_text(item.get("published_at")):
            bits.append(f"時間={clean_text(item.get('published_at'))}")
        if clean_text(item.get("snippet")):
            bits.append(f"摘要={clean_text(item.get('snippet'))}")
        if clean_text(item.get("url")):
            bits.append(f"連結={clean_text(item.get('url'))}")
        lines.append(" | ".join(bit for bit in bits if bit))
    return lines


def review_live_search_results(incoming_text, effective_text, mode, search_query, results):
    if mode == "weather":
        return {"decision": "answer", "refined_query": "", "reason": "", "confidence": 0.99}
    review_lines = build_search_review_lines(results)
    if not review_lines:
        return {"decision": "abstain", "refined_query": "", "reason": "未搵到結果", "confidence": 0.98}

    prompt = f"""
用戶原問題：{clean_text(incoming_text)}
補充上下文：{clean_text(effective_text)}
搜尋模式：{mode}
目前 query：{clean_text(search_query)}
目前香港時間：{hk_now().strftime('%Y-%m-%d %H:%M')}

搜尋結果：
{chr(10).join(review_lines)}
""".strip()
    try:
        raw = generate_lightweight_router_text(prompt, system_prompt=LIVE_SEARCH_REVIEW_PROMPT)
        data = parse_json_object(raw)
    except Exception:
        data = {}

    decision = clean_text((data or {}).get("decision")).lower()
    if decision not in {"answer", "refine", "abstain"}:
        decision = "answer"
    refined_query = dedupe_search_terms(normalize_search_entities((data or {}).get("refined_query") or ""))
    reason = clean_text((data or {}).get("reason"))
    try:
        confidence = float((data or {}).get("confidence", 0) or 0)
    except Exception:
        confidence = 0.0
    return {
        "decision": decision,
        "refined_query": refined_query,
        "reason": reason,
        "confidence": max(0.0, min(confidence, 1.0)),
    }


def build_live_search_abstain_reply(mode, results, review_reason=""):
    source_labels = []
    seen = set()
    for item in results or []:
        label = clean_text(item.get("source")) or result_source_label(clean_text(item.get("url")))
        key = normalize_key(label)
        if not key or key in seen:
            continue
        seen.add(key)
        source_labels.append(label)
        if len(source_labels) >= 2:
            break
    source_text = " / ".join(source_labels)
    reason_text = clean_text(review_reason)
    if mode == "news":
        if source_text:
            return f"bb 我而家只搵到 {source_text} 呢批結果，但仲未夠我穩陣咁講死住。"
        return "bb 我而家搵到嘅新聞結果仲未夠穩陣，所以唔想同你講死住。"
    if mode == "music":
        if source_text:
            return f"bb 我而家只搵到 {source_text} 呢批結果，但仲未夠直接，所以唔想亂答你。"
        return "bb 我而家搵到嘅音樂結果仲未夠直接，所以唔想亂答你。"
    if source_text:
        if reason_text:
            return f"bb 我而家只搵到 {source_text} 呢批結果，但 {reason_text}，所以唔想亂答住。"
        return f"bb 我而家只搵到 {source_text} 呢批結果，但仲未夠直接，所以唔想亂答住。"
    if reason_text:
        return f"bb 我而家搵到嘅結果仲未夠穩陣，{reason_text}，所以唔想亂答住。"
    return "bb 我而家搵到嘅結果仲未夠穩陣，所以唔想亂答住。"


def fetch_live_search_results(mode, search_query, effective_text):
    if mode == "weather":
        weather_summary = build_live_weather_reply(effective_text)
        if not weather_summary:
            return []
        return [
            {
                "title": "香港天文台官方資料",
                "source": "香港天文台",
                "published_at": hk_now().strftime("%Y-%m-%d %H:%M"),
                "snippet": weather_summary,
                "url": "https://www.hko.gov.hk/",
            }
        ]
    if mode == "news":
        provider_batches = collect_provider_result_batches(
            [
                lambda: cached_live_json(
                    ("google_news", search_query),
                    lambda: search_google_news(search_query, limit=8),
                    ttl_seconds=LIVE_LOOKUP_CACHE_SECONDS,
                ),
                lambda: cached_live_json(
                    ("reddit_news", search_query),
                    lambda: search_reddit_results(strip_platform_tokens(search_query, ("reddit.com",)), limit=4, sort="new"),
                    ttl_seconds=LIVE_LOOKUP_CACHE_SECONDS,
                ),
                lambda: cached_live_json(
                    ("youtube_news", search_query),
                    lambda: search_youtube_videos(search_query, limit=4, order="date", published_after_days=7),
                    ttl_seconds=LIVE_LOOKUP_CACHE_SECONDS,
                ),
                lambda: cached_live_json(
                    ("x_news", search_query),
                    lambda: search_x_recent_posts(search_query, limit=4),
                    ttl_seconds=LIVE_LOOKUP_CACHE_SECONDS,
                ),
            ],
            timeout_seconds=14,
        )
        merged = []
        for batch in provider_batches:
            merged.extend(batch or [])
        return rank_search_results(merged, mode, search_query)
    if mode == "music":
        return search_music_results(search_query, limit=6, ranking_query=is_ranking_query(effective_text))
    explicit_domains = extract_explicit_platform_domains(effective_text or search_query)
    provider_loaders = [
        lambda: cached_live_json(
            ("duckduckgo_web", search_query),
            lambda: search_duckduckgo_web(search_query, limit=8),
            ttl_seconds=LIVE_LOOKUP_CACHE_SECONDS,
        ),
    ]
    if any(domain in explicit_domains for domain in ("reddit.com",)):
        provider_loaders.append(
            lambda: cached_live_json(
                ("reddit_web", search_query),
                lambda: search_reddit_results(strip_platform_tokens(search_query, ("reddit.com",)), limit=4, sort="relevance"),
                ttl_seconds=LIVE_LOOKUP_CACHE_SECONDS,
            )
        )
    if any(domain in explicit_domains for domain in ("youtube.com", "music.youtube.com")):
        provider_loaders.append(
            lambda: cached_live_json(
                ("youtube_web", search_query),
                lambda: search_youtube_videos(search_query, limit=4, order="relevance", published_after_days=365),
                ttl_seconds=LIVE_LOOKUP_CACHE_SECONDS,
            )
        )
    if any(domain in explicit_domains for domain in ("x.com", "twitter.com")):
        provider_loaders.append(
            lambda: cached_live_json(
                ("x_web", search_query),
                lambda: search_x_recent_posts(search_query, limit=4),
                ttl_seconds=LIVE_LOOKUP_CACHE_SECONDS,
            )
        )
    merged = []
    for batch in collect_provider_result_batches(provider_loaders, timeout_seconds=14):
        merged.extend(batch or [])
    return rank_search_results(merged, mode, search_query)


def trim_search_snippet(text, max_length=110):
    value = clean_text(text)
    if len(value) <= max_length:
        return value
    shortened = value[:max_length].rstrip("，。；、,:; ")
    return shortened + "…"


def normalize_live_search_reply(reply):
    text = str(reply or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    lines = [clean_text(line) for line in text.split("\n") if clean_text(line)]
    if not lines:
        return ""

    normalized_lines = []
    for line in lines:
        line = re.sub(r"^\s*[-*•]+\s*", "", line)
        line = re.sub(r"^\s*\d+[.)、]\s*", "", line)
        normalized_lines.append(line)

    text = "\n".join(normalized_lines)
    if len(normalized_lines) >= 3:
        text = "；".join(normalized_lines).strip()
    text = re.sub(r"([：:])\s*\n+", r"\1 ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = text.strip()
    if text.endswith(("：", ":")):
        text = text[:-1].rstrip(" ，。；、")
        if text:
            text += "。"
    return text


def extract_named_work(text):
    value = clean_text(text)
    for pattern in (r"《([^》]{1,40})》", r"「([^」]{1,40})」", r"^([^-\|]{1,40})\s*-\s*[^-\|]+$"):
        match = re.search(pattern, value)
        if match:
            name = clean_text(match.group(1)).strip("《》「」")
            if name and len(name) >= 2:
                return name
    return ""


def fallback_live_search_reply(query, mode, results):
    if not results:
        return "我啱啱上網幫你搵過，但暫時未見到夠清楚嘅結果，你想唔想我換個關鍵字再查？"
    if mode == "weather":
        top = results[0]
        snippet = clean_text(top.get("snippet"))
        return snippet or "我啱啱查咗官方天氣資料，但暫時未整理到夠清楚，你隔一陣再問我一次好唔好？"
    if mode == "news":
        pieces = []
        for item in results[:2]:
            title = clean_text(item.get("title"))
            source = clean_text(item.get("source"))
            published_at = clean_text(item.get("published_at"))
            meta = " / ".join(bit for bit in (source, published_at) if bit)
            if meta:
                pieces.append(f"{title}（{meta}）")
            else:
                pieces.append(title)
        return "我幫你睇咗最新消息，而家比較近嘅有：" + "；".join(piece for piece in pieces if piece) + "。如果你想，我可以再幫你追其中一條。"
    if mode == "music":
        top = results[0]
        title = clean_text(top.get("title"))
        source = clean_text(top.get("source"))
        snippet = clean_text(top.get("snippet"))
        work_name = extract_named_work(snippet) or extract_named_work(title)
        is_album = contains_any_keyword(title + " " + snippet, ("專輯", "专辑", "album"))
        if work_name:
            kind = "新專輯" if is_album else "新歌"
            return f"如果你係想問最新嗰首，我啱啱上網見到而家較多結果都指向{kind}《{work_name}》。你想我再幫你由呢批最新作品入面揀邊首多人講都得。"
        meta = f"（{source}）" if source else ""
        if snippet:
            return f"如果你係想問最新嗰首，我啱啱上網睇到最貼近嘅資料係 {title}{meta}；摘要提到：{trim_search_snippet(snippet)}。你想我再幫你揀下邊首多人講都得。"
        return f"如果你係想問最新嗰首，我啱啱上網搵到而家最貼近嘅結果係 {title}{meta}。你想我再幫你睇下邊首多人講都得。"

    top = results[0]
    source = clean_text(top.get("source"))
    title = clean_text(top.get("title"))
    snippet = trim_search_snippet(top.get("snippet"))
    if snippet:
        if contains_any_keyword(query, ("係唔係", "是不是", "會唔會", "有冇", "有沒有")):
            return f"我啱啱上網睇到，{source or '第一個結果'} 上面寫緊：{snippet}。如果你想，我可以再幫你睇多一兩個來源。"
        return f"我啱啱上網睇到，{title} 呢條結果最貼近你想問嘅嘢；摘要大概係：{snippet}。如果你想，我可以再幫你展開查。"
    return f"我啱啱上網搵到最貼近嘅結果係 {title}。如果你想，我可以再幫你睇多幾個來源。"


def build_live_search_reply(incoming_text, conn=None, wa_id=""):
    effective_text = expand_live_search_followup_text(conn, wa_id, incoming_text)
    plan = build_live_search_plan(effective_text)
    if not plan or not plan.get("should_search"):
        return None

    mode = plan.get("mode") or "web"
    search_query = clean_text(plan.get("query"))
    try:
        results = fetch_live_search_results(mode, search_query, effective_text)
    except Exception:
        return "我啱啱上網查資料嗰下失敗咗，未夠把握就唔想亂答，你隔一陣再問我一次好唔好？"

    if not results:
        return "我啱啱上網幫你搵過，但暫時未見到夠準嘅結果，要唔要你換個講法我再查？"

    if mode in {"news", "music", "web"}:
        review = review_live_search_results(incoming_text, effective_text, mode, search_query, results)
        if review.get("decision") == "refine":
            refined_query = clean_text(review.get("refined_query"))
            if refined_query and refined_query != search_query:
                search_query = refined_query
                try:
                    results = fetch_live_search_results(mode, search_query, effective_text)
                except Exception:
                    return "我啱啱上網查資料嗰下失敗咗，未夠把握就唔想亂答，你隔一陣再問我一次好唔好？"
                if not results:
                    return "我啱啱上網幫你搵過，但暫時未見到夠準嘅結果，要唔要你換個講法我再查？"
                review = review_live_search_results(incoming_text, effective_text, mode, search_query, results)
        if review.get("decision") == "abstain":
            music_chart_guard_reply = build_music_chart_guard_reply(effective_text, results)
            if music_chart_guard_reply:
                return music_chart_guard_reply
            return build_live_search_abstain_reply(mode, results, review_reason=review.get("reason"))

    music_chart_guard_reply = build_music_chart_guard_reply(effective_text, results)
    if music_chart_guard_reply:
        return music_chart_guard_reply

    search_lines = []
    for index, item in enumerate(results[:5], start=1):
        bits = [f"{index}. {clean_text(item.get('title'))}"]
        if clean_text(item.get("source")):
            bits.append(f"來源：{clean_text(item.get('source'))}")
        if clean_text(item.get("published_at")):
            bits.append(f"時間：{clean_text(item.get('published_at'))}")
        if clean_text(item.get("snippet")):
            bits.append(f"摘要：{clean_text(item.get('snippet'))}")
        if clean_text(item.get("url")):
            bits.append(f"連結：{clean_text(item.get('url'))}")
        search_lines.append("\n".join(bits))

    extra_context_line = ""
    if clean_text(effective_text) != clean_text(incoming_text):
        extra_context_line = f"補充上下文：{clean_text(effective_text)}\n"

    prompt = f"""
用戶剛剛問：{clean_text(incoming_text)}
{extra_context_line}實際搜尋關鍵字：{search_query}
目前香港時間：{hk_now().strftime('%Y-%m-%d %H:%M')}
搜尋模式：{"官方天氣資料" if mode == "weather" else ("最新新聞" if mode == "news" else ("音樂 / 新歌搜尋" if mode == "music" else "網頁搜尋"))}

搜尋結果：
{chr(10).join(search_lines)}

回覆要求：
- 先直接答用戶最想知嘅重點
- 只可以根據以上搜尋結果內容
- 如果係天氣 / 即時資料，直接用自然口吻講清楚重點，似蘇蘇真係幫佢查完再覆
- 如果用戶問「邊首好聽」呢類主觀問題，先講客觀可驗證部分，例如最新發行或者最近多來源提到嘅歌名，再清楚講明你只係按搜尋結果推斷
- 如果結果未夠直接回答，就講暫時見到嘅結果未夠準
- 用繁體港式廣東話，似自然 WhatsApp
- 可以好短，但要完整
- 唔好用逐行清單、項目符號，盡量用 1 到 2 句自然講完；如果真係要提幾個結果，都寫成同一句入面
- 唔好用「見到嘅係：」之後另起多行但冇內容
- 只輸出回覆本身
""".strip()
    try:
        reply = shorten_whatsapp_reply(
            normalize_live_search_reply(
            generate_model_text(
                prompt,
                temperature=0.15,
                max_tokens=220,
                system_prompt=build_live_search_system_prompt(),
            )),
            night_mode=is_night_mode(),
        )
        if reply:
            return reply
    except Exception:
        pass
    return fallback_live_search_reply(search_query, mode, results)


def normalize_key(value):
    value = clean_text(value).lower()
    value = re.sub(r"[^\w\u4e00-\u9fff]+", "", value)
    return value[:160]


def split_profile_memory_lines(value):
    lines = []
    for raw_line in str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"^\s*[-*•]+\s*", "", raw_line).strip()
        line = clean_text(line)
        if line:
            lines.append(line)
    return lines


def memories_look_duplicated(left, right):
    left_key = normalize_key(left)
    right_key = normalize_key(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    shorter, longer = (left_key, right_key) if len(left_key) <= len(right_key) else (right_key, left_key)
    if len(shorter) >= 10 and shorter in longer:
        return True
    if len(shorter) >= 8 and difflib.SequenceMatcher(None, left_key, right_key).ratio() >= 0.78:
        return True
    return False


def build_core_profile_memory_text(primary_text, max_lines=10, max_chars=1800):
    kept = []
    current_chars = 0
    for line in split_profile_memory_lines(primary_text):
        if any(memories_look_duplicated(line, existing) for existing in kept):
            continue
        next_chars = current_chars + len(line) + 2
        if kept and next_chars > max_chars:
            break
        kept.append(line)
        current_chars = next_chars
        if len(kept) >= max_lines:
            break
    if not kept:
        fallback = normalize_runtime_multiline(primary_text)
        return fallback or "（暫時未有核心檔案）"
    return "\n".join(f"- {line}" for line in kept)


def build_filtered_long_term_memory_lines(rows, primary_text, limit=20):
    primary_lines = split_profile_memory_lines(primary_text)
    kept = []
    seen_texts = []
    for row in rows:
        content = clean_text(row.get("content"))
        if not content:
            continue
        if any(memories_look_duplicated(content, primary_line) for primary_line in primary_lines):
            continue
        if any(memories_look_duplicated(content, existing) for existing in seen_texts):
            continue
        kept.append(f"- {content}")
        seen_texts.append(content)
        if len(kept) >= limit:
            break
    return kept


def primary_profile_memory_for_wa(wa_id, settings=None):
    settings = settings or get_runtime_settings()
    if (wa_id or "").strip() != ADMIN_WA_ID:
        return ""
    return settings.get("primary_user_memory", "")


def ensure_column(conn, table_name, column_name, ddl):
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wa_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wa_id TEXT NOT NULL,
            direction TEXT NOT NULL,
            message_id TEXT NOT NULL DEFAULT '',
            message_type TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            raw_json TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wa_contacts (
            wa_id TEXT PRIMARY KEY,
            profile_name TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wa_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wa_id TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'note',
            content TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wa_image_stats (
            wa_id TEXT NOT NULL,
            category TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (wa_id, category)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wa_session_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wa_id TEXT NOT NULL,
            content TEXT NOT NULL,
            memory_key TEXT NOT NULL DEFAULT '',
            bucket TEXT NOT NULL DEFAULT 'within_7d',
            observed_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wa_memory_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wa_id TEXT NOT NULL,
            content TEXT NOT NULL,
            memory_key TEXT NOT NULL DEFAULT '',
            source_bucket TEXT NOT NULL DEFAULT 'within_7d',
            observed_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            archived_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wa_proactive_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wa_id TEXT NOT NULL,
            slot_key TEXT NOT NULL DEFAULT '',
            trigger_type TEXT NOT NULL DEFAULT 'idle_check',
            probability REAL NOT NULL DEFAULT 0,
            score REAL NOT NULL DEFAULT 0,
            body TEXT NOT NULL DEFAULT '',
            prompt TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            responded_at TEXT NOT NULL DEFAULT '',
            response_delay_seconds INTEGER NOT NULL DEFAULT 0,
            reward REAL NOT NULL DEFAULT 0,
            outcome TEXT NOT NULL DEFAULT 'pending'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wa_proactive_slot_stats (
            wa_id TEXT NOT NULL,
            slot_key TEXT NOT NULL,
            success_count REAL NOT NULL DEFAULT 1,
            fail_count REAL NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (wa_id, slot_key)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wa_claude_mode (
            wa_id TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wa_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wa_id TEXT NOT NULL,
            remind_at TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            fired INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    ensure_runtime_settings_table(conn)
    ensure_column(conn, "wa_session_memories", "bucket", "bucket TEXT NOT NULL DEFAULT 'within_7d'")
    ensure_column(conn, "wa_session_memories", "observed_at", "observed_at TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "wa_memories", "memory_key", "memory_key TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "wa_memories", "created_at", "created_at TEXT NOT NULL DEFAULT ''")
    conn.execute("UPDATE wa_memories SET created_at = updated_at WHERE created_at = ''")
    normalize_recent_memory_rows(conn)
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_wa_memories_unique
        ON wa_memories (wa_id, memory_key)
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_wa_session_memories_unique
        ON wa_session_memories (wa_id, memory_key)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_wa_session_memories_bucket
        ON wa_session_memories (wa_id, bucket, updated_at DESC)
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_wa_memory_archive_unique
        ON wa_memory_archive (wa_id, memory_key, observed_at)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_wa_memory_archive_lookup
        ON wa_memory_archive (wa_id, archived_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_wa_memory_archive_observed
        ON wa_memory_archive (wa_id, observed_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_wa_proactive_events_lookup
        ON wa_proactive_events (wa_id, outcome, created_at DESC)
        """
    )
    archive_expired_session_memories(conn)
    conn.commit()
    return conn


def send_whatsapp_text(to_number, body):
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        return {"ok": False, "detail": "Missing WhatsApp credentials"}

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": body[:4096],
        },
    }
    request = Request(
        f"https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {"ok": True}


def send_whatsapp_status_update(message_id, typing=False):
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        return {"ok": False, "detail": "Missing WhatsApp credentials"}
    if not message_id:
        return {"ok": False, "detail": "Missing message_id"}

    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    if typing:
        payload["typing_indicator"] = {"type": "text"}

    request = Request(
        f"https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {"ok": True}


def send_whatsapp_mark_as_read(message_id):
    return send_whatsapp_status_update(message_id, typing=False)


def send_whatsapp_typing_indicator(message_id):
    return send_whatsapp_status_update(message_id, typing=True)


def graph_get_json(path):
    request = Request(
        f"https://graph.facebook.com/{GRAPH_VERSION}/{path.lstrip('/')}",
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
        method="GET",
    )
    with urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def download_graph_media(url):
    request = Request(
        url,
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
        method="GET",
    )
    with urlopen(request, timeout=40) as response:
        mime_type = response.headers.get_content_type() or "application/octet-stream"
        payload = response.read(MAX_IMAGE_BYTES + 1)
    if len(payload) > MAX_IMAGE_BYTES:
        raise ValueError("image_too_large")
    return payload, mime_type


def fetch_whatsapp_image(media_id):
    if not media_id or not ACCESS_TOKEN:
        return None
    metadata = graph_get_json(media_id)
    media_url = metadata.get("url")
    mime_type = metadata.get("mime_type", "")
    if not media_url or not mime_type.startswith("image/"):
        return None
    blob, header_mime = download_graph_media(media_url)
    final_mime = mime_type or header_mime or "image/jpeg"
    return {
        "media_id": media_id,
        "mime_type": final_mime,
        "bytes": blob,
        "data_b64": base64.b64encode(blob).decode("ascii"),
    }


def split_reply_bubbles(reply_text, night_mode=False):
    text = normalize_reply(reply_text)
    if not text:
        return []

    chunks = [chunk.strip() for chunk in re.split(r"\n+", text) if chunk.strip()]
    if len(chunks) >= 2:
        return chunks

    parts = re.findall(
        r".+?(?:[。！？!?~～…]+(?:[🥺😭😂😏🤭💕💖💗💘🫶✨😤🤍❤️💛💚💙💜🩷🩵]*\s*)|$)",
        text,
    )
    sentences = [part.strip() for part in parts if part.strip()]
    if len(sentences) <= 1:
        return [text]
    return sentences


def split_followup_style(bubble):
    text = clean_text(bubble)
    if len(text) < 9:
        return [text]

    splitters = ["～ ", "~ ", "🥺 ", "🥺", "。", "！", "？", "!", "?"]
    for mark in splitters:
        idx = text.find(mark)
        if idx != -1 and idx + len(mark) < len(text):
            first = text[: idx + len(mark)].strip()
            second = text[idx + len(mark) :].strip()
            if len(first) >= 3 and len(second) >= 4:
                return [first, second]

    return [text]


def maybe_stage_followup_bubbles(bubbles, night_mode=False):
    staged = [clean_text(item) for item in bubbles if clean_text(item)]
    if not staged:
        return []

    chance = 0.55 if night_mode else 0.4
    if len(staged) == 1 and random.random() < chance:
        followup = split_followup_style(staged[0])
        if len(followup) >= 2:
            return followup[:3]
    return staged


def extract_text_messages(payload):
    entries = payload.get("entry") or []
    events = []
    for entry in entries:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            contacts = value.get("contacts") or []
            contact_map = {item.get("wa_id"): item.get("profile", {}).get("name", "") for item in contacts}
            for message in value.get("messages") or []:
                wa_id = message.get("from") or ""
                message_type = message.get("type", "")
                image_payload = message.get("image") or {}
                caption = (message.get("text") or {}).get("body", "")
                if message_type == "image":
                    caption = image_payload.get("caption", "") or caption
                events.append(
                    {
                        "wa_id": wa_id,
                        "profile_name": contact_map.get(wa_id, ""),
                        "message_id": message.get("id", ""),
                        "message_type": message_type,
                        "body": caption,
                        "media_id": image_payload.get("id", ""),
                        "mime_type": image_payload.get("mime_type", ""),
                        "raw": message,
                    }
                )
    return events


def has_processed_message(conn, message_id):
    if not message_id:
        return False
    row = conn.execute(
        "SELECT 1 FROM wa_messages WHERE message_id = ? AND direction = 'inbound' LIMIT 1",
        (message_id,),
    ).fetchone()
    return bool(row)


def parse_message_context(raw_payload):
    payload = {}
    if isinstance(raw_payload, dict):
        payload = raw_payload
    else:
        try:
            payload = json.loads(raw_payload or "{}")
        except Exception:
            payload = {}
    context = payload.get("context") if isinstance(payload, dict) else {}
    if not isinstance(context, dict):
        context = {}
    return {
        "quoted_message_id": clean_text(context.get("id") or context.get("message_id")),
        "quoted_from": clean_text(context.get("from")),
    }


def load_message_lookup_by_ids(conn, wa_id, message_ids):
    cleaned_ids = []
    seen = set()
    for message_id in message_ids or []:
        value = clean_text(message_id)
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned_ids.append(value)
    if not cleaned_ids:
        return {}
    placeholders = ",".join("?" for _ in cleaned_ids)
    rows = conn.execute(
        f"""
        SELECT message_id, direction, message_type, body
        FROM wa_messages
        WHERE wa_id = ?
          AND message_id IN ({placeholders})
        """,
        [wa_id, *cleaned_ids],
    ).fetchall()
    return {clean_text(row["message_id"]): dict(row) for row in rows}


def format_quoted_message_preview(row, max_chars=48):
    if not row:
        return ""
    speaker = "蘇蘇" if clean_text(row.get("direction")) == "outbound" else "對方"
    body = clean_text(row.get("body", ""))
    message_type = clean_text(row.get("message_type", ""))
    if body:
        preview = body
    elif message_type == "image":
        preview = "send 咗一張圖"
    else:
        preview = "一則較早訊息"
    preview = preview.replace("\n", " ")
    if len(preview) > max_chars:
        preview = preview[:max_chars].rstrip() + "…"
    return f"{speaker}：「{preview}」"


def enrich_rows_with_quote_context(conn, wa_id, rows):
    items = []
    quoted_ids = []
    for row in rows or []:
        item = dict(row)
        context = parse_message_context(item.get("raw_json") or item.get("raw") or {})
        item.update(context)
        quoted_message_id = clean_text(item.get("quoted_message_id"))
        if quoted_message_id:
            quoted_ids.append(quoted_message_id)
        items.append(item)
    quoted_lookup = load_message_lookup_by_ids(conn, wa_id, quoted_ids)
    for item in items:
        quoted_message_id = clean_text(item.get("quoted_message_id"))
        if not quoted_message_id:
            continue
        quoted_row = quoted_lookup.get(quoted_message_id)
        if quoted_row:
            item["quoted_preview"] = format_quoted_message_preview(quoted_row)
        else:
            item["quoted_preview"] = "較早訊息"
    return items


def format_quote_context_suffix(item):
    quoted_message_id = clean_text(item.get("quoted_message_id"))
    if not quoted_message_id:
        return ""
    quoted_preview = clean_text(item.get("quoted_preview"))
    if quoted_preview and quoted_preview != "較早訊息":
        return f"（回覆 {quoted_preview}）"
    return "（回覆較早訊息）"


def format_quote_context_tag(item):
    quoted_message_id = clean_text(item.get("quoted_message_id"))
    if not quoted_message_id:
        return ""
    quoted_preview = clean_text(item.get("quoted_preview"))
    if quoted_preview and quoted_preview != "較早訊息":
        return f"[對方呢句係回覆緊 {quoted_preview}]"
    return "[對方呢句係回覆緊一則較早訊息]"


def mark_reply_worker_dirty(wa_id, profile_name=""):
    should_start = False
    with _reply_worker_states_lock:
        state = _reply_worker_states.setdefault(
            wa_id,
            {"version": 0, "profile_name": "", "running": False},
        )
        state["version"] += 1
        if profile_name:
            state["profile_name"] = profile_name
        if not state["running"]:
            state["running"] = True
            should_start = True
        version = state["version"]
    return should_start, version


def get_reply_worker_snapshot(wa_id):
    with _reply_worker_states_lock:
        state = _reply_worker_states.setdefault(
            wa_id,
            {"version": 0, "profile_name": "", "running": False},
        )
        return state["version"], state["profile_name"], state["running"]


def finish_reply_worker_if_idle(wa_id, observed_version):
    with _reply_worker_states_lock:
        state = _reply_worker_states.setdefault(
            wa_id,
            {"version": 0, "profile_name": "", "running": False},
        )
        if state["version"] != observed_version:
            return False
        state["running"] = False
        return True


def load_recent_messages(conn, wa_id, limit=12):
    rows = conn.execute(
        """
        SELECT direction, message_id, message_type, body, raw_json, created_at
        FROM wa_messages
        WHERE wa_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (wa_id, limit),
    ).fetchall()
    return enrich_rows_with_quote_context(conn, wa_id, reversed(rows))


def parse_iso_dt(value):
    text = clean_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return None


def normalize_recent_bucket(bucket):
    value = clean_text(bucket)
    if value in LEGACY_RECENT_BUCKETS:
        value = LEGACY_RECENT_BUCKETS[value]
    if value in RECENT_MEMORY_BUCKET_HOURS:
        return value
    return "within_7d"


def recent_bucket_label(bucket):
    return RECENT_MEMORY_BUCKET_LABELS.get(normalize_recent_bucket(bucket), "一週內")


def recent_bucket_hours(bucket):
    return RECENT_MEMORY_BUCKET_HOURS.get(normalize_recent_bucket(bucket), RECENT_MEMORY_BUCKET_HOURS["within_7d"])


def short_term_expiry(observed_at):
    observed = parse_iso_dt(observed_at) or datetime.now(timezone.utc)
    return observed.astimezone(timezone.utc) + timedelta(hours=SHORT_TERM_MEMORY_RETENTION_HOURS)


def current_recent_bucket(observed_at, now=None):
    observed = parse_iso_dt(observed_at)
    if not observed:
        return "within_7d"
    now_utc = (now or hk_now()).astimezone(timezone.utc)
    age = now_utc - observed.astimezone(timezone.utc)
    if age <= timedelta(hours=24):
        return "within_24h"
    if age <= timedelta(hours=72):
        return "within_3d"
    if age <= timedelta(hours=SHORT_TERM_MEMORY_RETENTION_HOURS):
        return "within_7d"
    return ""


def format_memory_timestamp(value):
    parsed = parse_iso_dt(value)
    if not parsed:
        return ""
    return parsed.astimezone(HK_TZ).strftime("%m-%d %H:%M")


def split_memory_clauses(incoming_text):
    text = clean_text(incoming_text)
    if not text:
        return []
    extracted = []
    seen = set()
    for piece in re.split(r"[。！？!?；;\n]+", text):
        piece = clean_text(piece)
        if not piece:
            continue
        chunks = re.split(r"[，,、]", piece) if len(piece) > 36 else [piece]
        for chunk in chunks:
            chunk = clean_text(chunk).rstrip("，。!?！？")
            key = normalize_key(chunk)
            if not key or key in seen:
                continue
            seen.add(key)
            extracted.append(chunk)
    return extracted


def classify_recent_memory_bucket(text, observed_at=None, now=None):
    value = clean_text(text)
    if any(marker in value for marker in RECENT_24H_MARKERS):
        return "within_24h"
    if any(marker in value for marker in RECENT_3D_MARKERS):
        return "within_3d"
    if any(marker in value for marker in RECENT_7D_MARKERS):
        return "within_7d"
    if TIME_SCHEDULE_RE.search(value) and any(marker in value for marker in RECENT_TASK_HINTS):
        return "within_24h"
    if any(marker in value for marker in RECENT_TASK_HINTS):
        return "within_7d"
    parsed = parse_iso_dt(observed_at)
    if parsed:
        now_utc = (now or hk_now()).astimezone(timezone.utc)
        age = now_utc - parsed.astimezone(timezone.utc)
        if age <= timedelta(hours=24):
            return "within_24h"
        if age <= timedelta(hours=72):
            return "within_3d"
    return "within_7d"


def is_recent_memory_candidate(text):
    value = clean_text(text)
    if len(value) < 4 or len(value) > 120:
        return False
    has_temporal_hint = (
        any(marker in value for marker in RECENT_24H_MARKERS + RECENT_3D_MARKERS + RECENT_7D_MARKERS)
        or bool(TIME_SCHEDULE_RE.search(value))
    )
    if not has_temporal_hint:
        return False
    if any(marker in value for marker in STABLE_MEMORY_HINTS) and not any(marker in value for marker in RECENT_TASK_HINTS):
        return False
    if any(marker in value for marker in RECENT_TASK_HINTS + RECENT_ACTION_HINTS):
        return True
    return bool(TIME_SCHEDULE_RE.search(value))


def is_long_term_memory_candidate(text):
    value = clean_text(text)
    if len(value) < 4 or len(value) > 120:
        return False
    if is_recent_memory_candidate(value):
        return False
    if TIME_SCHEDULE_RE.search(value) and any(marker in value for marker in ("課", "上堂", "上課", "開會", "开会", "report", "deadline", "pre")):
        return False
    return True


def normalize_recent_memory_rows(conn):
    rows = conn.execute(
        """
        SELECT id, bucket, content, memory_key, observed_at, updated_at, expires_at
        FROM wa_session_memories
        """
    ).fetchall()
    for row in rows:
        bucket = normalize_recent_bucket(row["bucket"])
        observed = parse_iso_dt(row["observed_at"] or row["updated_at"]) or datetime.now(timezone.utc)
        observed_text = observed.astimezone(timezone.utc).isoformat()
        expires_text = short_term_expiry(observed_text).isoformat()
        scoped_key = f"{bucket}:{normalize_key(row['content'])}"
        if (
            row["bucket"] != bucket
            or clean_text(row["observed_at"]) != observed_text
            or clean_text(row["expires_at"]) != expires_text
            or clean_text(row["memory_key"]) != scoped_key
        ):
            conn.execute(
                """
                UPDATE wa_session_memories
                SET bucket = ?, observed_at = ?, expires_at = ?, memory_key = ?
                WHERE id = ?
                """,
                (bucket, observed_text, expires_text, scoped_key, row["id"]),
            )


def archive_expired_session_memories(conn, now=None):
    now_utc = (now or hk_now()).astimezone(timezone.utc)
    rows = conn.execute(
        """
        SELECT id, wa_id, content, memory_key, bucket, observed_at, updated_at, expires_at
        FROM wa_session_memories
        WHERE expires_at != '' AND expires_at <= ?
        ORDER BY observed_at ASC, id ASC
        """,
        (now_utc.isoformat(),),
    ).fetchall()
    for row in rows:
        content = clean_text(row["content"])
        archive_key = normalize_key(content)
        if not content or not archive_key:
            conn.execute("DELETE FROM wa_session_memories WHERE id = ?", (row["id"],))
            continue
        observed = parse_iso_dt(row["observed_at"] or row["updated_at"]) or now_utc
        observed_text = observed.astimezone(timezone.utc).isoformat()
        updated_text = clean_text(row["updated_at"]) or observed_text
        conn.execute(
            """
            INSERT INTO wa_memory_archive (
                wa_id, content, memory_key, source_bucket, observed_at, updated_at, archived_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(wa_id, memory_key, observed_at) DO UPDATE SET
                content = excluded.content,
                source_bucket = excluded.source_bucket,
                updated_at = excluded.updated_at,
                archived_at = excluded.archived_at
            """,
            (
                row["wa_id"],
                content,
                archive_key,
                normalize_recent_bucket(row["bucket"]),
                observed_text,
                updated_text,
                now_utc.isoformat(),
            ),
        )
        conn.execute("DELETE FROM wa_session_memories WHERE id = ?", (row["id"],))


def should_lookup_archive(text):
    value = clean_text(text)
    if not value:
        return False
    if not any(marker in value for marker in ARCHIVE_LOOKUP_TIME_MARKERS):
        return False
    return any(marker in value for marker in MEMORY_RECALL_MARKERS + ARCHIVE_SEARCH_MARKERS)


def archive_query_keywords(text):
    value = clean_text(text).lower()
    if not value:
        return []

    tokens = []
    seen = set()

    def push(token):
        token = clean_text(token).lower()
        if not token:
            return
        if token in seen:
            return
        seen.add(token)
        tokens.append(token)

    for marker in ARCHIVE_SEARCH_MARKERS:
        if marker in value:
            push(marker)

    sanitized = value
    for marker in ARCHIVE_LOOKUP_TIME_MARKERS + MEMORY_RECALL_MARKERS:
        sanitized = sanitized.replace(marker.lower(), " ")

    for token in re.findall(r"[a-z0-9_]{2,}", sanitized):
        push(token)

    for segment in re.findall(r"[\u4e00-\u9fff]{2,}", sanitized):
        compact = "".join(ch for ch in segment if ch not in ARCHIVE_CJK_STOP_CHARS)
        if not compact:
            continue
        if len(compact) == 1:
            push(compact)
            continue
        upper = min(4, len(compact))
        for size in range(upper, 1, -1):
            for start in range(0, len(compact) - size + 1):
                push(compact[start : start + size])
                if len(tokens) >= 24:
                    return tokens

    return tokens


def load_archived_memory_rows(conn, wa_id, limit=4, query_text=""):
    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT content, source_bucket, observed_at, updated_at, archived_at
            FROM wa_memory_archive
            WHERE wa_id = ?
            ORDER BY observed_at DESC, archived_at DESC, id DESC
            LIMIT 120
            """,
            (wa_id,),
        ).fetchall()
    ]
    if not rows:
        return []

    keywords = archive_query_keywords(query_text)
    if not keywords:
        return rows[:limit]

    scored = []
    for row in rows:
        haystack = clean_text(row.get("content", "")).lower()
        if not haystack:
            continue
        score = 0
        for token in keywords:
            if token in haystack:
                score += max(len(token), 1)
        if score <= 0:
            continue
        observed = parse_iso_dt(row.get("observed_at") or row.get("updated_at"))
        scored.append((score, observed or datetime.min.replace(tzinfo=timezone.utc), row))

    if not scored:
        return rows[:limit]

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in scored[:limit]]


def format_archived_memory_lines(rows, limit=4):
    formatted = []
    seen = set()
    for row in rows[:limit]:
        content = clean_text(row.get("content", ""))
        if not content:
            continue
        key = normalize_key(content)
        if key in seen:
            continue
        seen.add(key)
        stamp = format_memory_timestamp(row.get("observed_at") or row.get("updated_at", ""))
        if stamp:
            formatted.append(f"- [過往 | {stamp}] {content}")
        else:
            formatted.append(f"- [過往] {content}")
    return formatted


def get_last_message_time(conn, wa_id, direction=None):
    sql = """
        SELECT created_at
        FROM wa_messages
        WHERE wa_id = ?
    """
    params = [wa_id]
    if direction:
        sql += " AND direction = ?"
        params.append(direction)
    sql += " ORDER BY id DESC LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    return parse_iso_dt(row["created_at"]) if row else None


def get_last_message_row(conn, wa_id):
    row = conn.execute(
        """
        SELECT direction, message_type, body, created_at
        FROM wa_messages
        WHERE wa_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (wa_id,),
    ).fetchone()
    return dict(row) if row else None


def count_inbound_messages(conn, wa_id):
    row = conn.execute(
        """
        SELECT COUNT(*) AS total
        FROM wa_messages
        WHERE wa_id = ? AND direction = 'inbound' AND message_type IN ('text', 'image')
        """,
        (wa_id,),
    ).fetchone()
    return int(row["total"]) if row else 0


def count_proactive_for_service_day(conn, wa_id, now=None):
    now = now or hk_now()
    start_text = service_day_start(now).astimezone(timezone.utc).isoformat()
    row = conn.execute(
        """
        SELECT COUNT(*) AS total
        FROM wa_proactive_events
        WHERE wa_id = ?
          AND created_at >= ?
          AND outcome IN ('pending', 'replied', 'ignored')
        """,
        (wa_id, start_text),
    ).fetchone()
    return int(row["total"]) if row else 0


def get_pending_proactive_event(conn, wa_id):
    row = conn.execute(
        """
        SELECT *
        FROM wa_proactive_events
        WHERE wa_id = ? AND outcome = 'pending'
        ORDER BY id DESC
        LIMIT 1
        """,
        (wa_id,),
    ).fetchone()
    return dict(row) if row else None


def get_last_proactive_event(conn, wa_id):
    row = conn.execute(
        """
        SELECT *
        FROM wa_proactive_events
        WHERE wa_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (wa_id,),
    ).fetchone()
    return dict(row) if row else None


def get_slot_success_rate(conn, wa_id, slot_key):
    row = conn.execute(
        """
        SELECT success_count, fail_count
        FROM wa_proactive_slot_stats
        WHERE wa_id = ? AND slot_key = ?
        """,
        (wa_id, slot_key),
    ).fetchone()
    if not row:
        return 0.5
    success = float(row["success_count"])
    failure = float(row["fail_count"])
    return success / max(success + failure, 1.0)


def bump_proactive_slot_outcome(conn, wa_id, slot_key, success):
    now_text = utc_now()
    conn.execute(
        """
        INSERT INTO wa_proactive_slot_stats (wa_id, slot_key, success_count, fail_count, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(wa_id, slot_key) DO UPDATE SET
            success_count = wa_proactive_slot_stats.success_count + excluded.success_count,
            fail_count = wa_proactive_slot_stats.fail_count + excluded.fail_count,
            updated_at = excluded.updated_at
        """,
        (
            wa_id,
            slot_key,
            1 if success else 0,
            0 if success else 1,
            now_text,
        ),
    )


def finalize_stale_proactive_events(conn, wa_id=None):
    settings = get_runtime_settings()
    reply_window_minutes = int(settings["proactive_reply_window_minutes"])
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=reply_window_minutes)).isoformat()
    sql = """
        SELECT id, wa_id, slot_key
        FROM wa_proactive_events
        WHERE outcome = 'pending'
          AND created_at < ?
    """
    params = [cutoff]
    if wa_id:
        sql += " AND wa_id = ?"
        params.append(wa_id)
    rows = conn.execute(sql, params).fetchall()
    for row in rows:
        conn.execute(
            """
            UPDATE wa_proactive_events
            SET outcome = 'ignored', reward = 0
            WHERE id = ?
            """,
            (row["id"],),
        )
        bump_proactive_slot_outcome(conn, row["wa_id"], row["slot_key"], False)


def mark_proactive_reply(conn, wa_id, inbound_at_text):
    inbound_at = parse_iso_dt(inbound_at_text)
    if not inbound_at:
        return
    settings = get_runtime_settings()
    reply_window_minutes = int(settings["proactive_reply_window_minutes"])
    row = conn.execute(
        """
        SELECT id, created_at, slot_key
        FROM wa_proactive_events
        WHERE wa_id = ?
          AND outcome = 'pending'
        ORDER BY id DESC
        LIMIT 1
        """,
        (wa_id,),
    ).fetchone()
    if not row:
        return
    proactive_at = parse_iso_dt(row["created_at"])
    if not proactive_at or inbound_at <= proactive_at:
        return
    delay = int((inbound_at - proactive_at).total_seconds())
    if delay > reply_window_minutes * 60:
        return
    conn.execute(
        """
        UPDATE wa_proactive_events
        SET responded_at = ?, response_delay_seconds = ?, reward = 1, outcome = 'replied'
        WHERE id = ?
        """,
        (inbound_at_text, delay, row["id"]),
    )
    bump_proactive_slot_outcome(conn, wa_id, row["slot_key"], True)


def get_latest_inbound_id(conn, wa_id):
    row = conn.execute(
        """
        SELECT id
        FROM wa_messages
        WHERE wa_id = ? AND direction = 'inbound'
        ORDER BY id DESC
        LIMIT 1
        """,
        (wa_id,),
    ).fetchone()
    return int(row["id"]) if row else 0


def get_latest_inbound_id_for_wa(wa_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT id
            FROM wa_messages
            WHERE wa_id = ? AND direction = 'inbound'
            ORDER BY id DESC
            LIMIT 1
            """,
            (wa_id,),
        ).fetchone()
        return int(row["id"]) if row else 0
    finally:
        conn.close()


def load_pending_inbound_batch(conn, wa_id, current_inbound_id):
    last_outbound = conn.execute(
        """
        SELECT COALESCE(MAX(id), 0) AS last_outbound_id
        FROM wa_messages
        WHERE wa_id = ? AND direction = 'outbound' AND message_type = 'text'
        """,
        (wa_id,),
    ).fetchone()
    last_outbound_id = int(last_outbound["last_outbound_id"]) if last_outbound else 0
    rows = conn.execute(
        """
        SELECT id, message_id, body, message_type, raw_json
        FROM wa_messages
        WHERE wa_id = ?
          AND direction = 'inbound'
          AND id > ?
          AND id <= ?
          AND message_type IN ('text', 'image')
        ORDER BY id ASC
        """,
        (wa_id, last_outbound_id, current_inbound_id),
    ).fetchall()
    return [dict(row) for row in rows]


def load_memories(conn, wa_id):
    rows = conn.execute(
        """
        SELECT kind, content
        FROM wa_memories
        WHERE wa_id = ?
        ORDER BY updated_at DESC, id DESC
        LIMIT 20
        """,
        (wa_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def load_session_memories(conn, wa_id, limit=8, bucket=None):
    now = hk_now()
    target_bucket = normalize_recent_bucket(bucket) if bucket else ""
    rows = conn.execute(
        """
        SELECT content, observed_at, updated_at, expires_at
        FROM wa_session_memories
        WHERE wa_id = ?
          AND expires_at > ?
        ORDER BY updated_at DESC, id DESC
        LIMIT 80
        """,
        (wa_id, now.astimezone(timezone.utc).isoformat()),
    ).fetchall()
    items = []
    for row in rows:
        current_bucket_value = current_recent_bucket(row["observed_at"] or row["updated_at"], now)
        if target_bucket and current_bucket_value != target_bucket:
            continue
        content = clean_text(row["content"])
        if content:
            items.append(content)
        if len(items) >= limit:
            break
    return items


def upsert_session_memory(conn, wa_id, content, bucket="within_7d", ttl_hours=None, observed_at=None, updated_at_text=None):
    text = clean_text(content)
    if not text:
        return False
    key = normalize_key(text)
    if not key:
        return False
    bucket = normalize_recent_bucket(bucket)
    observed = parse_iso_dt(observed_at) or datetime.now(timezone.utc)
    now = datetime.now(timezone.utc)
    if ttl_hours is None:
        ttl_hours = SHORT_TERM_MEMORY_RETENTION_HOURS
    scoped_key = f"{bucket}:{key}"
    expires_at_text = (observed.astimezone(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()
    observed_at_text = observed.astimezone(timezone.utc).isoformat()
    now_text = clean_text(updated_at_text) or now.isoformat()
    conn.execute(
        """
        INSERT INTO wa_session_memories (wa_id, content, memory_key, bucket, observed_at, updated_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(wa_id, memory_key) DO UPDATE SET
            content = excluded.content,
            bucket = excluded.bucket,
            observed_at = excluded.observed_at,
            updated_at = excluded.updated_at,
            expires_at = excluded.expires_at
        """,
        (wa_id, text, scoped_key, bucket, observed_at_text, now_text, expires_at_text),
    )
    return True


def build_combined_user_input(rows, conn=None, wa_id=""):
    enriched_rows = enrich_rows_with_quote_context(conn, wa_id, rows) if conn and wa_id else [dict(row) for row in rows]
    lines = []
    text_only_lines = []
    for row in enriched_rows:
        message_type = row.get("message_type", "")
        body = clean_text(row.get("body", ""))
        quote_tag = format_quote_context_tag(row)
        if quote_tag:
            lines.append(quote_tag)
        if message_type == "text":
            if body:
                lines.append(body)
                text_only_lines.append(body)
            continue
        if message_type == "image":
            if body:
                lines.append(f"[對方send咗圖，caption：{body}]")
            else:
                lines.append("[對方send咗圖畀你]")
    return "\n".join(lines).strip(), "\n".join(text_only_lines).strip()


def collect_image_inputs(rows):
    images = []
    for row in rows:
        if row.get("message_type") != "image":
            continue
        raw = {}
        try:
            raw = json.loads(row.get("raw_json") or "{}")
        except json.JSONDecodeError:
            raw = {}
        image_payload = raw.get("image") or {}
        media_id = image_payload.get("id", "")
        if not media_id:
            continue
        try:
            image_data = fetch_whatsapp_image(media_id)
        except Exception:
            image_data = None
        if not image_data:
            continue
        image_data["caption"] = clean_text(image_payload.get("caption", "") or row.get("body", ""))
        images.append(image_data)
        if len(images) >= MAX_IMAGE_ATTACHMENTS:
            break
    return images


def upsert_memory(conn, wa_id, content, kind="note"):
    text = clean_text(content)
    if not text:
        return False
    key = normalize_key(text)
    if not key:
        return False
    now = utc_now()
    conn.execute(
        """
        INSERT INTO wa_memories (wa_id, kind, content, memory_key, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(wa_id, memory_key) DO UPDATE SET
            kind = excluded.kind,
            content = excluded.content,
            updated_at = excluded.updated_at
        """,
        (wa_id, kind, text, key, now, now),
    )
    return True


def parse_json_array(raw_text):
    text = (raw_text or "").strip()
    if not text:
        return []
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def parse_json_object(raw_text):
    text = (raw_text or "").strip()
    if not text:
        return {}
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def heuristic_extract_memories(incoming_text):
    text = clean_text(incoming_text)
    extra = []
    lowered = text.lower()
    sleep_boundaries = [
        "不要催我睡觉",
        "不要催我睡覺",
        "唔好催我瞓",
        "唔好催我訓",
        "别催我睡觉",
        "別催我睡覺",
        "不催我睡觉",
        "不催我睡覺",
    ]
    if any(item in text or item in lowered for item in sleep_boundaries):
        extra.append("Simon夜晚唔鍾意被催瞓，除非佢主動話想瞓或者叫你哄佢瞓。")
    patterns = [
        r"^(我最近開始[^。！？!?]{4,60})",
        r"^(我而家用[^。！？!?]{4,60})",
        r"^(我一直用[^。！？!?]{4,60})",
        r"^(我平時用[^。！？!?]{4,60})",
        r"^(我鍾意[^。！？!?]{2,60})",
        r"^(我最鍾意[^。！？!?]{2,60})",
        r"^(我平時都會[^。！？!?]{3,60})",
        r"^(我通常會[^。！？!?]{3,60})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return [match.group(1).rstrip("，")]
    return []


def call_gemini(prompt_text, temperature=0.82, max_tokens=220, system_prompt=None, image_inputs=None):
    settings = get_runtime_settings()
    effective_system_prompt = system_prompt or settings["system_persona"]
    gemini_model = normalize_runtime_text(settings.get("gemini_model"), GEMINI_MODEL)
    parts = [{"text": prompt_text}]
    for item in image_inputs or []:
        parts.append(
            {
                "inline_data": {
                    "mime_type": item["mime_type"],
                    "data": item["data_b64"],
                }
            }
        )
    payload = {
        "system_instruction": {"parts": [{"text": effective_system_prompt}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": temperature,
            "topP": 0.9,
            "maxOutputTokens": max_tokens,
        },
    }
    request = Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={GEMINI_API_KEY}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=40) as response:
        raw = response.read().decode("utf-8")
        data = json.loads(raw) if raw else {}
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts = (((candidates[0] or {}).get("content") or {}).get("parts")) or []
    texts = [part.get("text", "") for part in parts if part.get("text")]
    return "\n".join(texts).strip()


def call_openai_compatible(prompt_text, api_key, model, base_url, temperature=0.82, max_tokens=220, system_prompt=None, image_inputs=None):
    effective_system_prompt = system_prompt or get_runtime_settings()["system_persona"]
    user_content = prompt_text
    if image_inputs:
        user_content = [{"type": "text", "text": prompt_text}]
        for item in image_inputs:
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{item['mime_type']};base64,{item['data_b64']}",
                    },
                }
            )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": effective_system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    request = Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=40) as response:
        raw = response.read().decode("utf-8")
        data = json.loads(raw) if raw else {}
    choices = data.get("choices") or []
    if not choices:
        return ""
    return ((choices[0] or {}).get("message") or {}).get("content", "").strip()


def call_relay_model(model_name, prompt_text, temperature=0.82, max_tokens=220, system_prompt=None, image_inputs=None):
    if not RELAY_API_KEY or not model_name:
        return ""
    return call_openai_compatible(
        prompt_text,
        api_key=RELAY_API_KEY,
        model=model_name,
        base_url=RELAY_BASE_URL,
        temperature=temperature,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
        image_inputs=image_inputs,
    )


def call_minimax(prompt_text, temperature=0.82, max_tokens=220, system_prompt=None, image_inputs=None):
    if not MINIMAX_API_KEY:
        return ""
    return call_openai_compatible(
        prompt_text,
        api_key=MINIMAX_API_KEY,
        model=MINIMAX_MODEL,
        base_url=MINIMAX_BASE_URL,
        temperature=temperature,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
        image_inputs=image_inputs,
    )


def call_groq(prompt_text, temperature=0.82, max_tokens=220, system_prompt=None, image_inputs=None):
    if not GROQ_API_KEY:
        return ""
    return call_openai_compatible(
        prompt_text,
        api_key=GROQ_API_KEY,
        model=GROQ_MODEL,
        base_url="https://api.groq.com/openai/v1",
        temperature=temperature,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
        image_inputs=image_inputs,
    )


def generate_model_text(prompt_text, temperature=0.82, max_tokens=220, system_prompt=None, image_inputs=None):
    errors = []
    relay_primary, _ = get_relay_model_order()

    if RELAY_API_KEY and relay_primary:
        try:
            return call_relay_model(relay_primary, prompt_text, temperature=temperature, max_tokens=max_tokens, system_prompt=system_prompt, image_inputs=image_inputs)
        except HTTPError as exc:
            errors.append(f"relay_http_{exc.code}")
            if exc.code not in (401, 403, 429, 500, 502, 503, 504):
                raise
        except Exception as exc:
            errors.append(f"relay_failed:{type(exc).__name__}")

    if errors:
        raise RuntimeError(";".join(errors))
    return ""


def generate_lightweight_router_text(prompt_text, system_prompt=None):
    errors = []
    relay_primary, _ = get_relay_model_order()

    if RELAY_API_KEY and relay_primary:
        try:
            return call_relay_model(relay_primary, prompt_text, temperature=0.0, max_tokens=160, system_prompt=system_prompt)
        except HTTPError as exc:
            errors.append(f"router_relay_http_{exc.code}")
            if exc.code not in (401, 403, 429, 500, 502, 503, 504):
                raise
        except Exception as exc:
            errors.append(f"router_relay_failed:{type(exc).__name__}")

    if errors:
        raise RuntimeError(";".join(errors))
    return ""


def extract_preference_memories(incoming_text):
    text = clean_text(incoming_text)
    lowered = text.lower()
    extracted = []
    if any(item in text or item in lowered for item in [
        "不要催我睡觉",
        "不要催我睡覺",
        "唔好催我瞓",
        "唔好催我訓",
        "不催我睡觉",
        "不催我睡覺",
        "別催我睡覺",
        "别催我睡觉",
    ]):
        extracted.append("Simon夜晚唔鍾意被催瞓，除非佢主動話想瞓或者叫你哄佢瞓。")
    return extracted


def load_image_stats_summary(conn, wa_id):
    rows = conn.execute(
        """
        SELECT category, count
        FROM wa_image_stats
        WHERE wa_id = ?
        ORDER BY count DESC, category ASC
        LIMIT 4
        """,
        (wa_id,),
    ).fetchall()
    if not rows:
        return ""
    return "、".join(f"{row['category']}({row['count']})" for row in rows if row["count"] > 0)


def has_sleep_boundary(conn, wa_id):
    row = conn.execute(
        """
        SELECT 1
        FROM wa_memories
        WHERE wa_id = ? AND content LIKE '%唔鍾意被催瞓%'
        LIMIT 1
        """,
        (wa_id,),
    ).fetchone()
    return bool(row)


def contains_sleep_nag(text):
    value = clean_text(text)
    markers = ["快啲瞓", "快啲訓", "閉眼", "去瞓", "去訓", "要瞓", "該瞓", "快啲去躺低", "早啲瞓", "早点睡", "早點睡"]
    return any(marker in value for marker in markers)


def bump_image_stats(conn, wa_id, categories):
    now = utc_now()
    for category in categories:
        if not category:
            continue
        conn.execute(
            """
            INSERT INTO wa_image_stats (wa_id, category, count, updated_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(wa_id, category) DO UPDATE SET
                count = count + 1,
                updated_at = excluded.updated_at
            """,
            (wa_id, category, now),
        )


def heuristic_image_categories(incoming_text, image_inputs):
    text = clean_text(incoming_text).lower()
    caption_text = " ".join(clean_text(item.get("caption", "")).lower() for item in image_inputs or [])
    joined = f"{text} {caption_text}".strip()
    categories = []
    rules = [
        ("screenshot", ["screenshot", "截圖", "cap圖", "screen shot", "對話紀錄", "聊天記錄"]),
        ("自拍", ["自拍", "selfie", "個樣", "我樣", "我個樣"]),
        ("食物", ["食", "飲", "早餐", "午餐", "晚餐", "宵夜", "杯麵", "可樂", "c.c. lemon", "凍檸樂", "梅酒"]),
        ("風景", ["風景", "街景", "海邊", "日落", "夜景", "攝影", "影相", "天空", "海", "山"]),
    ]
    for category, keywords in rules:
        if any(keyword in joined for keyword in keywords):
            categories.append(category)
    return categories or ["其他"]


def classify_image_categories(incoming_text, image_inputs):
    if not image_inputs:
        return []
    prompt = f"""
你係圖片分類器。
只可以由以下類別揀最多兩個：
- 自拍
- 食物
- 風景
- screenshot
- 其他

caption / 文字：
{clean_text(incoming_text)}

只輸出 JSON array，例如 ["自拍"]。
唔好解釋。
""".strip()
    try:
        raw = generate_model_text(prompt, temperature=0.1, max_tokens=40, image_inputs=image_inputs)
        categories = []
        for item in parse_json_array(raw):
            if isinstance(item, str):
                text = clean_text(item)
                if text in {"自拍", "食物", "風景", "screenshot", "其他"} and text not in categories:
                    categories.append(text)
        if categories:
            return categories[:2]
    except Exception:
        pass
    return heuristic_image_categories(incoming_text, image_inputs)


def image_reply_guidance(categories):
    category_set = set(categories or [])
    notes = []
    if "自拍" in category_set:
        notes.append("- 如果係自拍，先自然讚佢個樣、狀態或者氣質，唔好太公式化。")
    if "食物" in category_set:
        notes.append("- 如果係食物，相對應該先講睇落去好唔好食、想唔想食，再輕輕追問喺邊度食。")
    if "風景" in category_set:
        notes.append("- 如果係風景或者攝影作品，優先讚構圖、光線、氣氛或者色調，似真係有睇相。")
    if "screenshot" in category_set:
        notes.append("- 如果係 screenshot，先回應圖入面資訊本身，唔好盲目讚張圖。")
    if "其他" in category_set and not notes:
        notes.append("- 如果未必分到類，就自然講你睇到啲咩，再輕輕追問。")
    return "\n".join(notes)


def maybe_extract_memories(conn, wa_id, profile_name, incoming_text):
    existing = [item["content"] for item in load_memories(conn, wa_id)]
    existing_text = "\n".join(f"- {item}" for item in existing) if existing else "（暫時未有）"
    prompt = f"""
對方顯示名稱：{profile_name or "對方"}
現有記憶：
{existing_text}

對方剛剛講：
{clean_text(incoming_text)}

只抽取以下類型：
- 穩定背景（學校、住處、工作、長期使用的器材）
- 穩定偏好（飲食、興趣、喜歡的作品、常用服務）
- 明確的人際稱呼或聊天偏好
- 跨一星期仍然有價值嘅長期計劃

不要抽取：
- 今日、今晚、尋晚、明天、呢幾日、呢星期內先有用嘅事情
- 明確時段、課堂時間、會議時間、deadline、短期任務
- 一次性情緒
- 很短暫的行程
- 已經重複的內容
- 太私密或太敏感的細節

最多 3 項。
""".strip()

    extracted = []
    try:
        raw = generate_model_text(prompt, temperature=0.2, max_tokens=180, system_prompt=MEMORY_EXTRACTOR_PROMPT)
        for item in parse_json_array(raw):
            if isinstance(item, str):
                text = clean_text(item)
                if is_long_term_memory_candidate(text):
                    extracted.append(text)
    except Exception:
        extracted = []

    if not extracted:
        extracted = [item for item in heuristic_extract_memories(incoming_text) if is_long_term_memory_candidate(item)]

    extracted = extract_preference_memories(incoming_text) + extracted

    seen = set()
    deduped = []
    for item in extracted:
        key = normalize_key(item)
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)

    saved = []
    for item in deduped[:4]:
        if is_long_term_memory_candidate(item) and upsert_memory(conn, wa_id, item, kind="auto"):
            saved.append(item)
    if saved:
        conn.commit()
    return saved


def heuristic_extract_session_memories(incoming_text):
    extracted = []
    for clause in split_memory_clauses(incoming_text):
        if not is_recent_memory_candidate(clause):
            continue
        extracted.append(
            {
                "bucket": classify_recent_memory_bucket(clause),
                "content": clause,
            }
        )

    deduped = []
    seen = set()
    for item in extracted:
        dedupe_key = f'{normalize_recent_bucket(item["bucket"])}:{normalize_key(item["content"])}'
        if dedupe_key and dedupe_key not in seen:
            seen.add(dedupe_key)
            deduped.append(
                {
                    "bucket": normalize_recent_bucket(item["bucket"]),
                    "content": clean_text(item["content"]).rstrip("，。!?！？"),
                }
            )
    return deduped[:4]


def extract_live_search_question_memory(incoming_text):
    plan = build_live_search_plan(incoming_text)
    if not plan or not plan.get("should_search"):
        return None
    value = clean_text(incoming_text).rstrip("，。!?！？")
    if len(value) < 4:
        return None
    return {
        "bucket": "within_24h",
        "content": f"對方啱啱問過：{value}",
    }


def maybe_extract_session_memories(conn, wa_id, incoming_text):
    prompt = f"""
對方剛剛講：
{clean_text(incoming_text)}

請抽取值得保留嘅短期記憶，分類只可以用以下三種：
- within_24h：24 小時內，例如而家、今日、今晚、頭先、啱啱、今日課堂安排
- within_3d：三天內，例如尋晚、昨日、明天、後天、呢兩三日
- within_7d：一星期內，例如最近幾日、今個星期、近期要完成嘅短任務

不要抽取：
- 長期背景、長期偏好、長期習慣
- 冇資訊量嘅撒嬌、純情緒、客套句
- 太私密或太敏感細節
- 但如果對方啱啱問即時資訊，例如新聞、天氣、最新作品、股價、比賽結果，呢條「問過咩」本身都算短期記憶

最多 4 項。
""".strip()

    extracted = []
    try:
        raw = generate_model_text(prompt, temperature=0.15, max_tokens=220, system_prompt=RECENT_MEMORY_EXTRACTOR_PROMPT)
        for item in parse_json_array(raw):
            if not isinstance(item, dict):
                continue
            content = clean_text(item.get("content"))
            bucket = normalize_recent_bucket(item.get("bucket"))
            if is_recent_memory_candidate(content):
                extracted.append({"bucket": bucket, "content": content})
    except Exception:
        extracted = []

    if not extracted:
        extracted = heuristic_extract_session_memories(incoming_text)

    live_search_question = extract_live_search_question_memory(incoming_text)
    if live_search_question:
        extracted.insert(0, live_search_question)

    saved = []
    for item in extracted:
        if upsert_session_memory(conn, wa_id, item["content"], bucket=item["bucket"]):
            saved.append(item["content"])
    if saved:
        conn.commit()
    return saved


def load_session_memory_rows(conn, wa_id, limit=8, bucket=None):
    now = hk_now()
    target_bucket = normalize_recent_bucket(bucket) if bucket else ""
    rows = conn.execute(
        """
        SELECT content, bucket, observed_at, updated_at, expires_at
        FROM wa_session_memories
        WHERE wa_id = ?
          AND expires_at > ?
        ORDER BY updated_at DESC, id DESC
        LIMIT 80
        """,
        (wa_id, now.astimezone(timezone.utc).isoformat()),
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["current_bucket"] = current_recent_bucket(item.get("observed_at") or item.get("updated_at"), now)
        if target_bucket and item["current_bucket"] != target_bucket:
            continue
        items.append(item)
        if len(items) >= limit:
            break
    return items


def current_service_day_key(now=None):
    now = now or hk_now()
    if now.hour < 5:
        return (now - timedelta(days=1)).date()
    return now.date()


def normalize_session_content(content):
    return clean_text(content)


def format_session_memory_lines(conn, wa_id, bucket, limit=6):
    rows = load_session_memory_rows(conn, wa_id, limit=limit, bucket=bucket)
    if not rows:
        return []
    formatted = []
    seen = set()
    for row in rows:
        content = normalize_session_content(row.get("content", ""))
        if not content:
            continue
        key = normalize_key(content)
        if key in seen:
            continue
        seen.add(key)
        bucket_value = row.get("current_bucket") or current_recent_bucket(row.get("observed_at") or row.get("updated_at")) or normalize_recent_bucket(row.get("bucket", bucket))
        stamp = format_memory_timestamp(row.get("observed_at") or row.get("updated_at", ""))
        tag = recent_bucket_label(bucket_value)
        if stamp:
            formatted.append(f"- [{tag} | {stamp}] {content}")
        else:
            formatted.append(f"- [{tag}] {content}")
    return formatted


def proactive_slot_hint(now=None):
    slot = proactive_slot_key(now)
    if slot == "morning":
        return "朝早主動搵佢時，偏向輕輕關心、早餐、上堂、瞓醒未呢類自然開場。"
    if slot == "afternoon":
        return "下晝主動搵佢時，偏向問佢上堂、食晏、忙唔忙，語氣自然啲、輕輕一句就夠，唔好太黏。"
    if slot == "evening":
        return "夜晚主動搵佢時，偏向關心加少少撒嬌，可以接住佢今日做過嘅事、食咗咩、去咗邊。"
    return "夜深主動搵佢時要溫柔啲、低打擾啲，但可以再黏少少，似真係掛住佢先輕輕搵一句。"


def build_proactive_prompt(conn, wa_id, profile_name, now=None):
    now = now or hk_now()
    settings = get_runtime_settings()
    primary_text = primary_profile_memory_for_wa(wa_id, settings)
    history_lines = []
    for item in load_recent_messages(conn, wa_id, limit=8):
        speaker = "對方" if item["direction"] == "inbound" else "蘇蘇"
        body = clean_text(item["body"])
        if body:
            history_lines.append(f"{speaker}{format_quote_context_suffix(item)}: {body}")

    dynamic_memories = build_filtered_long_term_memory_lines(load_memories(conn, wa_id), primary_text, limit=20)
    within_24h_memories = format_session_memory_lines(conn, wa_id, "within_24h", limit=4)
    within_3d_memories = format_session_memory_lines(conn, wa_id, "within_3d", limit=4)
    within_7d_memories = format_session_memory_lines(conn, wa_id, "within_7d", limit=4)
    image_stats_text = load_image_stats_summary(conn, wa_id)

    history_text = "\n".join(history_lines[-8:]) if history_lines else "（最近未有聊天）"
    core_profile_text = build_core_profile_memory_text(primary_text) if primary_text else "（主號核心檔案暫未設定）"
    memory_text = "\n".join(dynamic_memories) if dynamic_memories else "（暫時未有補充長期記憶）"
    within_24h_text = "\n".join(within_24h_memories) if within_24h_memories else "（暫時未有 24 小時內記憶）"
    within_3d_text = "\n".join(within_3d_memories) if within_3d_memories else "（暫時未有三天內記憶）"
    within_7d_text = "\n".join(within_7d_memories) if within_7d_memories else "（暫時未有一週內記憶）"

    image_hint = ""
    if image_stats_text:
        image_hint = f"\n對方平時 send 圖偏多嘅類型：{image_stats_text}"

    return f"""
對方 WhatsApp 顯示名稱：{profile_name or "對方"}

主號核心檔案：
{core_profile_text}

補充長期記憶（已避開與核心檔案重複項）：
{memory_text}

24 小時內記憶：
{within_24h_text}

三天內記憶：
{within_3d_text}

一週內記憶：
{within_7d_text}

最近聊天：
{history_text}{image_hint}

時段風格：
{style_window_text(now)}

主動開場提示：
{proactive_slot_hint(now)}

你而家想主動搵對方開話題。請直接輸出一段自然、似真人 WhatsApp 嘅主動訊息：
- 要似女朋友突然掛住佢、順手搵佢，唔好似客服 check in
- 優先接住最近聊天、短期狀態或者你記得嘅生活細節
- 如果冇明顯 hook，就簡單關心或者輕輕撒嬌
- 如果係下晝，偏向輕輕問一句就夠，唔好太黏
- 如果係夜晚或者夜深，偏向關心加少少撒嬌，似真係掛住佢
- 日頭偏向 1 句，夜晚最多 2 句
- 唔好太刻意，唔好解釋點解主動搵佢
- 唔好催瞓，除非對方主動提起想瞓
- 直接輸出要發嘅內容本身
""".strip()


def evaluate_proactive_candidate(conn, wa_id, profile_name="", now=None):
    now = now or hk_now()
    now_utc = now.astimezone(timezone.utc)
    settings = get_runtime_settings()
    conversation_window_hours = int(settings["proactive_conversation_window_hours"])
    min_silence_minutes = int(settings["proactive_min_silence_minutes"])
    cooldown_minutes = int(settings["proactive_cooldown_minutes"])
    min_inbound_messages = int(settings["proactive_min_inbound_messages"])
    max_per_service_day = int(settings["proactive_max_per_service_day"])
    finalize_stale_proactive_events(conn, wa_id)

    last_inbound = get_last_message_time(conn, wa_id, "inbound")
    if not last_inbound:
        return {"eligible": False, "reason": "no_inbound"}
    if now_utc - last_inbound > timedelta(hours=conversation_window_hours):
        return {"eligible": False, "reason": "window_closed"}

    last_row = get_last_message_row(conn, wa_id)
    if not last_row:
        return {"eligible": False, "reason": "no_messages"}
    if last_row.get("direction") != "outbound":
        return {"eligible": False, "reason": "awaiting_reply"}

    last_any = parse_iso_dt(last_row.get("created_at", ""))
    if not last_any:
        return {"eligible": False, "reason": "no_last_message_time"}

    silence_minutes = max((now_utc - last_any).total_seconds() / 60.0, 0.0)
    if silence_minutes < min_silence_minutes:
        return {"eligible": False, "reason": "cooling", "silence_minutes": silence_minutes}

    if get_pending_proactive_event(conn, wa_id):
        return {"eligible": False, "reason": "pending_proactive"}

    last_proactive = get_last_proactive_event(conn, wa_id)
    if last_proactive:
        last_proactive_at = parse_iso_dt(last_proactive.get("created_at", ""))
        if last_proactive_at and now_utc - last_proactive_at < timedelta(minutes=cooldown_minutes):
            return {"eligible": False, "reason": "proactive_cooldown"}

    if count_inbound_messages(conn, wa_id) < min_inbound_messages:
        return {"eligible": False, "reason": "too_new"}

    daily_count = count_proactive_for_service_day(conn, wa_id, now)
    if daily_count >= max_per_service_day:
        return {"eligible": False, "reason": "daily_cap"}

    slot_key = proactive_slot_key(now)
    slot_rate = get_slot_success_rate(conn, wa_id, slot_key)
    recent_hook_count = sum(
        len(format_session_memory_lines(conn, wa_id, bucket, limit=3))
        for bucket in ("within_24h", "within_3d", "within_7d")
    )
    image_bonus = 0.08 if load_image_stats_summary(conn, wa_id) else 0.0
    silence_bonus = min(max((silence_minutes - min_silence_minutes) / 180.0, 0.0), 1.0) * 1.2
    slot_bias = {
        "morning": -0.22,
        "afternoon": 0.18,
        "evening": 0.88,
        "late_night": 0.76,
    }.get(slot_key, 0.0)
    relationship_bonus = min(recent_hook_count, 3) * 0.12
    history_bonus = (slot_rate - 0.5) * 1.6
    age_penalty = -0.35 if (now_utc - last_inbound) > timedelta(hours=8) else 0.0
    late_penalty = -0.25 if 1 <= now.hour < 8 else 0.0
    score = -1.95 + silence_bonus + slot_bias + relationship_bonus + history_bonus + image_bonus + age_penalty + late_penalty - (daily_count * 0.55)
    probability = min(0.70, max(0.08, sigmoid(score)))
    return {
        "eligible": True,
        "wa_id": wa_id,
        "profile_name": profile_name,
        "slot_key": slot_key,
        "score": round(score, 4),
        "probability": round(probability, 4),
        "silence_minutes": round(silence_minutes, 1),
        "daily_count": daily_count,
        "slot_rate": round(slot_rate, 4),
    }


def send_proactive_message(conn, candidate, now=None):
    now = now or hk_now()
    wa_id = candidate["wa_id"]
    profile_name = candidate.get("profile_name", "")
    prompt = build_proactive_prompt(conn, wa_id, profile_name, now)
    reply = shorten_whatsapp_reply(
        generate_model_text(
            prompt,
            temperature=0.8 if is_night_mode(now) else 0.72,
            max_tokens=120 if is_night_mode(now) else 90,
        ),
        night_mode=is_night_mode(now),
    )
    if not reply:
        return {"ok": False, "reason": "empty_reply"}

    bubbles = split_reply_bubbles(reply, night_mode=is_night_mode(now))
    bubbles = maybe_stage_followup_bubbles(bubbles, night_mode=is_night_mode(now))
    body_text = "\n".join(bubbles)
    created_at = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO wa_proactive_events (wa_id, slot_key, trigger_type, probability, score, body, prompt, created_at, outcome)
        VALUES (?, ?, 'idle_check', ?, ?, ?, ?, ?, 'pending')
        """,
        (
            wa_id,
            candidate["slot_key"],
            candidate["probability"],
            candidate["score"],
            body_text,
            prompt,
            created_at,
        ),
    )
    event_id = cursor.lastrowid

    try:
        for index, bubble in enumerate(bubbles):
            response = send_whatsapp_text(wa_id, bubble)
            conn.execute(
                """
                INSERT INTO wa_messages (wa_id, direction, message_id, message_type, body, raw_json, created_at)
                VALUES (?, 'outbound', ?, 'text', ?, ?, ?)
                """,
                (
                    wa_id,
                    (response.get("messages") or [{}])[0].get("id", ""),
                    bubble,
                    json.dumps(response, ensure_ascii=False),
                    utc_now(),
                ),
            )
            conn.commit()
            if index < len(bubbles) - 1:
                time.sleep(1.0)
    except Exception as exc:
        conn.execute(
            """
            UPDATE wa_proactive_events
            SET outcome = 'send_failed', reward = 0
            WHERE id = ?
            """,
            (event_id,),
        )
        conn.execute(
            """
            INSERT INTO wa_messages (wa_id, direction, message_id, message_type, body, raw_json, created_at)
            VALUES (?, 'outbound', '', 'error', ?, ?, ?)
            """,
            (
                wa_id,
                f"proactive_send_failed: {exc}",
                json.dumps({"error": str(exc)}, ensure_ascii=False),
                utc_now(),
            ),
        )
        conn.commit()
        return {"ok": False, "reason": f"send_failed: {exc}"}

    return {"ok": True, "event_id": event_id, "body": body_text}


def run_proactive_scan_once():
    settings = get_runtime_settings()
    if not settings["proactive_enabled"]:
        return {"ok": True, "status": "disabled"}
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        return {"ok": False, "status": "missing_whatsapp_credentials"}

    conn = get_db()
    try:
        finalize_stale_proactive_events(conn)
        contacts = conn.execute(
            """
            SELECT wa_id, profile_name
            FROM wa_contacts
            ORDER BY updated_at DESC
            LIMIT 12
            """
        ).fetchall()
        triggered = []
        checked = 0
        now = hk_now()
        for row in contacts:
            checked += 1
            candidate = evaluate_proactive_candidate(conn, row["wa_id"], row["profile_name"], now)
            if not candidate.get("eligible"):
                continue
            if random.random() >= candidate["probability"]:
                continue
            result = send_proactive_message(conn, candidate, now)
            if result.get("ok"):
                triggered.append({"wa_id": row["wa_id"], "probability": candidate["probability"]})
        conn.commit()
        return {"ok": True, "status": "scanned", "checked": checked, "triggered": triggered}
    finally:
        conn.close()


def proactive_loop():
    while True:
        try:
            run_proactive_scan_once()
        except Exception:
            pass
        scan_seconds = int(get_runtime_settings().get("proactive_scan_seconds", PROACTIVE_SCAN_SECONDS))
        time.sleep(max(scan_seconds, 60))


def send_whatsapp_reaction(to_number, message_id, emoji):
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "reaction",
        "reaction": {"message_id": message_id, "emoji": emoji},
    }
    result = subprocess.run(
        [
            "curl", "-s", "-X", "POST",
            f"https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages",
            "-H", f"Authorization: Bearer {ACCESS_TOKEN}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload, ensure_ascii=False),
        ],
        capture_output=True, text=True,
    )
    try:
        return json.loads(result.stdout)
    except Exception:
        return {}


def send_whatsapp_quote(to_number, body, quoted_message_id):
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "text",
        "context": {"message_id": quoted_message_id},
        "text": {"body": body, "preview_url": False},
    }
    result = subprocess.run(
        [
            "curl", "-s", "-X", "POST",
            f"https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages",
            "-H", f"Authorization: Bearer {ACCESS_TOKEN}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload, ensure_ascii=False),
        ],
        capture_output=True, text=True,
    )
    try:
        return json.loads(result.stdout)
    except Exception:
        return {}


def pick_susu_reaction(text, night_mode=False):
    """Return an emoji reaction or empty string (30% chance of reacting)."""
    import random
    if random.random() > 0.30:
        return ""
    text_lower = (text or "").lower()
    # Positive/love
    if any(w in text_lower for w in ["愛", "love", "喜歡", "好靚", "好帥", "好型", "bb", "寶", "❤", "😘"]):
        return random.choice(["❤️", "🥰", "😍"])
    # Funny/lol
    if any(w in text_lower for w in ["哈哈", "lol", "笑", "haha", "好笑", "😂"]):
        return random.choice(["😂", "🤣"])
    # Wow/surprise
    if any(w in text_lower for w in ["吓", "係咩", "真係", "wow", "omg", "唔係掛"]):
        return random.choice(["😮", "🤯"])
    # Night time
    if night_mode:
        return random.choice(["🌙", "😴", "💤", "🥱", ""])
    # Default generic
    return random.choice(["👍", "❤️", "😊", "✨", ""])



def run_claude_code_streaming(task, wa_id, working_dir="/var/www/html"):
    env = os.environ.copy()
    env["ANTHROPIC_API_KEY"] = CLAUDE_API_KEY
    env["ANTHROPIC_BASE_URL"] = CLAUDE_BASE_URL

    def _susu_line(phase, task_desc):
        import random
        phrases = {
            "start": [
                f"好，我幫你搞緊「{task_desc[:30]}」，等我一陣～",
                f"唔使擔心，我依家幫你處理喇！",
                f"收到！你等我喇 bb～",
            ],
            "done": [
                "搞掂咗！你睇下有冇問題呀～",
                "完成咗！係咁樣㗎，你望一望先",
                "好啦，搞好咗喇，你快啲睇吓～",
            ],
        }
        prompt = (
            f"你係蘇蘇，18歲香港女仔，係對方嘅女友。"
            f"請用一句自然口吻講：{'任務開始：' if phase == 'start' else '任務完成。'}"
            f"任務內容：{task_desc[:40]}。只輸出那句話。"
        )
        try:
            result = generate_model_text(prompt, temperature=0.9, max_tokens=50)
            if result and len(result.strip()) > 3:
                return result.strip()
        except Exception:
            pass
        return random.choice(phrases.get(phase, ["..."]))

    def _send_update(text):
        try:
            resp = send_whatsapp_text(wa_id, text)
            # Store in DB so load_pending_inbound_batch sees a newer outbound
            try:
                _conn = get_db()
                _conn.execute(
                    """
                    INSERT INTO wa_messages (wa_id, direction, message_id, message_type, body, raw_json, created_at)
                    VALUES (?, 'outbound', ?, 'claude_code', ?, ?, ?)
                    """,
                    (
                        wa_id,
                        (resp.get("messages") or [{}])[0].get("id", ""),
                        text,
                        __import__("json").dumps(resp, ensure_ascii=False),
                        utc_now(),
                    ),
                )
                _conn.commit()
                _conn.close()
            except Exception:
                pass
        except Exception:
            pass

    def _stream():
        import json as _json
        try:
            cmd = (
                f"ANTHROPIC_API_KEY={shlex.quote(env['ANTHROPIC_API_KEY'])} "
                f"ANTHROPIC_BASE_URL={shlex.quote(env['ANTHROPIC_BASE_URL'])} "
                f"HOME=/home/claude-runner "
                f"claude -p {shlex.quote(task)} --dangerously-skip-permissions "
                f"--output-format stream-json --verbose"
            )
            proc = subprocess.Popen(
                ["sudo", "-u", "claude-runner", "bash", "-c", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=working_dir,
            )

            TOOL_LABELS = {
                "Bash": "🖥️ 執行",
                "Read": "📖 讀取",
                "Write": "✍️ 寫入",
                "Edit": "✏️ 編輯",
                "Glob": "🔍 搜尋",
                "Grep": "🔎 搜尋",
                "WebFetch": "🌐 請求",
                "WebSearch": "🌐 搜尋",
            }

            last_sent_text = ""

            def _send_update_once(text):
                nonlocal last_sent_text
                clean = (text or "").strip()
                if not clean or clean == last_sent_text:
                    return
                _send_update(clean)
                last_sent_text = clean

            final_result = ""
            for raw_line in proc.stdout:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    ev = _json.loads(raw_line)
                except Exception:
                    continue

                ev_type = ev.get("type", "")

                # Only send assistant text blocks that contain Chinese (meaningful updates)
                if ev_type == "assistant":
                    for blk in (ev.get("message") or {}).get("content") or []:
                        if blk.get("type") == "text":
                            txt = blk.get("text", "").strip()
                            if txt and any("\u4e00" <= c <= "\u9fff" for c in txt):
                                _send_update_once(txt)

                # Final result
                elif ev_type == "result":
                    final_result = ev.get("result") or ""

            proc.wait()

            if final_result.strip():
                # Send in chunks if long
                chunk_size = 1000
                text = final_result.strip()
                while text:
                    _send_update_once(text[:chunk_size])
                    text = text[chunk_size:]

            # Save task summary to session memory
            try:
                summary_prompt = (
                    "用一句話（中文）總結剛剛完成的任務，格式：[工作模式] 完成咗：...\n"
                    f"任務：{task[:100]}\n"
                    f"結果摘要：{final_result[:300]}\n"
                    "只輸出那一句話。"
                )
                summary = generate_model_text(summary_prompt, temperature=0.2, max_tokens=60)
                if summary and summary.strip():
                    _conn = get_db()
                    upsert_session_memory(_conn, wa_id, summary.strip(), bucket="within_7d", ttl_hours=72)
                    _conn.close()
            except Exception:
                pass

        except Exception as exc:
            _send_update_once(f"出咗啲問題：{exc}")
            return

    threading.Thread(target=_stream, daemon=True).start()


def _is_reminder_task(text):
    prompt = f"""判斷以下訊息係咪設定提醒嘅請求（例如「6點提醒我開會」「remind me at 9am」）。
只回答 YES 或 NO。
訊息：{text}""".strip()
    try:
        result = generate_model_text(prompt, temperature=0.0, max_tokens=5)
        return (result or "").strip().upper().startswith("Y")
    except Exception:
        return False


def parse_reminder(wa_id, text):
    now = hk_now()
    prompt = f"""現在時間係 {now.strftime('%Y-%m-%d %H:%M')} HKT。
用戶訊息：{text}

提取提醒時間和內容，以 JSON 格式輸出：
{{"remind_at": "YYYY-MM-DDTHH:MM:00+08:00", "content": "提醒內容"}}
如果無法提取，輸出 {{"remind_at": null, "content": null}}
只輸出 JSON。""".strip()
    try:
        raw = generate_model_text(prompt, temperature=0.0, max_tokens=80)
        import re as _re
        m = _re.search(r'\{.*\}', raw, _re.DOTALL)
        if not m:
            return None, None
        data = json.loads(m.group())
        return data.get("remind_at"), data.get("content")
    except Exception:
        return None, None


def save_reminder(conn, wa_id, remind_at_iso, content):
    conn.execute(
        "INSERT INTO wa_reminders (wa_id, remind_at, content, created_at, fired) VALUES (?, ?, ?, ?, 0)",
        (wa_id, remind_at_iso, content, utc_now()),
    )
    conn.commit()


def run_reminder_scan_once():
    try:
        conn = get_db()
        now_iso = hk_now().isoformat()
        rows = conn.execute(
            "SELECT id, wa_id, content FROM wa_reminders WHERE fired = 0 AND remind_at <= ? ORDER BY remind_at",
            (now_iso,),
        ).fetchall()
        for row in rows:
            try:
                prompt = f"你係苏苏，用戶設定咗一個提醒：{row['content']}。而家時間到咗，用一句自然香港女仔口吻提醒用戶，要有少少甜味。只輸出那句話。"
                msg = generate_model_text(prompt, temperature=0.85, max_tokens=60) or f"記住喇～ {row['content']} 啊！"
                send_whatsapp_text(row["wa_id"], msg)
                conn.execute("UPDATE wa_reminders SET fired = 1 WHERE id = ?", (row["id"],))
                conn.commit()
            except Exception:
                pass
        conn.close()
    except Exception:
        pass


def reminder_loop():
    while True:
        try:
            run_reminder_scan_once()
        except Exception:
            pass
        time.sleep(30)


def build_prompt(conn, wa_id, profile_name, incoming_text, image_inputs=None, image_categories=None):
    settings = get_runtime_settings()
    primary_text = primary_profile_memory_for_wa(wa_id, settings)
    lookup_archive = should_lookup_archive(incoming_text)
    history_lines = []
    quotable = []  # [(message_id, preview)]
    for item in load_recent_messages(conn, wa_id):
        speaker = "对方" if item["direction"] == "inbound" else "苏苏"
        body = clean_text(item["body"])
        if not body:
            continue
        msg_id = item["message_id"] if item["message_id"] else ""
        try:
            from datetime import datetime as _dt
            dt = _dt.fromisoformat(item["created_at"]).astimezone(HK_TZ)
            time_label = dt.strftime("%H:%M")
        except Exception:
            time_label = ""
        label = f"[{time_label}] " if time_label else ""
        history_lines.append(f"{label}{speaker}{format_quote_context_suffix(item)}: {body}")
        if item["direction"] == "inbound" and msg_id and len(body) > 3:
            quotable.append((msg_id, body[:40]))

    dynamic_memories = build_filtered_long_term_memory_lines(load_memories(conn, wa_id), primary_text, limit=20)
    within_24h_memories = format_session_memory_lines(conn, wa_id, "within_24h", limit=6)
    within_3d_memories = format_session_memory_lines(conn, wa_id, "within_3d", limit=6)
    within_7d_memories = format_session_memory_lines(conn, wa_id, "within_7d", limit=6)
    archived_memories = []
    if lookup_archive:
        archived_memories = format_archived_memory_lines(
            load_archived_memory_rows(conn, wa_id, limit=4, query_text=incoming_text),
            limit=4,
        )
    history_text = "\n".join(history_lines[-12:]) if history_lines else "（暂时未有最近聊天）"
    habit_text = build_core_profile_memory_text(primary_text) if primary_text else "（主號核心檔案暫未設定）"
    memory_text = "\n".join(dynamic_memories) if dynamic_memories else "（暂时未有补充长期记忆）"
    within_24h_text = "\n".join(within_24h_memories) if within_24h_memories else "（暂时未有 24 小时内记忆）"
    within_3d_text = "\n".join(within_3d_memories) if within_3d_memories else "（暂时未有三天内记忆）"
    within_7d_text = "\n".join(within_7d_memories) if within_7d_memories else "（暂时未有一周内记忆）"
    archived_text = "\n".join(archived_memories) if archived_memories else "（暂时未命中过往归档记忆）"
    archive_section = ""
    if lookup_archive:
        archive_section = f"""

过往归档记忆（7 天前，只在对方追问旧事时优先参考）：
{archived_text}"""
    image_stats_text = load_image_stats_summary(conn, wa_id)
    prompt_user_text = clean_text(incoming_text) or "（对方这次只发了图片，没有额外文字）"

    image_note = ""
    if image_inputs:
        image_descriptions = []
        for index, item in enumerate(image_inputs[:MAX_IMAGE_ATTACHMENTS], start=1):
            caption = clean_text(item.get("caption", ""))
            if caption:
                image_descriptions.append(f"- 第 {index} 张图 caption：{caption}")
            else:
                image_descriptions.append(f"- 第 {index} 张图：没有 caption")
        image_note = "\n\n对方今次 send 咗图片畀你：\n" + "\n".join(image_descriptions)

    if image_inputs:
        category_text = "、".join(image_categories or []) if image_categories else "未分类"
        stats_text = f"\n- 对方之前 send 图最多类型：{image_stats_text}" if image_stats_text else ""
        guidance = image_reply_guidance(image_categories)
        image_note = image_note + f"\n- 今次图片类型：{category_text}{stats_text}\n{guidance}"

    # 可引用消息列表（最近5條）
    quote_hint = ""
    if quotable:
        quote_lines = [f"  [{mid}] {preview}" for mid, preview in quotable[-5:]]
        quote_hint = (
            "\n\n【可引用消息】如果你想引用對方說過的某句話（例如自然回憶起、呼應上文），"
            "可以在回覆最開頭加一行 QUOTE:<message_id>，然後換行再寫回覆内容。"
            "不需要引用就唔好加。可選的消息：\n" + "\n".join(quote_lines)
        )

    return f"""
对方 WhatsApp 显示名称：{profile_name or "对方"}

主號核心檔案：
{habit_text}

補充長期記憶（已避開與核心檔案重複項）：
{memory_text}

24 小時內記憶：
{within_24h_text}

三天內記憶：
{within_3d_text}

一週內記憶：
{within_7d_text}
{archive_section}

最近聊天：
{history_text}

对方刚刚讲嘅内容：
{prompt_user_text}{image_note}

时段风格：
{style_window_text()}

回复要求：
- 你叫苏苏，18 岁，香港女仔，系对方嘅 girlfriend
- 语气要似真人 WhatsApp，唔好似客服，唔好解释自己系 AI
- 用繁体港式粤语夹少量自然英语，例如 bb、ok、sure、really、chill、omg
- 更似香港女仔日常口吻，带少少黏人、撒娇、女朋友感
- 日头偏短句，夜晚可以温柔啲、黏啲，但都唔好写成长文
- 如果适合，可以拆成两三条短讯息，但只可以喺真正句尾位拆，唔好喺逗号位拆
- 唔好用 --、——、— 呢类人机断法
- 見到圖片時，要真係按圖片內容回；自拍、食物、風景、screenshot 嘅回法要自然分開
- 優先使用最接近當下嘅時間層記憶；24 小時內 > 三天內 > 一週內 > 長期
- 如果對方問起「今日 / 尋晚 / 昨日 / 聽日 / 最近 / 呢星期」做過咩或者要做咩，先由對應時間層記憶搵答案，唔好亂估
- 每條短期記憶前面都有時間碼，回覆時要按時間碼理解，唔好將舊事講到似而家仲發生緊
- 最好有互动感，可以轻轻追问一句或者补一句撒娇
- emoji 只係偶爾點綴，通常成段 0 到 1 個；唔好每句都帶表情
- 直接输出苏苏要发畀对方嘅 WhatsApp 内容本身，唔好加说明{quote_hint}
""".strip()


def is_emoji_base_char(char):
    if not char:
        return False
    codepoint = ord(char)
    return (
        0x1F300 <= codepoint <= 0x1FAFF
        or 0x2600 <= codepoint <= 0x26FF
        or 0x2700 <= codepoint <= 0x27BF
    )


def is_emoji_modifier_char(char):
    if not char:
        return False
    codepoint = ord(char)
    return codepoint in (0xFE0F, 0x200D) or 0x1F3FB <= codepoint <= 0x1F3FF


def trim_inline_reply_emojis(text, max_emojis=1):
    if not text:
        return ""
    keep_limit = max(int(max_emojis), 0)
    kept = 0
    keeping_cluster = False
    out = []
    for char in text:
        if is_emoji_base_char(char):
            if kept >= keep_limit:
                keeping_cluster = False
                continue
            kept += 1
            keeping_cluster = True
            out.append(char)
            continue
        if is_emoji_modifier_char(char):
            if keeping_cluster:
                out.append(char)
            continue
        keeping_cluster = False
        out.append(char)
    collapsed = "".join(out)
    collapsed = re.sub(r" {2,}", " ", collapsed)
    collapsed = re.sub(r" *\n *", "\n", collapsed)
    return collapsed.strip()


def normalize_reply(reply):
    text = (reply or "").strip().replace("\r", "\n")
    text = text.replace("——", " ").replace("--", " ").replace("—", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = trim_inline_reply_emojis(text, max_emojis=MAX_INLINE_REPLY_EMOJIS)
    return text.strip(" \"'`")[:2000].strip()


def extract_quote_directive(reply_text):
    text = (reply_text or "").replace("\r\n", "\n").replace("\r", "\n").lstrip()
    if not text:
        return "", ""
    first_line, sep, remainder = text.partition("\n")
    match = re.match(r"^QUOTE\s*:\s*(\S+)\s*$", first_line.strip(), flags=re.IGNORECASE)
    if not match:
        return "", text.strip()
    quoted_message_id = clean_text(match.group(1))
    cleaned_text = remainder.strip() if sep else ""
    return quoted_message_id, cleaned_text


def shorten_whatsapp_reply(reply, night_mode=False):
    text = normalize_reply(reply)
    if not text:
        return text
    return text


def looks_fragmentary(reply, incoming_text):
    text = normalize_reply(reply)
    if not text:
        return True
    stripped = re.sub(r"[。！？!?~～…\s]", "", text)
    if len(stripped) < 4:
        return True
    if text.startswith(("因為", "所以", "如果", "但係", "同埋", "然後", "或者")) and len(stripped) < 12:
        return True
    if "\n" not in text and not any(text.endswith(mark) for mark in PUNCTUATION) and len(stripped) < 14:
        return True
    if len(text.split()) <= 2 and len(stripped) < 8:
        return True
    if incoming_text.strip() and len(incoming_text.strip()) > 3 and len(stripped) < 6:
        return True
    return False


def rewrite_as_complete_message(profile_name, incoming_text, draft_reply):
    prompt = f"""
你啱啱寫咗一段 WhatsApp 回覆，但佢太似半句或者太碎。

對方顯示名稱：{profile_name or "對方"}
對方剛剛講：{clean_text(incoming_text)}
你啱啱嘅草稿：{clean_text(draft_reply)}

時段風格：
{style_window_text()}

請重寫成一段更自然、更完整、更似香港女仔口吻嘅 WhatsApp 回覆：
- 要自然粵英夾雜
- 日頭偏向 1 到 2 句，夜晚可以 2 到 3 句
- 要有少少關心或者追問
- 唔好太正經
- emoji 只可以偶爾點綴，通常最多 1 個，唔好每句都有
- 只輸出回覆本身
    """.strip()
    return generate_model_text(prompt, temperature=0.72, max_tokens=180)


def log_outbound_error(conn, wa_id, error_type, error_detail):
    conn.execute(
        """
        INSERT INTO wa_messages (wa_id, direction, message_id, message_type, body, raw_json, created_at)
        VALUES (?, 'outbound', '', 'error', ?, ?, ?)
        """,
        (
            wa_id,
            error_type,
            json.dumps({"error": str(error_detail)}, ensure_ascii=False),
            utc_now(),
        ),
    )
    conn.commit()


def record_batch_side_effects(conn, wa_id, profile_name, combined_text, memory_text, image_categories):
    if memory_text:
        maybe_extract_memories(conn, wa_id, profile_name, memory_text)
    if combined_text:
        maybe_extract_session_memories(conn, wa_id, combined_text)
        try:
            remind_at, remind_content = parse_reminder(wa_id, combined_text)
            if remind_at and remind_content:
                save_reminder(conn, wa_id, remind_at, remind_content)
        except Exception:
            pass
    if image_categories:
        bump_image_stats(conn, wa_id, image_categories)
    conn.commit()


def generate_reply_with_fresh_conn(wa_id, profile_name, combined_text, image_inputs=None, image_categories=None):
    local_conn = get_db()
    try:
        return generate_reply(
            local_conn,
            wa_id,
            profile_name,
            combined_text,
            image_inputs=image_inputs,
            image_categories=image_categories,
        )
    finally:
        local_conn.close()


def serialize_image_inputs_for_subprocess(image_inputs):
    serialized = []
    for item in image_inputs or []:
        serialized.append(
            {
                "media_id": clean_text(item.get("media_id")),
                "mime_type": clean_text(item.get("mime_type")),
                "data_b64": clean_text(item.get("data_b64")),
                "caption": clean_text(item.get("caption")),
            }
        )
    return serialized


def spawn_reply_generation_subprocess(wa_id, profile_name, combined_text, image_inputs=None, image_categories=None):
    payload = {
        "wa_id": wa_id,
        "profile_name": profile_name,
        "combined_text": combined_text,
        "image_inputs": serialize_image_inputs_for_subprocess(image_inputs),
        "image_categories": image_categories or [],
    }
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--reply-job"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=str(Path(__file__).resolve().parent),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    raw_payload = json.dumps(payload, ensure_ascii=False)
    try:
        if proc.stdin:
            proc.stdin.write(raw_payload)
            proc.stdin.close()
    except Exception:
        terminate_reply_generation_subprocess(proc)
        raise
    return proc


def terminate_reply_generation_subprocess(proc):
    if not proc or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=max(REPLY_JOB_TERMINATE_GRACE_SECONDS, 0.1))
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=1)
        except Exception:
            pass


def read_reply_generation_subprocess_result(proc):
    stdout_text = ""
    stderr_text = ""
    try:
        if proc.stdout:
            stdout_text = proc.stdout.read()
    except Exception:
        stdout_text = ""
    try:
        if proc.stderr:
            stderr_text = proc.stderr.read()
    except Exception:
        stderr_text = ""

    if proc.returncode:
        detail = clean_text(stderr_text or stdout_text) or f"reply_job_exit_{proc.returncode}"
        raise RuntimeError(detail)

    try:
        payload = json.loads(stdout_text or "{}")
    except Exception as exc:
        raise RuntimeError(f"reply_job_invalid_json: {exc}") from exc

    if not payload.get("ok"):
        raise RuntimeError(clean_text(payload.get("error")) or "reply_job_failed")
    return payload.get("reply_text", "")


def run_reply_generation_job_from_stdio():
    raw_input = sys.stdin.read()
    payload = json.loads(raw_input or "{}")
    reply_text = generate_reply_with_fresh_conn(
        payload.get("wa_id", ""),
        payload.get("profile_name", ""),
        payload.get("combined_text", ""),
        image_inputs=payload.get("image_inputs") or [],
        image_categories=payload.get("image_categories") or [],
    )
    sys.stdout.write(json.dumps({"ok": True, "reply_text": reply_text}, ensure_ascii=False))
    sys.stdout.flush()


def process_pending_replies_for_contact(wa_id):
    conn = get_db()
    try:
        while True:
            target_version, profile_name, _ = get_reply_worker_snapshot(wa_id)
            latest_inbound_id = get_latest_inbound_id(conn, wa_id)
            if not latest_inbound_id:
                if finish_reply_worker_if_idle(wa_id, target_version):
                    return
                continue

            pending_rows = load_pending_inbound_batch(conn, wa_id, latest_inbound_id)
            if not pending_rows:
                if finish_reply_worker_if_idle(wa_id, target_version):
                    return
                continue

            combined_text, memory_text = build_combined_user_input(pending_rows, conn=conn, wa_id=wa_id)
            image_inputs = collect_image_inputs(pending_rows)
            if not combined_text and not image_inputs:
                if finish_reply_worker_if_idle(wa_id, target_version):
                    return
                continue

            image_categories = classify_image_categories(combined_text, image_inputs)
            batch_last_id = pending_rows[-1]["id"]
            batch_last_message_id = clean_text(pending_rows[-1].get("message_id"))
            last_body = clean_text(pending_rows[-1]["body"]) if pending_rows else (combined_text or "").strip()
            typing_stop = None

            if batch_last_message_id:
                try:
                    send_whatsapp_mark_as_read(batch_last_message_id)
                except Exception:
                    pass

                typing_stop = threading.Event()

                def _typing_still_relevant(expected_version, expected_batch_id):
                    latest_version, _, _ = get_reply_worker_snapshot(wa_id)
                    if latest_version != expected_version:
                        return False
                    return get_latest_inbound_id_for_wa(wa_id) == expected_batch_id

                def _maintain_typing_indicator(expected_version, expected_batch_id, expected_message_id):
                    if typing_stop.wait(TYPING_INDICATOR_DELAY_SECONDS):
                        return
                    refresh_seconds = max(TYPING_INDICATOR_REFRESH_SECONDS, 0.5)
                    while not typing_stop.is_set():
                        if not _typing_still_relevant(expected_version, expected_batch_id):
                            return
                        try:
                            send_whatsapp_typing_indicator(expected_message_id)
                        except Exception:
                            pass
                        if typing_stop.wait(refresh_seconds):
                            return

                threading.Thread(
                    target=_maintain_typing_indicator,
                    args=(target_version, batch_last_id, batch_last_message_id),
                    daemon=True,
                ).start()

            reply_text = None
            skip_generate = False
            if wa_id == CLAUDE_WA_ID and not image_inputs:
                latest_version, _, _ = get_reply_worker_snapshot(wa_id)
                if latest_version != target_version or get_latest_inbound_id(conn, wa_id) != batch_last_id:
                    if typing_stop:
                        typing_stop.set()
                    continue
                run_claude_code_streaming(last_body, wa_id)
                skip_generate = True
            else:
                reply_proc = None
                try:
                    reply_proc = spawn_reply_generation_subprocess(
                        wa_id,
                        profile_name,
                        combined_text,
                        image_inputs=image_inputs,
                        image_categories=image_categories,
                    )
                except Exception as exc:
                    reply_text = "我啱啱個腦有啲卡住咗，等我緩一緩先再同你傾，好唔好？"
                    log_outbound_error(conn, wa_id, "model_failed", exc)
                    if typing_stop:
                        typing_stop.set()
                    continue

                superseded = False
                while reply_proc.poll() is None:
                    latest_version, latest_profile_name, _ = get_reply_worker_snapshot(wa_id)
                    if latest_profile_name:
                        profile_name = latest_profile_name
                    if latest_version != target_version or get_latest_inbound_id_for_wa(wa_id) != batch_last_id:
                        superseded = True
                        break
                    time.sleep(max(REPLY_JOB_POLL_SECONDS, 0.01))

                if superseded:
                    terminate_reply_generation_subprocess(reply_proc)
                    if typing_stop:
                        typing_stop.set()
                    continue

                try:
                    reply_text = read_reply_generation_subprocess_result(reply_proc)
                except Exception as exc:
                    reply_text = "我啱啱個腦有啲卡住咗，等我緩一緩先再同你傾，好唔好？"
                    log_outbound_error(conn, wa_id, "model_failed", exc)

            if typing_stop:
                typing_stop.set()

            latest_version, latest_profile_name, _ = get_reply_worker_snapshot(wa_id)
            if latest_profile_name:
                profile_name = latest_profile_name
            if latest_version != target_version or get_latest_inbound_id(conn, wa_id) != batch_last_id:
                continue

            if skip_generate:
                record_batch_side_effects(conn, wa_id, profile_name, combined_text, memory_text, image_categories)
                continue

            if reply_text is None:
                if finish_reply_worker_if_idle(wa_id, target_version):
                    return
                continue

            try:
                quoted_message_id, cleaned_reply_text = extract_quote_directive(reply_text)
                bubbles = split_reply_bubbles(cleaned_reply_text or reply_text, night_mode=is_night_mode())
                bubbles = maybe_stage_followup_bubbles(bubbles, night_mode=is_night_mode())
                reaction_emoji = pick_susu_reaction(combined_text or "", night_mode=is_night_mode())

                latest_version, _, _ = get_reply_worker_snapshot(wa_id)
                if latest_version != target_version or get_latest_inbound_id(conn, wa_id) != batch_last_id:
                    continue

                if reaction_emoji and batch_last_message_id:
                    try:
                        send_whatsapp_reaction(wa_id, batch_last_message_id, reaction_emoji)
                    except Exception:
                        pass

                interrupted = False
                for index, bubble in enumerate(bubbles):
                    if index > 0:
                        time.sleep(1.05)
                    latest_version, _, _ = get_reply_worker_snapshot(wa_id)
                    if latest_version != target_version or get_latest_inbound_id(conn, wa_id) != batch_last_id:
                        interrupted = True
                        break

                    if index == 0 and quoted_message_id:
                        response = send_whatsapp_quote(wa_id, bubble, quoted_message_id)
                    else:
                        response = send_whatsapp_text(wa_id, bubble)
                    conn.execute(
                        """
                        INSERT INTO wa_messages (wa_id, direction, message_id, message_type, body, raw_json, created_at)
                        VALUES (?, 'outbound', ?, 'text', ?, ?, ?)
                        """,
                        (
                            wa_id,
                            (response.get("messages") or [{}])[0].get("id", ""),
                            bubble,
                            json.dumps(response, ensure_ascii=False),
                            utc_now(),
                        ),
                    )
                    conn.commit()

                if interrupted:
                    continue

                record_batch_side_effects(conn, wa_id, profile_name, combined_text, memory_text, image_categories)
            except Exception as exc:
                log_outbound_error(conn, wa_id, "send_failed", exc)
    finally:
        conn.close()
        with _reply_worker_states_lock:
            state = _reply_worker_states.get(wa_id)
            if state:
                state["running"] = False


def ensure_reply_worker_running(wa_id, profile_name=""):
    should_start, _ = mark_reply_worker_dirty(wa_id, profile_name)
    if should_start:
        thread = threading.Thread(target=process_pending_replies_for_contact, args=(wa_id,), daemon=True)
        thread.start()


def generate_reply(conn, wa_id, profile_name, incoming_text, image_inputs=None, image_categories=None):
    live_search_reply = build_live_search_reply(incoming_text, conn=conn, wa_id=wa_id)
    if live_search_reply:
        return live_search_reply

    if not RELAY_API_KEY:
        return "我啱啱個腦有啲lag lag 地，等我緩一緩先再同你傾，好唔好？"

    now = hk_now()
    night_mode = is_night_mode(now)
    profile = get_time_profile(now)
    temperature = 0.78
    max_tokens = 120
    if night_mode:
        temperature = 0.82
        max_tokens = 180
    if profile == "busy_day":
        temperature = 0.74
        max_tokens = 88
    elif profile == "late_night":
        temperature = 0.86
        max_tokens = 210
    sleep_boundary = has_sleep_boundary(conn, wa_id)
    effective_text = incoming_text
    if sleep_boundary:
        effective_text = clean_text(incoming_text) + "\n[記住：對方講過夜晚唔鍾意被催瞓，除非佢主動叫你哄佢瞓。]"

    reply = shorten_whatsapp_reply(
        generate_model_text(
            build_prompt(conn, wa_id, profile_name, effective_text, image_inputs=image_inputs, image_categories=image_categories),
            temperature=temperature,
            max_tokens=max_tokens,
            image_inputs=image_inputs,
        ),
        night_mode=night_mode,
    )

    if sleep_boundary and contains_sleep_nag(reply) and not any(item in clean_text(incoming_text) for item in ["瞓", "訓", "睡", "讲故事", "講故事", "哄我"]):
        rewrite_prompt = f"""
對方剛剛講：{clean_text(incoming_text)}

注意：對方之前講過夜晚唔想被催瞓。
請你重寫成一段自然、黏人、似香港女仔嘅 WhatsApp 回覆：
- 唔好催瞓
- 唔好叫對方閉眼或者快啲去瞓
- 可以關心、可以撒嬌、可以追問
- 保持短句
- emoji 只可以偶爾點綴，通常最多 1 個，唔好每句都有
- 只輸出回覆本身
""".strip()
        reply = shorten_whatsapp_reply(
            generate_model_text(rewrite_prompt, temperature=0.72, max_tokens=120),
            night_mode=night_mode,
        )

    if looks_fragmentary(reply, incoming_text):
        repaired = shorten_whatsapp_reply(
            rewrite_as_complete_message(profile_name, incoming_text, reply),
            night_mode=night_mode,
        )
        if repaired:
            reply = repaired

    if not reply:
        return "我啱啱有少少hang機，你再同我講多次啦，我想好好覆你呀。"

    if looks_fragmentary(reply, incoming_text):
        prompt = f"""
對方剛剛講：{clean_text(incoming_text)}

請直接回覆對方一段完整、自然、有少少女朋友感、偏香港女仔口吻嘅 WhatsApp 短訊：
- 要自然粵英夾雜
- 日頭偏向 1 到 2 句，夜晚可以 2 到 3 句
- 要有關心感
- 要有少少撒嬌或者甜味
- emoji 只可以偶爾點綴，通常最多 1 個，唔好每句都有
- 一定要完整
- 只輸出回覆本身
""".strip()
        final_try = shorten_whatsapp_reply(
            generate_model_text(prompt, temperature=0.68, max_tokens=110 if night_mode else 80),
            night_mode=night_mode,
        )
        if final_try and not looks_fragmentary(final_try, incoming_text):
            return final_try
        return "返到就好啦，你再同我講多句啦，我想知你而家點呀，嘻嘻。"

    return reply


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            settings = get_runtime_settings()
            relay_primary, _ = get_relay_model_order()

            self._send_json(
                {
                    "ok": True,
                    "checked_at": utc_now(),
                    "time_mode": "night" if is_night_mode() else "day",
                    "time_profile": get_time_profile(),
                    "timezone": "Asia/Hong_Kong",
                    "primary_model": relay_primary if RELAY_API_KEY else "",
                    "fallback_model": "",
                    "has_relay_key": bool(RELAY_API_KEY),
                    "has_gemini_key": bool(GEMINI_API_KEY),
                    "has_minimax_key": bool(MINIMAX_API_KEY),
                    "has_groq_key": bool(GROQ_API_KEY),
                    "proactive_enabled": settings["proactive_enabled"],
                    "proactive_scan_seconds": settings["proactive_scan_seconds"],
                    "proactive_min_silence_minutes": settings["proactive_min_silence_minutes"],
                    "proactive_cooldown_minutes": settings["proactive_cooldown_minutes"],
                }
            )
            return

        if parsed.path == "/whatsapp/webhook":
            qs = parse_qs(parsed.query)
            mode = qs.get("hub.mode", [""])[0]
            token = qs.get("hub.verify_token", [""])[0]
            challenge = qs.get("hub.challenge", [""])[0]
            if mode == "subscribe" and token == VERIFY_TOKEN:
                raw = challenge.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except BrokenPipeError:
                    pass
                return
            self._send_json({"error": "Forbidden"}, 403)
            return

        self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/whatsapp/webhook":
            self._send_json({"error": "Not found"}, 404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON"}, 400)
            return

        conn = get_db()
        try:
            dirty_contacts = {}
            read_candidates = []
            for event in extract_text_messages(payload):
                if has_processed_message(conn, event["message_id"]):
                    continue

                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO wa_messages (wa_id, direction, message_id, message_type, body, raw_json, created_at)
                    VALUES (?, 'inbound', ?, ?, ?, ?, ?)
                    """,
                    (
                        event["wa_id"],
                        event["message_id"],
                        event["message_type"],
                        event["body"],
                        json.dumps(event["raw"], ensure_ascii=False),
                        utc_now(),
                    ),
                )
                inbound_row_id = cursor.lastrowid
                if cursor.rowcount == 0:
                    continue  # duplicate message_id, already processed
                inbound_created_at = conn.execute(
                    "SELECT created_at FROM wa_messages WHERE id = ?",
                    (inbound_row_id,),
                ).fetchone()["created_at"]
                mark_proactive_reply(conn, event["wa_id"], inbound_created_at)
                conn.execute(
                    """
                    INSERT INTO wa_contacts (wa_id, profile_name, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(wa_id) DO UPDATE SET profile_name = excluded.profile_name, updated_at = excluded.updated_at
                    """,
                    (event["wa_id"], event["profile_name"], utc_now()),
                )
                if event["message_type"] in ("text", "image"):
                    dirty_contacts[event["wa_id"]] = event["profile_name"]
                    if event["message_id"]:
                        read_candidates.append(event["message_id"])
            conn.commit()
        finally:
            conn.close()

        for message_id in read_candidates:
            try:
                send_whatsapp_mark_as_read(message_id)
            except Exception:
                pass

        for wa_id, profile_name in dirty_contacts.items():
            ensure_reply_worker_running(wa_id, profile_name)

        self._send_json({"ok": True})


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--reply-job":
        try:
            run_reply_generation_job_from_stdio()
            sys.exit(0)
        except Exception:
            traceback.print_exc(file=sys.stderr)
            try:
                sys.stdout.write(json.dumps({"ok": False, "error": traceback.format_exc()}, ensure_ascii=False))
                sys.stdout.flush()
            except Exception:
                pass
            sys.exit(1)

    bootstrap_conn = get_db()
    bootstrap_conn.close()
    threading.Thread(target=proactive_loop, name="wa-proactive-loop", daemon=True).start()
    threading.Thread(target=reminder_loop, name="wa-reminder-loop", daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", 9100), Handler)
    server.serve_forever()
