#!/usr/bin/env python3
import base64
import subprocess
import shlex
import json
import os
import random
import re
import sqlite3
import threading
import textwrap
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None


BASE_DIR = Path("/var/www/html")
DB_PATH = BASE_DIR / "wa_agent.db"

VERIFY_TOKEN = os.environ.get("WA_VERIFY_TOKEN", "")
ACCESS_TOKEN = os.environ.get("WA_ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("WA_PHONE_NUMBER_ID", "")
GRAPH_VERSION = os.environ.get("WA_GRAPH_VERSION", "v22.0")
INBOUND_GRACE_SECONDS = float(os.environ.get("WA_INBOUND_GRACE_SECONDS", "7"))
PROACTIVE_ENABLED = os.environ.get("WA_PROACTIVE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
PROACTIVE_SCAN_SECONDS = int(os.environ.get("WA_PROACTIVE_SCAN_SECONDS", "300"))
PROACTIVE_MIN_SILENCE_MINUTES = int(os.environ.get("WA_PROACTIVE_MIN_SILENCE_MINUTES", "45"))
PROACTIVE_COOLDOWN_MINUTES = int(os.environ.get("WA_PROACTIVE_COOLDOWN_MINUTES", "180"))
PROACTIVE_REPLY_WINDOW_MINUTES = int(os.environ.get("WA_PROACTIVE_REPLY_WINDOW_MINUTES", "90"))
PROACTIVE_CONVERSATION_WINDOW_HOURS = int(os.environ.get("WA_PROACTIVE_CONVERSATION_WINDOW_HOURS", "24"))
PROACTIVE_MAX_PER_SERVICE_DAY = int(os.environ.get("WA_PROACTIVE_MAX_PER_SERVICE_DAY", "2"))
PROACTIVE_MIN_INBOUND_MESSAGES = int(os.environ.get("WA_PROACTIVE_MIN_INBOUND_MESSAGES", "8"))

RELAY_API_KEY = os.environ.get("WA_RELAY_API_KEY", "")
RELAY_MODEL = os.environ.get("WA_RELAY_MODEL", "claude-opus-4-6")
RELAY_FALLBACK_MODEL = os.environ.get("WA_RELAY_FALLBACK_MODEL", "claude-sonnet-4-6")
RELAY_BASE_URL = os.environ.get("WA_RELAY_BASE_URL", "https://apiapipp.com/v1")

GEMINI_API_KEY = os.environ.get("WA_GEMINI_API_KEY") or os.environ.get("GOOGLE_KEY", "")
GEMINI_MODEL = os.environ.get("WA_GEMINI_MODEL", "gemini-2.5-flash")

MINIMAX_API_KEY = os.environ.get("WA_MINIMAX_API_KEY", "")
MINIMAX_MODEL = os.environ.get("WA_MINIMAX_MODEL", "MiniMax-M2.5")
MINIMAX_BASE_URL = os.environ.get("WA_MINIMAX_BASE_URL", "https://api.minimaxi.com/v1")

GROQ_API_KEY = os.environ.get("WA_GROQ_API_KEY") or os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("WA_GROQ_MODEL", "llama-3.3-70b-versatile")

ADMIN_WA_ID = os.environ.get("WA_ADMIN_WA_ID", "85259576670")
CLAUDE_WA_ID = os.environ.get("WA_CLAUDE_WA_ID", "8618704499898")
CLAUDE_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://apiapipp.com")

# 安全詞
MAX_IMAGE_ATTACHMENTS = int(os.environ.get("WA_MAX_IMAGE_ATTACHMENTS", "3"))
MAX_IMAGE_BYTES = int(os.environ.get("WA_MAX_IMAGE_BYTES", str(5 * 1024 * 1024)))

HK_TZ = ZoneInfo("Asia/Hong_Kong") if ZoneInfo else timezone(timedelta(hours=8))
PUNCTUATION = "。！？!?~～…"

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
    now = now or hk_now()
    if is_night_mode(now):
        primary = RELAY_FALLBACK_MODEL or RELAY_MODEL
        secondary = RELAY_MODEL if RELAY_MODEL != primary else ""
    else:
        primary = RELAY_MODEL
        secondary = RELAY_FALLBACK_MODEL if RELAY_FALLBACK_MODEL != primary else ""
    return primary, secondary


def clean_text(value):
    return re.sub(r"\s+", " ", (value or "").strip())


def normalize_key(value):
    value = clean_text(value).lower()
    value = re.sub(r"[^\w\u4e00-\u9fff]+", "", value)
    return value[:160]


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
        CREATE INDEX IF NOT EXISTS idx_wa_proactive_events_lookup
        ON wa_proactive_events (wa_id, outcome, created_at DESC)
        """
    )
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

    max_bubbles = 4 if night_mode else 3
    if len(text) < 26:
        return [text]

    chunks = [chunk.strip() for chunk in re.split(r"\n+", text) if chunk.strip()]
    if len(chunks) >= 2:
        return chunks[:max_bubbles]

    parts = re.findall(
        r".+?(?:[。！？!?…]+(?:[🥺😭😂😏🤭💕💖💗💘🫶✨😤🤍❤️💛💚💙💜🩷🩵]*\s*)|$)",
        text,
    )
    sentences = [part.strip() for part in parts if part.strip()]
    if len(sentences) <= 1:
        return [text]
    if len(sentences) <= max_bubbles:
        return sentences
    head = sentences[: max_bubbles - 1]
    tail = " ".join(sentences[max_bubbles - 1 :]).strip()
    return head + ([tail] if tail else [])


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


def load_recent_messages(conn, wa_id, limit=12):
    rows = conn.execute(
        """
        SELECT direction, message_id, body, created_at
        FROM wa_messages
        WHERE wa_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (wa_id, limit),
    ).fetchall()
    return list(reversed(rows))


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
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=PROACTIVE_REPLY_WINDOW_MINUTES)).isoformat()
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
    if delay > PROACTIVE_REPLY_WINDOW_MINUTES * 60:
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
        SELECT id, body, message_type, raw_json
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


