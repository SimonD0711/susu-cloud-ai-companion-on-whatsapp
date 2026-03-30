#!/usr/bin/env python3
import base64
import hashlib
import html
import hmac
import json
import os
import re
import shutil
import sqlite3
import ssl
import subprocess
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


BASE_DIR = Path("/var/www/html")
DB_PATH = BASE_DIR / "engagement.db"
UNKNOWN_LOCATION = "\u672a\u77e5\u4f4d\u7f6e"
ADMIN_NAME = "SimonD\uff08\u7ad9\u4e3b\uff09"
ADMIN_PASSWORD_SALT_B64 = "rj+nNw193+XBQ8+IyFmlUQ=="
ADMIN_PASSWORD_HASH_B64 = "DcUZc6HCEKdOJA215n4LTWcC/SbHknCocktIVbEBtYs="
ADMIN_SESSION_SECRET = "2c80b1f822a936df1d2fe5089abfca25d33964f81059b7f69991873efd35dd99"
ADMIN_SESSION_COOKIE = "cc_admin_session"
ADMIN_SESSION_TTL = 60 * 60 * 24 * 30
MONGO_URI = "mongodb://librechat:librechat_pass@127.0.0.1:27017/LibreChat?authSource=admin"
SITE_MONITORS = [
    {"id": "home", "label": "主頁", "url": "https://simond.photo/", "host": "simond.photo", "cert_path": "/etc/letsencrypt/live/simond.photo/fullchain.pem"},
    {"id": "cheungchau", "label": "長洲之旅", "url": "https://simond.photo/cheungchau.html", "host": "simond.photo", "cert_path": "/etc/letsencrypt/live/simond.photo/fullchain.pem"},
    {"id": "gemini", "label": "Gemini 子站", "url": "https://gemini.simond.photo/", "host": "gemini.simond.photo", "cert_path": "/etc/letsencrypt/live/gemini.simond.photo/fullchain.pem"},
]

