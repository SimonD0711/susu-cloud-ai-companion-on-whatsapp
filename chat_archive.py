import json
from datetime import datetime


def _clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


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
        "quoted_message_id": _clean_text(context.get("id") or context.get("message_id")),
        "quoted_from": _clean_text(context.get("from")),
    }


def source_day_from_created_at(created_at, hk_tz):
    try:
        dt = datetime.fromisoformat(_clean_text(created_at))
        return dt.astimezone(hk_tz).strftime("%Y-%m-%d")
    except Exception:
        return ""


def ensure_archive_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wa_message_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wa_id TEXT NOT NULL,
            message_id TEXT NOT NULL DEFAULT '',
            direction TEXT NOT NULL,
            message_type TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            raw_json TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            source_day TEXT NOT NULL DEFAULT '',
            media_id TEXT NOT NULL DEFAULT '',
            mime_type TEXT NOT NULL DEFAULT '',
            quoted_message_id TEXT NOT NULL DEFAULT '',
            quoted_from TEXT NOT NULL DEFAULT '',
            quoted_preview TEXT NOT NULL DEFAULT '',
            quoted_body TEXT NOT NULL DEFAULT '',
            resolved_quoted_local_id INTEGER NOT NULL DEFAULT 0,
            thread_key TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wa_message_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wa_id TEXT NOT NULL,
            message_id TEXT NOT NULL DEFAULT '',
            quoted_message_id TEXT NOT NULL DEFAULT '',
            resolved_local_id INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'unresolved',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_wa_message_archive_message_id
        ON wa_message_archive (wa_id, message_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_wa_message_archive_created_at
        ON wa_message_archive (wa_id, created_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_wa_message_archive_source_day
        ON wa_message_archive (wa_id, source_day, created_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_wa_message_archive_quoted
        ON wa_message_archive (wa_id, quoted_message_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_wa_message_links_lookup
        ON wa_message_links (wa_id, quoted_message_id, status, updated_at DESC)
        """
    )


def archive_message(conn, hk_tz, *, wa_id, direction, message_id, message_type, body, raw_json, created_at, media_id="", mime_type=""):
    context = parse_message_context(raw_json)
    source_day = source_day_from_created_at(created_at, hk_tz)
    resolved_local_id = 0
    quoted_body = ""
    quoted_preview = ""
    quoted_message_id = context["quoted_message_id"]
    if quoted_message_id:
        row = conn.execute(
            "SELECT id, body FROM wa_message_archive WHERE wa_id = ? AND message_id = ? LIMIT 1",
            (wa_id, quoted_message_id),
        ).fetchone()
        if row:
            resolved_local_id = int(row["id"] or 0)
            quoted_body = _clean_text(row["body"])
            quoted_preview = quoted_body[:80]
    conn.execute(
        """
        INSERT INTO wa_message_archive (
            wa_id, message_id, direction, message_type, body, raw_json, created_at,
            source_day, media_id, mime_type, quoted_message_id, quoted_from,
            quoted_preview, quoted_body, resolved_quoted_local_id, thread_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
        ON CONFLICT(wa_id, message_id) DO UPDATE SET
            body=excluded.body,
            raw_json=excluded.raw_json,
            message_type=excluded.message_type,
            source_day=excluded.source_day,
            media_id=excluded.media_id,
            mime_type=excluded.mime_type,
            quoted_message_id=excluded.quoted_message_id,
            quoted_from=excluded.quoted_from,
            quoted_preview=excluded.quoted_preview,
            quoted_body=excluded.quoted_body,
            resolved_quoted_local_id=excluded.resolved_quoted_local_id
        """,
        (
            wa_id,
            _clean_text(message_id),
            direction,
            _clean_text(message_type),
            _clean_text(body),
            _clean_text(raw_json),
            _clean_text(created_at),
            source_day,
            _clean_text(media_id),
            _clean_text(mime_type),
            quoted_message_id,
            context["quoted_from"],
            quoted_preview,
            quoted_body,
            resolved_local_id,
        ),
    )
    if quoted_message_id:
        status = "resolved" if resolved_local_id else "unresolved"
        conn.execute(
            """
            INSERT INTO wa_message_links (wa_id, message_id, quoted_message_id, resolved_local_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (wa_id, _clean_text(message_id), quoted_message_id, resolved_local_id, status, _clean_text(created_at), _clean_text(created_at)),
        )


def backfill_message_archive_rows(conn, hk_tz, limit=500):
    rows = conn.execute(
        """
        SELECT m.wa_id, m.direction, m.message_id, m.message_type, m.body, m.raw_json, m.created_at
        FROM wa_messages m
        LEFT JOIN wa_message_archive a ON a.wa_id = m.wa_id AND a.message_id = m.message_id
        WHERE a.id IS NULL
        ORDER BY m.id ASC
        LIMIT ?
        """,
        (max(1, int(limit)),),
    ).fetchall()
    for row in rows:
        archive_message(
            conn,
            hk_tz,
            wa_id=row["wa_id"],
            direction=row["direction"],
            message_id=row["message_id"],
            message_type=row["message_type"],
            body=row["body"],
            raw_json=row["raw_json"],
            created_at=row["created_at"],
        )


def reconcile_message_archive_links(conn, hk_tz, limit=300):
    rows = conn.execute(
        """
        SELECT id, wa_id, message_id, quoted_message_id
        FROM wa_message_archive
        WHERE quoted_message_id != '' AND resolved_quoted_local_id = 0
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (max(1, int(limit)),),
    ).fetchall()
    for row in rows:
        target = conn.execute(
            "SELECT id, body FROM wa_message_archive WHERE wa_id = ? AND message_id = ? LIMIT 1",
            (row["wa_id"], row["quoted_message_id"]),
        ).fetchone()
        if not target:
            continue
        quoted_body = _clean_text(target["body"])
        conn.execute(
            "UPDATE wa_message_archive SET resolved_quoted_local_id = ?, quoted_body = ?, quoted_preview = ? WHERE id = ?",
            (int(target["id"] or 0), quoted_body, quoted_body[:80], int(row["id"])),
        )
        conn.execute(
            "UPDATE wa_message_links SET resolved_local_id = ?, status = 'resolved', updated_at = (SELECT created_at FROM wa_message_archive WHERE id = ?) WHERE wa_id = ? AND message_id = ? AND quoted_message_id = ?",
            (int(target["id"] or 0), int(row["id"]), row["wa_id"], row["message_id"], row["quoted_message_id"]),
        )


def load_archive_messages_by_date(conn, wa_id, date_str, limit=80, direction="inbound"):
    if direction:
        rows = conn.execute(
            "SELECT * FROM wa_message_archive WHERE wa_id = ? AND source_day = ? AND direction = ? ORDER BY created_at ASC, id ASC LIMIT ?",
            (wa_id, _clean_text(date_str), direction, max(1, int(limit))),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM wa_message_archive WHERE wa_id = ? AND source_day = ? ORDER BY created_at ASC, id ASC LIMIT ?",
            (wa_id, _clean_text(date_str), max(1, int(limit))),
        ).fetchall()
    return [dict(row) for row in rows]