def build_combined_user_input(rows):
    lines = []
    text_only_lines = []
    for row in rows:
        message_type = row.get("message_type", "")
        body = clean_text(row.get("body", ""))
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
        "system_instruction": {"parts": [{"text": system_prompt or SYSTEM_PERSONA}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": temperature,
            "topP": 0.9,
            "maxOutputTokens": max_tokens,
        },
    }
    request = Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}",
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
            {"role": "system", "content": system_prompt or SYSTEM_PERSONA},
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
    relay_primary, relay_secondary = get_relay_model_order()

    if RELAY_API_KEY and relay_primary:
        try:
            return call_relay_model(relay_primary, prompt_text, temperature=temperature, max_tokens=max_tokens, system_prompt=system_prompt, image_inputs=image_inputs)
        except HTTPError as exc:
            errors.append(f"relay_http_{exc.code}")
            if exc.code not in (401, 403, 429, 500, 502, 503, 504):
                raise
        except Exception as exc:
            errors.append(f"relay_failed:{type(exc).__name__}")

    if RELAY_API_KEY and relay_secondary:
        try:
            return call_relay_model(relay_secondary, prompt_text, temperature=temperature, max_tokens=max_tokens, system_prompt=system_prompt, image_inputs=image_inputs)
        except HTTPError as exc:
            errors.append(f"relay_fallback_http_{exc.code}")
            if exc.code not in (401, 403, 429, 500, 502, 503, 504):
                raise
        except Exception as exc:
            errors.append(f"relay_fallback_failed:{type(exc).__name__}")

    if GEMINI_API_KEY:
        try:
            return call_gemini(prompt_text, temperature=temperature, max_tokens=max_tokens, system_prompt=system_prompt, image_inputs=image_inputs)
        except HTTPError as exc:
            errors.append(f"gemini_http_{exc.code}")
            if exc.code not in (429, 500, 502, 503, 504):
                raise
        except Exception as exc:
            errors.append(f"gemini_failed:{type(exc).__name__}")

    if MINIMAX_API_KEY:
        try:
            return call_minimax(prompt_text, temperature=temperature, max_tokens=max_tokens, system_prompt=system_prompt, image_inputs=image_inputs)
        except HTTPError as exc:
            errors.append(f"minimax_http_{exc.code}")
            if exc.code not in (401, 403, 429, 500, 502, 503, 504):
                raise
        except Exception as exc:
            errors.append(f"minimax_failed:{type(exc).__name__}")

    if GROQ_API_KEY:
        try:
            return call_groq(prompt_text, temperature=temperature, max_tokens=max_tokens, system_prompt=system_prompt, image_inputs=image_inputs)
        except HTTPError as exc:
            errors.append(f"groq_http_{exc.code}")
            if exc.code not in (401, 403, 429, 500, 502, 503, 504):
                raise
        except Exception as exc:
            errors.append(f"groq_failed:{type(exc).__name__}")

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
    history_lines = []
    for item in load_recent_messages(conn, wa_id, limit=8):
        speaker = "對方" if item["direction"] == "inbound" else "蘇蘇"
        body = clean_text(item["body"])
        if body:
            history_lines.append(f"{speaker}: {body}")

    dynamic_memories = [
        f"- {clean_text(item.get('content'))}"
        for item in load_memories(conn, wa_id)
        if clean_text(item.get("content"))
    ]
    within_24h_memories = format_session_memory_lines(conn, wa_id, "within_24h", limit=4)
    within_3d_memories = format_session_memory_lines(conn, wa_id, "within_3d", limit=4)
    within_7d_memories = format_session_memory_lines(conn, wa_id, "within_7d", limit=4)
    image_stats_text = load_image_stats_summary(conn, wa_id)

    history_text = "\n".join(history_lines[-8:]) if history_lines else "（最近未有聊天）"
    memory_text = "\n".join(dynamic_memories) if dynamic_memories else "（暫時未有補充長期記憶）"
    within_24h_text = "\n".join(within_24h_memories) if within_24h_memories else "（暫時未有 24 小時內記憶）"
    within_3d_text = "\n".join(within_3d_memories) if within_3d_memories else "（暫時未有三天內記憶）"
    within_7d_text = "\n".join(within_7d_memories) if within_7d_memories else "（暫時未有一週內記憶）"

    image_hint = ""
    if image_stats_text:
        image_hint = f"\n對方平時 send 圖偏多嘅類型：{image_stats_text}"

    return f"""
對方 WhatsApp 顯示名稱：{profile_name or "對方"}

長期生活習慣：
{PRIMARY_USER_MEMORY}

長期補充記憶：
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
    finalize_stale_proactive_events(conn, wa_id)

    last_inbound = get_last_message_time(conn, wa_id, "inbound")
    if not last_inbound:
        return {"eligible": False, "reason": "no_inbound"}
    if now_utc - last_inbound > timedelta(hours=PROACTIVE_CONVERSATION_WINDOW_HOURS):
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
    if silence_minutes < PROACTIVE_MIN_SILENCE_MINUTES:
        return {"eligible": False, "reason": "cooling", "silence_minutes": silence_minutes}

    if get_pending_proactive_event(conn, wa_id):
        return {"eligible": False, "reason": "pending_proactive"}

    last_proactive = get_last_proactive_event(conn, wa_id)
    if last_proactive:
        last_proactive_at = parse_iso_dt(last_proactive.get("created_at", ""))
        if last_proactive_at and now_utc - last_proactive_at < timedelta(minutes=PROACTIVE_COOLDOWN_MINUTES):
            return {"eligible": False, "reason": "proactive_cooldown"}

    if count_inbound_messages(conn, wa_id) < PROACTIVE_MIN_INBOUND_MESSAGES:
        return {"eligible": False, "reason": "too_new"}

    daily_count = count_proactive_for_service_day(conn, wa_id, now)
    if daily_count >= PROACTIVE_MAX_PER_SERVICE_DAY:
        return {"eligible": False, "reason": "daily_cap"}

    slot_key = proactive_slot_key(now)
    slot_rate = get_slot_success_rate(conn, wa_id, slot_key)
    recent_hook_count = sum(
        len(format_session_memory_lines(conn, wa_id, bucket, limit=3))
        for bucket in ("within_24h", "within_3d", "within_7d")
    )
    image_bonus = 0.08 if load_image_stats_summary(conn, wa_id) else 0.0
    silence_bonus = min(max((silence_minutes - PROACTIVE_MIN_SILENCE_MINUTES) / 180.0, 0.0), 1.0) * 1.2
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
    if not PROACTIVE_ENABLED:
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
        time.sleep(max(PROACTIVE_SCAN_SECONDS, 60))


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
        history_lines.append(f"{label}{speaker}: {body}")
        if item["direction"] == "inbound" and msg_id and len(body) > 3:
            quotable.append((msg_id, body[:40]))

    dynamic_memories = [
        f"- {clean_text(item.get('content'))}"
        for item in load_memories(conn, wa_id)
        if clean_text(item.get("content"))
    ]
    within_24h_memories = format_session_memory_lines(conn, wa_id, "within_24h", limit=6)
    within_3d_memories = format_session_memory_lines(conn, wa_id, "within_3d", limit=6)
    within_7d_memories = format_session_memory_lines(conn, wa_id, "within_7d", limit=6)
    history_text = "\n".join(history_lines[-12:]) if history_lines else "（暂时未有最近聊天）"
    habit_text = PRIMARY_USER_MEMORY
    memory_text = "\n".join(dynamic_memories) if dynamic_memories else "（暂时未有补充长期记忆）"
    within_24h_text = "\n".join(within_24h_memories) if within_24h_memories else "（暂时未有 24 小时内记忆）"
    within_3d_text = "\n".join(within_3d_memories) if within_3d_memories else "（暂时未有三天内记忆）"
    within_7d_text = "\n".join(within_7d_memories) if within_7d_memories else "（暂时未有一周内记忆）"
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

長期生活習慣：
{habit_text}

長期補充記憶：
{memory_text}

24 小時內記憶：
{within_24h_text}

三天內記憶：
{within_3d_text}

一週內記憶：
{within_7d_text}

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
- 直接输出苏苏要发畀对方嘅 WhatsApp 内容本身，唔好加说明{quote_hint}
""".strip()