COLLECTION_PAGE_EXCLUDES = {
    "index.html",
    "admin-stats.html",
    "gemini-guest-admin.html",
    "gemini-user-admin.html",
    "404.html",
    "cheungchau-plain.html",
}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS photo_likes (
            photo_id TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (photo_id, ip_address)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS photo_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            photo_id TEXT NOT NULL,
            parent_id INTEGER,
            author TEXT NOT NULL,
            body TEXT NOT NULL,
            is_pinned INTEGER NOT NULL DEFAULT 0,
            is_owner INTEGER NOT NULL DEFAULT 0,
            ip_address TEXT NOT NULL,
            masked_ip TEXT NOT NULL,
            location_label TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS comment_likes (
            comment_id INTEGER NOT NULL,
            ip_address TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (comment_id, ip_address)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ip_geo_cache (
            ip_address TEXT PRIMARY KEY,
            location_label TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metrics_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS system_metric_samples (
            bucket_start TEXT PRIMARY KEY,
            cpu_usage REAL,
            memory_usage REAL,
            disk_usage REAL,
            network_established INTEGER,
            network_total INTEGER,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS traffic_metric_buckets (
            bucket_start TEXT PRIMARY KEY,
            total_requests INTEGER NOT NULL DEFAULT 0,
            req_4xx INTEGER NOT NULL DEFAULT 0,
            req_5xx INTEGER NOT NULL DEFAULT 0,
            total_request_ms REAL NOT NULL DEFAULT 0,
            api_requests INTEGER NOT NULL DEFAULT 0,
            api_errors INTEGER NOT NULL DEFAULT 0,
            bytes_out INTEGER NOT NULL DEFAULT 0,
            bytes_in INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS page_view_buckets (
            bucket_start TEXT NOT NULL,
            path TEXT NOT NULL,
            views INTEGER NOT NULL DEFAULT 0,
            total_request_ms REAL NOT NULL DEFAULT 0,
            bytes_out INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (bucket_start, path)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS visitor_activity (
            minute_start TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            PRIMARY KEY (minute_start, ip_address)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS photo_view_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            photo_id TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            viewed_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_action_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(photo_comments)").fetchall()}
    if "location_label" not in columns:
        conn.execute("ALTER TABLE photo_comments ADD COLUMN location_label TEXT NOT NULL DEFAULT ''")
    if "parent_id" not in columns:
        conn.execute("ALTER TABLE photo_comments ADD COLUMN parent_id INTEGER")
    if "is_pinned" not in columns:
        conn.execute("ALTER TABLE photo_comments ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0")
    if "is_owner" not in columns:
        conn.execute("ALTER TABLE photo_comments ADD COLUMN is_owner INTEGER NOT NULL DEFAULT 0")
    return conn


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def mask_ip(ip):
    if ":" in ip:
        parts = ip.split(":")
        if len(parts) >= 4:
            return ":".join(parts[:2] + ["****", "****"])
        return ip
    parts = ip.split(".")
    if len(parts) == 4:
        return ".".join(parts[:2] + ["*", "*"])
    return ip


def normalize_ip(handler):
    forwarded = handler.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return handler.client_address[0]


def parse_cookies(handler):
    cookie_header = handler.headers.get("Cookie", "")
    cookies = {}
    for item in cookie_header.split(";"):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        cookies[key.strip()] = value.strip()
    return cookies


def sign_admin_session(expires_at):
    message = f"admin|{expires_at}".encode("utf-8")
    return hmac.new(ADMIN_SESSION_SECRET.encode("utf-8"), message, hashlib.sha256).hexdigest()


def make_admin_session_cookie():
    expires_at = int(time.time()) + ADMIN_SESSION_TTL
    signature = sign_admin_session(expires_at)
    token = base64.urlsafe_b64encode(f"{expires_at}:{signature}".encode("utf-8")).decode("ascii")
    return f"{ADMIN_SESSION_COOKIE}={token}; Max-Age={ADMIN_SESSION_TTL}; Path=/; HttpOnly; SameSite=Lax"


def clear_admin_session_cookie():
    return f"{ADMIN_SESSION_COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax"


def is_admin_authenticated(handler):
    token = parse_cookies(handler).get(ADMIN_SESSION_COOKIE)
    if not token:
        return False
    try:
        decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        expires_at_raw, signature = decoded.split(":", 1)
        expires_at = int(expires_at_raw)
    except Exception:
        return False
    if expires_at < int(time.time()):
        return False
    return hmac.compare_digest(signature, sign_admin_session(expires_at))


def verify_admin_password(password):
    salt = base64.b64decode(ADMIN_PASSWORD_SALT_B64)
    expected = base64.b64decode(ADMIN_PASSWORD_HASH_B64)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210000, dklen=32)
    return hmac.compare_digest(actual, expected)


def get_location_label(conn, ip):
    if not ip:
        return UNKNOWN_LOCATION

    cached = conn.execute(
        "SELECT location_label FROM ip_geo_cache WHERE ip_address = ?",
        (ip,),
    ).fetchone()
    if cached:
        return cached["location_label"]

    try:
        with urlopen(
            f"http://ip-api.com/json/{ip}?fields=status,country,regionName,city&lang=zh-CN",
            timeout=4,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("status") == "success":
            pieces = [payload.get("country"), payload.get("regionName"), payload.get("city")]
            label = " ".join([item.strip() for item in pieces if item and item.strip()]) or UNKNOWN_LOCATION
        else:
            label = UNKNOWN_LOCATION
    except Exception:
        label = UNKNOWN_LOCATION

    conn.execute(
        "INSERT OR REPLACE INTO ip_geo_cache (ip_address, location_label, updated_at) VALUES (?, ?, ?)",
        (ip, label, utc_now()),
    )
    conn.commit()
    return label


def is_mainland_china_label(label):
    return bool(label and label.startswith("涓浗"))


def fetch_comment_rows(conn, viewer_ip, viewer_is_admin, photo_id=None):
    query = """
        SELECT id, photo_id, parent_id, author, body, is_pinned, is_owner, masked_ip, created_at,
               location_label,
               COALESCE(cl.like_count, 0) AS like_count,
               CASE WHEN ul.comment_id IS NOT NULL THEN 1 ELSE 0 END AS liked,
               CASE WHEN ip_address = ? OR (is_owner = 1 AND ? = 1) THEN 1 ELSE 0 END AS can_edit,
               CASE WHEN ip_address = ? OR ? = 1 THEN 1 ELSE 0 END AS can_delete,
               CASE WHEN ? = 1 THEN 1 ELSE 0 END AS can_pin
        FROM photo_comments
        LEFT JOIN (
            SELECT comment_id, COUNT(*) AS like_count
            FROM comment_likes
            GROUP BY comment_id
        ) AS cl ON cl.comment_id = photo_comments.id
        LEFT JOIN (
            SELECT comment_id
            FROM comment_likes
            WHERE ip_address = ?
        ) AS ul ON ul.comment_id = photo_comments.id
    """
    params = [
        viewer_ip,
        1 if viewer_is_admin else 0,
        viewer_ip,
        1 if viewer_is_admin else 0,
        1 if viewer_is_admin else 0,
        viewer_ip,
    ]
    if photo_id:
        query += " WHERE photo_id = ?"
        params.append(photo_id)
    query += " ORDER BY id ASC"
    return conn.execute(query, params).fetchall()


def fetch_like_insights(conn, photo_id):
    rows = conn.execute(
        """
        SELECT ip_address, created_at
        FROM photo_likes
        WHERE photo_id = ?
        ORDER BY created_at DESC
        """,
        (photo_id,),
    ).fetchall()
    insights = []
    for row in rows:
        ip_address = row["ip_address"]
        insights.append(
            {
                "masked_ip": mask_ip(ip_address),
                "location_label": get_location_label(conn, ip_address),
                "created_at": row["created_at"],
            }
        )
    return {"count": len(insights), "likes": insights}


def fetch_admin_stats(conn):
    summary = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM photo_likes) AS total_likes,
            (SELECT COUNT(*) FROM photo_comments) AS total_comments,
            (SELECT COUNT(DISTINCT photo_id) FROM photo_likes) AS liked_photos,
            (SELECT COUNT(DISTINCT photo_id) FROM photo_comments) AS commented_photos
        """
    ).fetchone()

    photo_rows = conn.execute(
        """
        SELECT
            p.photo_id,
            COALESCE(l.like_count, 0) AS likes,
            COALESCE(c.comment_count, 0) AS comments,
            COALESCE(c.owner_comment_count, 0) AS owner_comments,
            COALESCE(c.last_comment_at, '') AS last_comment_at
        FROM (
            SELECT photo_id FROM photo_likes
            UNION
            SELECT photo_id FROM photo_comments
        ) AS p
        LEFT JOIN (
            SELECT photo_id, COUNT(*) AS like_count
            FROM photo_likes
            GROUP BY photo_id
        ) AS l ON l.photo_id = p.photo_id
        LEFT JOIN (
            SELECT
                photo_id,
                COUNT(*) AS comment_count,
                SUM(CASE WHEN is_owner = 1 THEN 1 ELSE 0 END) AS owner_comment_count,
                MAX(created_at) AS last_comment_at
            FROM photo_comments
            GROUP BY photo_id
        ) AS c ON c.photo_id = p.photo_id
        ORDER BY likes DESC, comments DESC, p.photo_id ASC
        """
    ).fetchall()

    like_location_rows = conn.execute(
        """
        SELECT ip_address
        FROM photo_likes
        ORDER BY created_at DESC
        """
    ).fetchall()
    like_location_counts = {}
    for row in like_location_rows:
        label = get_location_label(conn, row["ip_address"])
        like_location_counts[label] = like_location_counts.get(label, 0) + 1

    comment_location_rows = conn.execute(
        """
        SELECT location_label, COUNT(*) AS count
        FROM photo_comments
        GROUP BY location_label
        ORDER BY count DESC, location_label ASC
        """
    ).fetchall()

    return {
        "summary": {
            "total_likes": summary["total_likes"],
            "total_comments": summary["total_comments"],
            "liked_photos": summary["liked_photos"],
            "commented_photos": summary["commented_photos"],
        },
        "photos": [dict(row) for row in photo_rows],
        "like_locations": [
            {"location_label": label, "count": count}
            for label, count in sorted(like_location_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "comment_locations": [dict(row) for row in comment_location_rows],
        "site_overview": fetch_site_status(),
    }


def parse_iso_datetime(value):
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def read_recent_error_summary(log_path="/var/log/nginx/error.log", max_lines=200):
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as handle:
            lines = handle.readlines()[-max_lines:]
    except Exception:
        return {"warn": 0, "error": 0, "crit": 0, "recent": []}

    counts = {"warn": 0, "error": 0, "crit": 0}
    recent = []
    for line in lines:
        lowered = line.lower()
        for level in counts:
            if f"[{level}]" in lowered:
                counts[level] += 1
                if len(recent) < 5:
                    recent.append(line.strip())
                break
    return {**counts, "recent": recent[:5]}


def read_network_status():
    try:
        result = subprocess.run(
            ["ss", "-tan"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        lines = (result.stdout or "").splitlines()[1:]
    except Exception:
        return {"total": None, "established": None}

    total = len(lines)
    established = sum(1 for line in lines if line.lstrip().startswith("ESTAB"))
    return {"total": total, "established": established}


def describe_cert(cert_path, label, hostname):
    try:
        cert = ssl._ssl._test_decode_cert(cert_path)
        expires_at = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        days_left = max((expires_at - datetime.now(timezone.utc)).days, 0)
        return {
            "label": label,
            "hostname": hostname,
            "expires_at": expires_at.isoformat(),
            "days_left": days_left,
        }
    except Exception:
        return {
            "label": label,
            "hostname": hostname,
            "expires_at": "",
            "days_left": None,
        }


def fetch_site_status():
    unverified_context = ssl._create_unverified_context()
    checks = []
    certificates = []

    for item in SITE_MONITORS:
        started = time.perf_counter()
        status_code = None
        content_length = None
        error_message = ""
        try:
            request = Request(item["url"], method="HEAD", headers={"User-Agent": "simond.photo-admin/1.0"})
            with urlopen(request, timeout=6, context=unverified_context) as response:
                status_code = response.status
                content_length = response.headers.get("Content-Length", "")
        except Exception as exc:
            error_message = str(exc)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        checks.append(
            {
                "id": item["id"],
                "label": item["label"],
                "url": item["url"],
                "status_code": status_code,
                "response_ms": elapsed_ms,
                "content_length": content_length,
                "ok": bool(status_code and status_code < 400),
                "error": error_message[:120],
            }
        )
        certificates.append(describe_cert(item["cert_path"], item["label"], item["host"]))

    return {
        "checked_at": utc_now(),
        "checks": checks,
        "certificates": certificates,
    }


def extract_first(pattern, text, default=""):
    match = re.search(pattern, text, re.I | re.S)
    return match.group(1).strip() if match else default


def strip_html_tags(text):
    plain = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(plain)).strip()


def discover_collection_pages():
    items = []
    for path in sorted(BASE_DIR.glob("*.html")):
        if path.name in COLLECTION_PAGE_EXCLUDES:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        coord_matches = re.findall(r"google\.com/maps/search/\?api=1&query=([-0-9.]+),([-0-9.]+)", content, re.I)
        if not coord_matches:
            continue

        coords = [(float(lat), float(lng)) for lat, lng in coord_matches]
        center_lat = round(sum(lat for lat, _ in coords) / len(coords), 6)
        center_lng = round(sum(lng for _, lng in coords) / len(coords), 6)
        unique_points = len({(round(lat, 6), round(lng, 6)) for lat, lng in coords})

        title = strip_html_tags(
            extract_first(r"<h1[^>]*>(.*?)</h1>", content)
            or extract_first(r'<meta\s+property="og:title"\s+content="([^"]+)"', content)
            or path.stem
        )
        description = html.unescape(
            extract_first(r'<meta\s+name="description"\s+content="([^"]+)"', content)
            or extract_first(r'<p[^>]*class="desc"[^>]*>(.*?)</p>', content)
        )
        description = strip_html_tags(description)

        cover = extract_first(r'src="(/thumbs/[^"]+)"', content)
        if cover and not cover.startswith("http"):
            cover = cover if cover.startswith("/") else f"/{cover}"

        items.append(
            {
                "slug": path.stem,
                "title": title,
                "url": "/" if path.name == "index.html" else f"/{path.name}",
                "description": description,
                "cover": cover,
                "center_lat": center_lat,
                "center_lng": center_lng,
                "photo_count": len(coords),
                "location_count": unique_points,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
        )

    items.sort(key=lambda item: item["updated_at"], reverse=True)
    return {
        "checked_at": utc_now(),
        "count": len(items),
        "collections": items,
    }


def fetch_metric_trends(conn):
    rows = conn.execute(
        """
        SELECT bucket_start, cpu_usage, memory_usage, disk_usage
        FROM system_metric_samples
        WHERE bucket_start >= datetime('now', '-24 hours')
        ORDER BY bucket_start ASC
        """
    ).fetchall()
    return {
        "labels": [row["bucket_start"] for row in rows],
        "cpu": [row["cpu_usage"] for row in rows],
        "memory": [row["memory_usage"] for row in rows],
        "disk": [row["disk_usage"] for row in rows],
    }


def fetch_traffic_insights(conn):
    summary = conn.execute(
        """
        SELECT
            COALESCE(SUM(total_requests), 0) AS total_requests,
            COALESCE(SUM(req_4xx), 0) AS req_4xx,
            COALESCE(SUM(req_5xx), 0) AS req_5xx,
            COALESCE(SUM(total_request_ms), 0) AS total_request_ms,
            COALESCE(SUM(api_requests), 0) AS api_requests,
            COALESCE(SUM(api_errors), 0) AS api_errors,
            COALESCE(SUM(bytes_out), 0) AS bytes_out,
            COALESCE(SUM(bytes_in), 0) AS bytes_in
        FROM traffic_metric_buckets
        WHERE bucket_start >= datetime('now', '-24 hours')
        """
    ).fetchone()

    top_pages = conn.execute(
        """
        SELECT
            path,
            SUM(views) AS views,
            SUM(total_request_ms) AS total_request_ms,
            SUM(bytes_out) AS bytes_out
        FROM page_view_buckets
        WHERE bucket_start >= datetime('now', '-24 hours')
        GROUP BY path
        ORDER BY views DESC, path ASC
        LIMIT 8
        """
    ).fetchall()

    active_15m = conn.execute(
        """
        SELECT COUNT(DISTINCT ip_address) AS count
        FROM visitor_activity
        WHERE minute_start >= datetime('now', '-15 minutes')
        """
    ).fetchone()["count"]
    active_24h = conn.execute(
        """
        SELECT COUNT(DISTINCT ip_address) AS count
        FROM visitor_activity
        WHERE minute_start >= datetime('now', '-24 hours')
        """
    ).fetchone()["count"]

    total_requests = summary["total_requests"] or 0
    total_request_ms = summary["total_request_ms"] or 0
    api_requests = summary["api_requests"] or 0
    api_errors = summary["api_errors"] or 0

    return {
        "requests_24h": total_requests,
        "errors_4xx": summary["req_4xx"] or 0,
        "errors_5xx": summary["req_5xx"] or 0,
        "avg_response_ms": round(total_request_ms / total_requests, 1) if total_requests else 0.0,
        "api_requests": api_requests,
        "api_success_rate": round(((api_requests - api_errors) / api_requests) * 100, 1) if api_requests else 100.0,
        "api_error_count": api_errors,
        "bandwidth_out_mb": round((summary["bytes_out"] or 0) / (1024 * 1024), 2),
        "bandwidth_in_mb": round((summary["bytes_in"] or 0) / (1024 * 1024), 2),
        "active_visitors_15m": active_15m,
        "active_visitors_24h": active_24h,
        "top_pages": [dict(row) for row in top_pages],
    }


def fetch_photo_insights(conn):
    rows = conn.execute(
        """
        SELECT
            photo_id,
            COUNT(*) AS views
        FROM photo_view_events
        WHERE viewed_at >= datetime('now', '-30 days')
        GROUP BY photo_id
        """
    ).fetchall()
    view_map = {row["photo_id"]: row["views"] for row in rows}

    stats_rows = conn.execute(
        """
        SELECT
            photo_id,
            SUM(likes) AS likes,
            SUM(comments) AS comments
        FROM (
            SELECT photo_id, COUNT(*) AS likes, 0 AS comments
            FROM photo_likes
            GROUP BY photo_id
            UNION ALL
            SELECT photo_id, 0 AS likes, COUNT(*) AS comments
            FROM photo_comments
            GROUP BY photo_id
        )
        GROUP BY photo_id
        """
    ).fetchall()

    combined = []
    seen = set(view_map.keys())
    seen.update(row["photo_id"] for row in stats_rows)
    for photo_id in sorted(seen):
        views = int(view_map.get(photo_id, 0) or 0)
        stats = next((row for row in stats_rows if row["photo_id"] == photo_id), None)
        likes = int((stats["likes"] if stats else 0) or 0)
        comments = int((stats["comments"] if stats else 0) or 0)
        combined.append(
            {
                "photo_id": photo_id,
                "views": views,
                "likes": likes,
                "comments": comments,
                "like_rate": round((likes / views) * 100, 1) if views else 0.0,
                "comment_rate": round((comments / views) * 100, 1) if views else 0.0,
            }
        )

    combined.sort(key=lambda item: (-item["views"], -item["likes"], item["photo_id"]))
    return combined[:12]


def fetch_owner_effect(conn):
    rows = conn.execute(
        """
        SELECT
            owner.photo_id,
            owner.created_at AS owner_comment_at,
            owner.author,
            owner.body,
            (
                SELECT COUNT(*)
                FROM photo_likes AS likes
                WHERE likes.photo_id = owner.photo_id
                  AND likes.created_at > owner.created_at
            ) AS likes_after,
            (
                SELECT COUNT(*)
                FROM photo_comments AS comments
                WHERE comments.photo_id = owner.photo_id
                  AND comments.created_at > owner.created_at
                  AND comments.id != owner.id
            ) AS comments_after
        FROM photo_comments AS owner
        INNER JOIN (
            SELECT photo_id, MAX(created_at) AS latest_owner_comment
            FROM photo_comments
            WHERE is_owner = 1
            GROUP BY photo_id
        ) AS latest
          ON latest.photo_id = owner.photo_id
         AND latest.latest_owner_comment = owner.created_at
        WHERE owner.is_owner = 1
        ORDER BY owner.created_at DESC
        LIMIT 8
        """
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_region_trends(conn):
    like_rows = conn.execute(
        """
        SELECT ip_address, created_at
        FROM photo_likes
        WHERE created_at >= datetime('now', '-30 days')
        ORDER BY created_at DESC
        """
    ).fetchall()
    region_map = {}
    for row in like_rows:
        label = get_location_label(conn, row["ip_address"])
        bucket = region_map.setdefault(label, {"location_label": label, "likes": 0, "comments": 0, "total": 0})
        bucket["likes"] += 1
        bucket["total"] += 1

    comment_rows = conn.execute(
        """
        SELECT location_label, COUNT(*) AS count
        FROM photo_comments
        WHERE created_at >= datetime('now', '-30 days')
        GROUP BY location_label
        """
    ).fetchall()
    for row in comment_rows:
        label = row["location_label"] or UNKNOWN_LOCATION
        bucket = region_map.setdefault(label, {"location_label": label, "likes": 0, "comments": 0, "total": 0})
        bucket["comments"] += int(row["count"] or 0)
        bucket["total"] += int(row["count"] or 0)

    items = sorted(region_map.values(), key=lambda item: (-item["total"], item["location_label"]))
    return items[:12]


def fetch_recent_interactions(conn):
    rows = conn.execute(
        """
        SELECT event_type, photo_id, actor, body, created_at
        FROM (
            SELECT
                'like' AS event_type,
                photo_id,
                '' AS actor,
                '' AS body,
                created_at
            FROM photo_likes
            UNION ALL
            SELECT
                CASE WHEN is_owner = 1 THEN 'owner_comment' ELSE 'comment' END AS event_type,
                photo_id,
                author AS actor,
                body,
                created_at
            FROM photo_comments
        )
        ORDER BY created_at DESC
        LIMIT 18
        """
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_failed_units():
    try:
        result = subprocess.run(
            ["systemctl", "--failed", "--no-legend", "--plain"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        return lines[:8]
    except Exception:
        return []


def read_service_detail(name):
    detail = {"name": name, "status": service_status(name), "last_started": "", "restart_count": None}
    try:
        result = subprocess.run(
            ["systemctl", "show", name, "--property=ActiveEnterTimestamp,NRestarts"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        for line in (result.stdout or "").splitlines():
            if line.startswith("ActiveEnterTimestamp="):
                detail["last_started"] = line.split("=", 1)[1].strip()
            elif line.startswith("NRestarts="):
                raw_value = line.split("=", 1)[1].strip()
                detail["restart_count"] = int(raw_value) if raw_value.isdigit() else None
    except Exception:
        return detail
    return detail


def fetch_service_health():
    reboot_count = None
    last_boot = ""
    try:
        result = subprocess.run(
            ["journalctl", "--list-boots", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
        lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
        reboot_count = len(lines)
        if lines:
            last_boot = lines[-1]
    except Exception:
        reboot_count = None

    return {
        "services": [
            read_service_detail("nginx"),
            read_service_detail("cheungchau-api"),
        ],
        "failed_units": fetch_failed_units(),
        "reboot_count": reboot_count,
        "last_boot": last_boot,
    }


def fetch_alerts(disk_data, certificate_items):
    alerts = []
    usage = disk_data.get("usage_percent")
    free_gb = disk_data.get("free_gb")
    if usage is not None and usage >= 85:
        alerts.append({"level": "error", "label": "Disk usage high", "detail": f"Root disk usage is {usage}%."})
    elif usage is not None and usage >= 75:
        alerts.append({"level": "warn", "label": "Disk usage warning", "detail": f"Root disk usage is {usage}%, free space {free_gb} GB."})
    for item in certificate_items:
        days_left = item.get("days_left")
        hostname = item.get("hostname", "certificate")
        if days_left is None:
            alerts.append({"level": "warn", "label": f"{hostname} unreadable", "detail": "Certificate expiry could not be checked."})
        elif days_left <= 14:
            alerts.append({"level": "error", "label": f"{hostname} expiring soon", "detail": f"Certificate expires in {days_left} days."})
        elif days_left <= 30:
            alerts.append({"level": "warn", "label": f"{hostname} nearing expiry", "detail": f"Certificate expires in {days_left} days."})
    return alerts

def fetch_recent_deployments():
    tracked_paths = [
        BASE_DIR / "index.html",
        BASE_DIR / "cheungchau.html",
        BASE_DIR / "admin-stats.html",
        BASE_DIR / "api_server.py",
        Path("/etc/nginx/sites-enabled/default"),
        Path("/etc/nginx/nginx.conf"),
    ]
    items = []
    for path in tracked_paths:
        try:
            stat = path.stat()
        except Exception:
            continue
        items.append(
            {
                "path": str(path),
                "updated_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            }
        )
    items.sort(key=lambda item: item["updated_at"], reverse=True)
    return items[:10]


def fetch_admin_action_logs(conn):
    rows = conn.execute(
        """
        SELECT action, detail, status, created_at
        FROM admin_action_logs
        ORDER BY id DESC
        LIMIT 12
        """
    ).fetchall()
    return [dict(row) for row in rows]


def log_admin_action(conn, action, status, detail=""):
    conn.execute(
        "INSERT INTO admin_action_logs (action, detail, status, created_at) VALUES (?, ?, ?, ?)",
        (action, detail[:500], status, utc_now()),
    )
    conn.commit()


def call_guest_service(path, method="GET", payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"http://127.0.0.1:3001{path}", data=data, headers=headers, method=method)
    with urlopen(request, timeout=8) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def fetch_gemini_guest_pool():
    return call_guest_service("/guest-admin/status")


def run_gemini_guest_action(action, email=""):
    payload = {"action": action}
    if email:
        payload["email"] = email
    return call_guest_service("/guest-admin/action", method="POST", payload=payload)


def run_librechat_node_json(script):
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "librechat-librechat-1",
            "node",
            "-e",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "node query failed").strip()
        raise RuntimeError(detail[:500])
    raw = (result.stdout or "").strip()
    if not raw:
        return {}
    return json.loads(raw)


def fetch_gemini_user_accounts():
    script = r"""
const { MongoClient } = require('mongodb');
const MONGO_URI = 'mongodb://librechat:librechat_pass@mongodb:27017/LibreChat?authSource=admin';
const recent24h = Date.now() - (24 * 60 * 60 * 1000);
const recent7d = Date.now() - (7 * 24 * 60 * 60 * 1000);

function toIso(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function toMillis(value) {
  if (!value) return 0;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 0 : date.getTime();
}

(async () => {
  const client = new MongoClient(MONGO_URI);
  await client.connect();
  const db = client.db('LibreChat');
  const users = await db.collection('users').find(
    {
      email: {
        $not: /^guest(\d+)?@gemini\.simond\.photo$/i
      }
    },
    {
      projection: {
        email: 1,
        name: 1,
        username: 1,
        role: 1,
        createdAt: 1,
        updatedAt: 1
      }
    }
  ).sort({ updatedAt: -1, createdAt: -1 }).toArray();

  const rows = [];
  for (const user of users) {
    const userFilter = { $or: [{ user: user._id }, { user: String(user._id) }] };
    const session = await db.collection('sessions')
      .find(userFilter, { projection: { createdAt: 1, updatedAt: 1, expiration: 1 } })
      .sort({ updatedAt: -1, createdAt: -1 })
      .limit(1)
      .next();
    const conversations = await db.collection('conversations')
      .find(userFilter, { projection: { conversationId: 1, createdAt: 1, updatedAt: 1 } })
      .sort({ updatedAt: -1, createdAt: -1 })
      .toArray();
    const conversationIds = conversations.map((item) => item.conversationId).filter(Boolean);
    const latestConversation = conversations[0] || null;
    const [messageCount, presetCount, fileCount, sessionCount] = await Promise.all([
      conversationIds.length ? db.collection('messages').countDocuments({ conversationId: { $in: conversationIds } }) : 0,
      db.collection('presets').countDocuments({ user: user._id }),
      db.collection('files').countDocuments({ user: user._id }),
      db.collection('sessions').countDocuments(userFilter)
    ]);
    const lastActivityAt =
      latestConversation?.updatedAt ||
      latestConversation?.createdAt ||
      session?.updatedAt ||
      session?.createdAt ||
      session?.expiration ||
      user.updatedAt ||
      user.createdAt ||
      null;
    const lastActivityMs = toMillis(lastActivityAt);
    rows.push({
      email: user.email || '',
      name: user.name || '',
      username: user.username || '',
      role: user.role || 'user',
      created_at: toIso(user.createdAt),
      updated_at: toIso(user.updatedAt),
      last_session_at: toIso(session?.updatedAt || session?.createdAt || null),
      last_activity_at: toIso(lastActivityAt),
      is_active_24h: lastActivityMs >= recent24h,
      conversation_count: conversations.length,
      message_count: messageCount,
      preset_count: presetCount,
      file_count: fileCount,
      session_count: sessionCount
    });
  }

  const payload = {
    checked_at: new Date().toISOString(),
    total_users: rows.length,
    active_24h: rows.filter((row) => row.is_active_24h).length,
    created_7d: rows.filter((row) => toMillis(row.created_at) >= recent7d).length,
    users: rows
  };

  console.log(JSON.stringify(payload));
  await client.close();
})().catch((error) => {
  console.error(error.message || String(error));
  process.exit(1);
});
"""
    return run_librechat_node_json(script)


NODE_MODULES = "/opt/librechat/node_modules"
MONGO_URI_LOCAL = "mongodb://librechat:librechat_pass@127.0.0.1:27017/LibreChat?authSource=admin"


def run_admin_action(action):
    cache_dir = Path("/var/cache/nginx")
    backup_dir = Path("/root/backups")

    if action == "clear_cache":
        removed = 0
        if cache_dir.exists():
            for item in cache_dir.rglob("*"):
                if item.is_file():
                    try:
                        item.unlink()
                        removed += 1
                    except Exception:
                        continue
        return {"ok": True, "detail": f"Cleared {removed} cache files."}

    if action == "reload_nginx":
        test_result = subprocess.run(["nginx", "-t"], capture_output=True, text=True, timeout=6, check=False)
        if test_result.returncode != 0:
            detail = (test_result.stderr or test_result.stdout or "nginx -t failed").strip()
            return {"ok": False, "detail": detail[:500]}
        reload_result = subprocess.run(
            ["systemctl", "reload", "nginx"],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
        if reload_result.returncode != 0:
            detail = (reload_result.stderr or reload_result.stdout or "reload failed").strip()
            return {"ok": False, "detail": detail[:500]}
        return {"ok": True, "detail": "nginx reloaded."}

    if action == "restart_api":
        subprocess.Popen(
            ["/bin/sh", "-lc", "sleep 1 && systemctl restart cheungchau-api >/tmp/cheungchau-api-restart.log 2>&1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {"ok": True, "detail": "Scheduled cheungchau-api restart."}

    if action == "backup_db":
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"engagement-{timestamp}.sqlite3"
        shutil.copy2(DB_PATH, target)
        return {"ok": True, "detail": f"Database backup created: {target}"}

    return {"ok": False, "detail": "Unknown action."}

def format_uptime(total_seconds):
    total_seconds = max(int(total_seconds), 0)
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def read_meminfo():
    meminfo = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                key, value = line.split(":", 1)
                meminfo[key] = int(value.strip().split()[0])
    except Exception:
        return {}
    return meminfo


def read_cpu_times():
    try:
        with open("/proc/stat", "r", encoding="utf-8") as handle:
            line = handle.readline()
    except Exception:
        return None
    parts = line.split()
    if not parts or parts[0] != "cpu":
        return None
    values = [int(item) for item in parts[1:]]
    total = sum(values)
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return total, idle


def sample_cpu_percent(delay=0.12):
    first = read_cpu_times()
    if not first:
        return None
    time.sleep(delay)
    second = read_cpu_times()
    if not second:
        return None
    total_delta = second[0] - first[0]
    idle_delta = second[1] - first[1]
    if total_delta <= 0:
        return None
    return round(max(0.0, min(100.0, (1 - idle_delta / total_delta) * 100)), 1)


def service_status(name):
    try:
        result = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return (result.stdout or result.stderr).strip() or "unknown"
    except Exception:
        return "unknown"


def fetch_server_status():
    conn = get_db()
    meminfo = read_meminfo()
    total_mem_kb = meminfo.get("MemTotal", 0)
    available_mem_kb = meminfo.get("MemAvailable", 0)
    swap_total_kb = meminfo.get("SwapTotal", 0)
    swap_free_kb = meminfo.get("SwapFree", 0)
    disk_total, disk_used, disk_free = shutil.disk_usage("/")
    try:
        load1, load5, load15 = os.getloadavg()
    except OSError:
        load1 = load5 = load15 = 0.0
    cpu_percent = sample_cpu_percent()
    uptime_seconds = 0.0
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as handle:
            uptime_seconds = float(handle.read().split()[0])
    except Exception:
        uptime_seconds = 0.0
    disk_data = {
        "total_gb": round(disk_total / (1024 ** 3), 1),
        "used_gb": round(disk_used / (1024 ** 3), 1),
        "free_gb": round(disk_free / (1024 ** 3), 1),
        "usage_percent": round((disk_used / disk_total) * 100, 1) if disk_total else None,
    }
    certificates = [
        describe_cert("/etc/letsencrypt/live/simond.photo/fullchain.pem", "主站證書", "simond.photo"),
        describe_cert("/etc/letsencrypt/live/gemini.simond.photo/fullchain.pem", "Gemini 證書", "gemini.simond.photo"),
    ]

    try:
        return {
            "checked_at": utc_now(),
            "hostname": os.uname().nodename,
            "uptime": format_uptime(uptime_seconds),
            "uptime_seconds": int(uptime_seconds),
            "cpu": {
                "usage_percent": cpu_percent,
                "load_average": [round(load1, 2), round(load5, 2), round(load15, 2)],
                "cores": os.cpu_count() or 1,
            },
            "memory": {
                "total_mb": round(total_mem_kb / 1024, 1),
                "available_mb": round(available_mem_kb / 1024, 1),
                "used_mb": round(max(total_mem_kb - available_mem_kb, 0) / 1024, 1),
                "usage_percent": round(((total_mem_kb - available_mem_kb) / total_mem_kb) * 100, 1) if total_mem_kb else None,
            },
            "swap": {
                "total_mb": round(swap_total_kb / 1024, 1),
                "used_mb": round(max(swap_total_kb - swap_free_kb, 0) / 1024, 1),
                "usage_percent": round(((swap_total_kb - swap_free_kb) / swap_total_kb) * 100, 1) if swap_total_kb else 0.0,
            },
            "disk": disk_data,
            "services": [
                {"name": "nginx", "status": service_status("nginx")},
                {"name": "cheungchau-api", "status": service_status("cheungchau-api")},
            ],
            "network": read_network_status(),
            "error_summary": read_recent_error_summary(),
            "certificates": certificates,
            "site_overview": fetch_site_status(),
            "trends_24h": fetch_metric_trends(conn),
            "traffic_24h": fetch_traffic_insights(conn),
            "photo_insights": fetch_photo_insights(conn),
            "owner_effect": fetch_owner_effect(conn),
            "region_trends": fetch_region_trends(conn),
            "recent_interactions": fetch_recent_interactions(conn),
            "service_health": fetch_service_health(),
            "alerts": fetch_alerts(disk_data, certificates),
            "deployments": fetch_recent_deployments(),
            "admin_actions": fetch_admin_action_logs(conn),
        }
    finally:
        conn.close()


def shape_photo_comments(rows):
    comment_lookup = {}
    top_level = []

    for row in rows:
        comment = dict(row)
        comment.update({"replies": [], "reply_count": 0})
        comment_lookup[comment["id"]] = comment

    floor = 0
    for row in rows:
        comment = comment_lookup[row["id"]]
        parent_id = comment["parent_id"]
        if parent_id is None:
            floor += 1
            comment["floor"] = floor
            top_level.append(comment)
            continue
        parent = comment_lookup.get(parent_id)
        if not parent:
            floor += 1
            comment["floor"] = floor
            top_level.append(comment)
            continue
        comment["floor"] = parent["floor"]
        comment["reply_to_author"] = parent["author"]
        parent["replies"].append(comment)

    def finalize(nodes):
        total = 0
        for node in nodes:
            node["replies"].sort(key=lambda item: (0 if item["is_pinned"] else 1, item["id"]))
            total += 1
            total += finalize(node["replies"])
            node["reply_count"] = len(node["replies"])
        return total

    top_level.sort(key=lambda item: (0 if item["is_pinned"] else 1, item["id"]))
    total_comments = finalize(top_level)
    return {"comments": top_level, "comment_count": total_comments}


def photo_payload(conn, photo_id, viewer_ip="", viewer_is_admin=False):
    likes = conn.execute(
        "SELECT COUNT(*) AS count FROM photo_likes WHERE photo_id = ?",
        (photo_id,),
    ).fetchone()["count"]
    liked = False
    if viewer_ip:
        liked = bool(
            conn.execute(
                "SELECT 1 FROM photo_likes WHERE photo_id = ? AND ip_address = ?",
                (photo_id, viewer_ip),
            ).fetchone()
        )
    comments_payload = shape_photo_comments(fetch_comment_rows(conn, viewer_ip, viewer_is_admin, photo_id))
    return {
        "likes": likes,
        "liked": liked,
        "comments": comments_payload["comments"],
        "comment_count": comments_payload["comment_count"],
        "admin_authenticated": viewer_is_admin,
    }


def photo_payloads(conn, viewer_ip="", viewer_is_admin=False):
    payload = {}
    liked_photo_ids = set()

    if viewer_ip:
        liked_photo_ids = {
            row["photo_id"]
            for row in conn.execute(
                "SELECT photo_id FROM photo_likes WHERE ip_address = ?",
                (viewer_ip,),
            ).fetchall()
        }

    for row in conn.execute(
        "SELECT photo_id, COUNT(*) AS count FROM photo_likes GROUP BY photo_id"
    ).fetchall():
        payload[row["photo_id"]] = {
            "likes": row["count"],
            "liked": row["photo_id"] in liked_photo_ids,
            "comments": [],
            "comment_count": 0,
            "admin_authenticated": viewer_is_admin,
        }

    comment_rows = fetch_comment_rows(conn, viewer_ip, viewer_is_admin)
    grouped = {}
    for row in comment_rows:
        grouped.setdefault(row["photo_id"], []).append(row)

    for photo_id, rows in grouped.items():
        entry = payload.setdefault(
            photo_id,
            {
                "likes": 0,
                "liked": photo_id in liked_photo_ids,
                "comments": [],
                "comment_count": 0,
                "admin_authenticated": viewer_is_admin,
            },
        )
        comments_payload = shape_photo_comments(rows)
        entry["comments"] = comments_payload["comments"]
        entry["comment_count"] = comments_payload["comment_count"]

    return payload


def collect_descendant_ids(conn, root_id):
    pending = [root_id]
    descendants = []
    while pending:
        current_id = pending.pop()
        children = conn.execute(
            "SELECT id FROM photo_comments WHERE parent_id = ?",
            (current_id,),
        ).fetchall()
        child_ids = [row["id"] for row in children]
        descendants.extend(child_ids)
        pending.extend(child_ids)
    return descendants


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200, extra_headers=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        if extra_headers:
            for header_name, header_value in extra_headers:
                self.send_header(header_name, header_value)
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send_json({}, 204)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/map-tile/"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "map-tile" and parts[4].endswith(".png"):
                z = parts[2]
                x = parts[3]
                y = parts[4][:-4]
            elif len(parts) == 5 and parts[0] == "api" and parts[1] == "map-tile":
                z = parts[2]
                x = parts[3]
                y = parts[4]
            else:
                self.send_error(404)
                return
            tile_url = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
            try:
                request = Request(tile_url, headers={"User-Agent": "simond.photo-map-proxy/1.0"})
                with urlopen(request, timeout=8) as response:
                    body = response.read()
                    content_type = response.headers.get("Content-Type", "image/png")
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(body)
            except Exception:
                self.send_error(502)
            return

        if parsed.path == "/api/client-context":
            conn = get_db()
            try:
                ip = normalize_ip(self)
                location_label = get_location_label(conn, ip)
                self._send_json(
                    {
                        "location_label": location_label,
                        "is_mainland_china": is_mainland_china_label(location_label),
                    }
                )
            finally:
                conn.close()
            return

        if parsed.path == "/api/collections-map":
            self._send_json(discover_collection_pages())
            return

        if parsed.path == "/api/engagement":
            conn = get_db()
            try:
                ip = normalize_ip(self)
                viewer_is_admin = is_admin_authenticated(self)
                qs = parse_qs(parsed.query)
                photo_id = qs.get("photo_id", [""])[0].strip()
                if not photo_id:
                    self._send_json(photo_payloads(conn, ip, viewer_is_admin))
                    return
                self._send_json(photo_payload(conn, photo_id, ip, viewer_is_admin))
            finally:
                conn.close()
            return

        if parsed.path == "/api/admin/status":
            self._send_json({"authenticated": is_admin_authenticated(self), "display_name": ADMIN_NAME})
            return

        if parsed.path == "/api/admin/likes":
            if not is_admin_authenticated(self):
                self._send_json({"error": "Forbidden"}, 403)
                return
            conn = get_db()
            try:
                qs = parse_qs(parsed.query)
                photo_id = qs.get("photo_id", [""])[0].strip()
                if not photo_id:
                    self._send_json({"error": "Missing photo_id"}, 400)
                    return
                self._send_json(fetch_like_insights(conn, photo_id))
            finally:
                conn.close()
            return

        if parsed.path == "/api/admin/stats":
            if not is_admin_authenticated(self):
                self._send_json({"error": "Forbidden"}, 403)
                return
            conn = get_db()
            try:
                self._send_json(fetch_admin_stats(conn))
            finally:
                conn.close()
            return

        if parsed.path == "/api/admin/server-status":
            if not is_admin_authenticated(self):
                self._send_json({"error": "Forbidden"}, 403)
                return
            self._send_json(fetch_server_status())
            return

        if parsed.path == "/api/admin/gemini-guest-pool":
            if not is_admin_authenticated(self):
                self._send_json({"error": "Forbidden"}, 403)
                return
            try:
                self._send_json(fetch_gemini_guest_pool())
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)
            return

        if parsed.path == "/api/admin/gemini-users":
            if not is_admin_authenticated(self):
                self._send_json({"error": "Forbidden"}, 403)
                return
            try:
                self._send_json(fetch_gemini_user_accounts())
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)
            return

        self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON"}, 400)
            return

        if parsed.path == "/api/admin/login":
            password = str(data.get("password", ""))
            if not verify_admin_password(password):
                self._send_json({"error": "Invalid password"}, 403)
                return
            self._send_json(
                {"authenticated": True, "display_name": ADMIN_NAME},
                extra_headers=[("Set-Cookie", make_admin_session_cookie())],
            )
            return

        if parsed.path == "/api/admin/logout":
            self._send_json(
                {"authenticated": False},
                extra_headers=[("Set-Cookie", clear_admin_session_cookie())],
            )
            return

        conn = get_db()
        ip = normalize_ip(self)
        viewer_is_admin = is_admin_authenticated(self)
        now = utc_now()
        try:
            if parsed.path == "/api/photo-view":
                photo_id = str(data.get("photo_id", "")).strip()
                if not photo_id:
                    self._send_json({"error": "Missing photo_id"}, 400)
                    return
                conn.execute(
                    "INSERT INTO photo_view_events (photo_id, ip_address, viewed_at) VALUES (?, ?, ?)",
                    (photo_id, ip, now),
                )
                conn.commit()
                self._send_json({"ok": True})
                return

            if parsed.path == "/api/admin/action":
                if not viewer_is_admin:
                    self._send_json({"error": "Forbidden"}, 403)
                    return
                action = str(data.get("action", "")).strip()
                if not action:
                    self._send_json({"error": "Missing action"}, 400)
                    return
                result = run_admin_action(action)
                log_admin_action(conn, action, "ok" if result.get("ok") else "error", result.get("detail", ""))
                status = 200 if result.get("ok") else 400
                self._send_json(result, status)
                return

            if parsed.path == "/api/admin/gemini-guest-action":
                if not viewer_is_admin:
                    self._send_json({"error": "Forbidden"}, 403)
                    return
                action = str(data.get("action", "")).strip()
                email = str(data.get("email", "")).strip()
                if not action:
                    self._send_json({"error": "Missing action"}, 400)
                    return
                try:
                    result = run_gemini_guest_action(action, email)
                except Exception as exc:
                    result = {"ok": False, "detail": str(exc)}
                log_admin_action(
                    conn,
                    f"gemini_guest_{action}",
                    "ok" if result.get("ok") else "error",
                    result.get("detail", ""),
                )
                status = 200 if result.get("ok") else 400
                self._send_json(result, status)
                return

            if parsed.path == "/api/like":
                photo_id = str(data.get("photo_id", "")).strip()
                if not photo_id:
                    self._send_json({"error": "Missing photo_id"}, 400)
                    return
                existing = conn.execute(
                    "SELECT 1 FROM photo_likes WHERE photo_id = ? AND ip_address = ?",
                    (photo_id, ip),
                ).fetchone()
                if existing:
                    conn.execute(
                        "DELETE FROM photo_likes WHERE photo_id = ? AND ip_address = ?",
                        (photo_id, ip),
                    )
                    liked = False
                else:
                    conn.execute(
                        "INSERT INTO photo_likes (photo_id, ip_address, created_at) VALUES (?, ?, ?)",
                        (photo_id, ip, now),
                    )
                    get_location_label(conn, ip)
                    liked = True
                conn.commit()
                payload = photo_payload(conn, photo_id, ip, viewer_is_admin)
                payload["liked"] = liked
                self._send_json(payload)
                return

            if parsed.path == "/api/comment":
                photo_id = str(data.get("photo_id", "")).strip()
                author = str(data.get("author", "")).strip()[:40]
                body = str(data.get("body", "")).strip()[:500]
                parent_id = int(data.get("parent_id", 0) or 0) or None
                if viewer_is_admin:
                    author = ADMIN_NAME
                if not photo_id or not author or not body:
                    self._send_json({"error": "Missing fields"}, 400)
                    return
                if parent_id is not None:
                    parent = conn.execute(
                        "SELECT id FROM photo_comments WHERE id = ? AND photo_id = ?",
                        (parent_id, photo_id),
                    ).fetchone()
                    if not parent:
                        self._send_json({"error": "Parent comment not found"}, 400)
                        return
                conn.execute(
                    """
                    INSERT INTO photo_comments (
                        photo_id, parent_id, author, body, is_owner, ip_address, masked_ip, location_label, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        photo_id,
                        parent_id,
                        author,
                        body,
                        1 if viewer_is_admin else 0,
                        ip,
                        mask_ip(ip),
                        get_location_label(conn, ip),
                        now,
                    ),
                )
                conn.commit()
                self._send_json(photo_payload(conn, photo_id, ip, viewer_is_admin))
                return

            if parsed.path == "/api/comment/like":
                comment_id = int(data.get("comment_id", 0) or 0)
                if not comment_id:
                    self._send_json({"error": "Missing comment_id"}, 400)
                    return
                row = conn.execute(
                    "SELECT photo_id FROM photo_comments WHERE id = ?",
                    (comment_id,),
                ).fetchone()
                if not row:
                    self._send_json({"error": "Comment not found"}, 404)
                    return
                existing = conn.execute(
                    "SELECT 1 FROM comment_likes WHERE comment_id = ? AND ip_address = ?",
                    (comment_id, ip),
                ).fetchone()
                if existing:
                    conn.execute(
                        "DELETE FROM comment_likes WHERE comment_id = ? AND ip_address = ?",
                        (comment_id, ip),
                    )
                else:
                    conn.execute(
                        "INSERT INTO comment_likes (comment_id, ip_address, created_at) VALUES (?, ?, ?)",
                        (comment_id, ip, now),
                    )
                conn.commit()
                self._send_json(photo_payload(conn, row["photo_id"], ip, viewer_is_admin))
                return

            if parsed.path == "/api/comment/pin":
                comment_id = int(data.get("comment_id", 0) or 0)
                pinned = 1 if data.get("pinned") else 0
                if not viewer_is_admin or not comment_id:
                    self._send_json({"error": "Forbidden"}, 403)
                    return
                row = conn.execute(
                    "SELECT photo_id FROM photo_comments WHERE id = ?",
                    (comment_id,),
                ).fetchone()
                if not row:
                    self._send_json({"error": "Comment not found"}, 404)
                    return
                conn.execute(
                    "UPDATE photo_comments SET is_pinned = ? WHERE id = ?",
                    (pinned, comment_id),
                )
                conn.commit()
                self._send_json(photo_payload(conn, row["photo_id"], ip, viewer_is_admin))
                return

            if parsed.path == "/api/comment/update":
                photo_id = str(data.get("photo_id", "")).strip()
                author = str(data.get("author", "")).strip()[:40]
                body = str(data.get("body", "")).strip()[:500]
                comment_id = int(data.get("comment_id", 0) or 0)
                if viewer_is_admin:
                    author = ADMIN_NAME
                if not photo_id or not author or not body or not comment_id:
                    self._send_json({"error": "Missing fields"}, 400)
                    return
                row = conn.execute(
                    """
                    SELECT id FROM photo_comments
                    WHERE id = ? AND photo_id = ? AND (ip_address = ? OR (is_owner = 1 AND ? = 1))
                    """,
                    (comment_id, photo_id, ip, 1 if viewer_is_admin else 0),
                ).fetchone()
                if not row:
                    self._send_json({"error": "Forbidden"}, 403)
                    return
                conn.execute(
                    "UPDATE photo_comments SET author = ?, body = ? WHERE id = ?",
                    (author, body, comment_id),
                )
                conn.commit()
                self._send_json(photo_payload(conn, photo_id, ip, viewer_is_admin))
                return

            if parsed.path == "/api/comment/delete":
                comment_id = int(data.get("comment_id", 0) or 0)
                if not comment_id:
                    self._send_json({"error": "Missing comment_id"}, 400)
                    return
                row = conn.execute(
                    """
                    SELECT photo_id, parent_id FROM photo_comments
                    WHERE id = ? AND (ip_address = ? OR ? = 1)
                    """,
                    (comment_id, ip, 1 if viewer_is_admin else 0),
                ).fetchone()
                if not row:
                    self._send_json({"error": "Forbidden"}, 403)
                    return
                photo_id = row["photo_id"]
                parent_id = row["parent_id"]
                if parent_id is None:
                    descendant_ids = collect_descendant_ids(conn, comment_id)
                    placeholders = ", ".join(["?"] * (len(descendant_ids) + 1))
                    ids_to_delete = [comment_id] + descendant_ids
                    conn.execute(
                        f"DELETE FROM comment_likes WHERE comment_id IN ({placeholders})",
                        ids_to_delete,
                    )
                    conn.execute(
                        f"DELETE FROM photo_comments WHERE id IN ({placeholders})",
                        ids_to_delete,
                    )
                else:
                    conn.execute(
                        "DELETE FROM comment_likes WHERE comment_id = ?",
                        (comment_id,),
                    )
                    conn.execute(
                        "DELETE FROM photo_comments WHERE id = ?",
                        (comment_id,),
                    )
                conn.commit()
                self._send_json(photo_payload(conn, photo_id, ip, viewer_is_admin))
                return

            self._send_json({"error": "Not found"}, 404)
        finally:
            conn.close()


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 9000), Handler)
    server.serve_forever()