def normalize_reply(reply):
    text = (reply or "").strip().replace("\r", "\n")
    text = text.replace("——", " ").replace("--", " ").replace("—", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip(" \"'`")[:2000].strip()


def shorten_whatsapp_reply(reply, night_mode=False):
    text = normalize_reply(reply)
    if not text:
        return text

    max_lines = 3 if night_mode else 2
    max_sentences = 3 if night_mode else 2
    max_len = 120 if night_mode else 72
    min_cut = 45 if night_mode else 30

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    text = "\n".join(lines)

    sentences = re.split(r"(?<=[。！？!?~～…])\s*", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if len(sentences) > max_sentences:
        text = " ".join(sentences[:max_sentences]).strip()

    if len(text) > max_len:
        trimmed = text[:max_len].rstrip()
        cut = max(trimmed.rfind(mark) for mark in ["。", "！", "？", "!", "?", "~", "～", "…", " "])
        if cut > min_cut:
            text = trimmed[: cut + 1].strip()
        else:
            text = trimmed + "…"

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
- 只輸出回覆本身
""".strip()
    return generate_model_text(prompt, temperature=0.72, max_tokens=180)


def generate_reply(conn, wa_id, profile_name, incoming_text, image_inputs=None, image_categories=None):
    if not (RELAY_API_KEY or GEMINI_API_KEY or MINIMAX_API_KEY or GROQ_API_KEY):
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
            relay_primary, relay_secondary = get_relay_model_order()
            fallback_model = ""
            if RELAY_API_KEY and relay_secondary:
                fallback_model = relay_secondary
            elif GEMINI_API_KEY:
                fallback_model = GEMINI_MODEL
            elif MINIMAX_API_KEY:
                fallback_model = MINIMAX_MODEL
            elif GROQ_API_KEY:
                fallback_model = GROQ_MODEL

            self._send_json(
                {
                    "ok": True,
                    "checked_at": utc_now(),
                    "time_mode": "night" if is_night_mode() else "day",
                    "time_profile": get_time_profile(),
                    "timezone": "Asia/Hong_Kong",
                    "primary_model": relay_primary if RELAY_API_KEY else (GEMINI_MODEL if GEMINI_API_KEY else (MINIMAX_MODEL if MINIMAX_API_KEY else GROQ_MODEL)),
                    "fallback_model": fallback_model,
                    "has_relay_key": bool(RELAY_API_KEY),
                    "has_gemini_key": bool(GEMINI_API_KEY),
                    "has_minimax_key": bool(MINIMAX_API_KEY),
                    "has_groq_key": bool(GROQ_API_KEY),
                    "proactive_enabled": PROACTIVE_ENABLED,
                    "proactive_scan_seconds": PROACTIVE_SCAN_SECONDS,
                    "proactive_min_silence_minutes": PROACTIVE_MIN_SILENCE_MINUTES,
                    "proactive_cooldown_minutes": PROACTIVE_COOLDOWN_MINUTES,
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
                conn.commit()

                if event["message_type"] not in ("text", "image"):
                    continue

                time.sleep(INBOUND_GRACE_SECONDS)

                latest_inbound_id = get_latest_inbound_id(conn, event["wa_id"])
                if latest_inbound_id != inbound_row_id:
                    continue

                pending_rows = load_pending_inbound_batch(conn, event["wa_id"], inbound_row_id)
                if not pending_rows:
                    continue

                combined_text, memory_text = build_combined_user_input(pending_rows)
                image_inputs = collect_image_inputs(pending_rows)
                image_categories = classify_image_categories(combined_text, image_inputs)
                if not combined_text and not image_inputs:
                    continue

                if memory_text:
                    maybe_extract_memories(conn, event["wa_id"], event["profile_name"], memory_text)
                if combined_text:
                    maybe_extract_session_memories(conn, event["wa_id"], combined_text)
                    # Check if message contains a reminder request
                    try:
                        _remind_at, _remind_content = parse_reminder(event["wa_id"], combined_text)
                        if _remind_at and _remind_content:
                            save_reminder(conn, event["wa_id"], _remind_at, _remind_content)
                    except Exception:
                        pass
                if image_categories:
                    bump_image_stats(conn, event["wa_id"], image_categories)
                    conn.commit()

                # ── Claude Code 模式（第二號碼專用）──────────────────────
                reply_text = None
                _skip_generate = False
                last_body = clean_text(pending_rows[-1]["body"]) if pending_rows else (combined_text or "").strip()

                if event["wa_id"] == CLAUDE_WA_ID and not image_inputs:
                    run_claude_code_streaming(last_body, event["wa_id"])
                    _skip_generate = True

                if not _skip_generate:
                    try:
                        reply_text = generate_reply(
                            conn,
                            event["wa_id"],
                            event["profile_name"],
                            combined_text,
                            image_inputs=image_inputs,
                            image_categories=image_categories,
                        )
                    except Exception as exc:
                        reply_text = "我啱啱個腦有啲卡住咗，等我緩一緩先再同你傾，好唔好？"
                        conn.execute(
                            """
                            INSERT INTO wa_messages (wa_id, direction, message_id, message_type, body, raw_json, created_at)
                            VALUES (?, 'outbound', '', 'error', ?, ?, ?)
                            """,
                            (
                                event["wa_id"],
                                f"model_failed: {exc}",
                                json.dumps({"error": str(exc)}, ensure_ascii=False),
                                utc_now(),
                            ),
                        )
                        conn.commit()

                if reply_text is None:
                    continue

                try:
                    bubbles = split_reply_bubbles(reply_text, night_mode=is_night_mode())
                    bubbles = maybe_stage_followup_bubbles(bubbles, night_mode=is_night_mode())
                    # reaction on incoming message
                    reaction_emoji = pick_susu_reaction(combined_text or "", night_mode=is_night_mode())
                    if reaction_emoji and event.get("message_id"):
                        try:
                            send_whatsapp_reaction(event["wa_id"], event["message_id"], reaction_emoji)
                        except Exception:
                            pass
                    quote_id = _smart_quote_id if "_smart_quote_id" in vars() else ""
                    for index, bubble in enumerate(bubbles):
                        if index == 0 and quote_id:
                            response = send_whatsapp_quote(event["wa_id"], bubble, quote_id)
                        else:
                            response = send_whatsapp_text(event["wa_id"], bubble)
                        conn.execute(
                            """
                            INSERT INTO wa_messages (wa_id, direction, message_id, message_type, body, raw_json, created_at)
                            VALUES (?, 'outbound', ?, 'text', ?, ?, ?)
                            """,
                            (
                                event["wa_id"],
                                (response.get("messages") or [{}])[0].get("id", ""),
                                bubble,
                                json.dumps(response, ensure_ascii=False),
                                utc_now(),
                            ),
                        )
                        conn.commit()
                        if index < len(bubbles) - 1:
                            time.sleep(1.05)
                except Exception as exc:
                    conn.execute(
                        """
                        INSERT INTO wa_messages (wa_id, direction, message_id, message_type, body, raw_json, created_at)
                        VALUES (?, 'outbound', '', 'error', ?, ?, ?)
                        """,
                        (
                            event["wa_id"],
                            f"send_failed: {exc}",
                            json.dumps({"error": str(exc)}, ensure_ascii=False),
                            utc_now(),
                        ),
                    )
                    conn.commit()
        finally:
            conn.close()

        self._send_json({"ok": True})


if __name__ == "__main__":
    if PROACTIVE_ENABLED:
        threading.Thread(target=proactive_loop, name="wa-proactive-loop", daemon=True).start()
    threading.Thread(target=reminder_loop, name="wa-reminder-loop", daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", 9100), Handler)
    server.serve_forever()
