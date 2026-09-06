"""
memory.py — Chunked, low-storage memory system for Jarvis.

Concept: like Minecraft chunk loading.
  - "Active chunk"   = the last N turns, always loaded into context (what's "rendered")
  - "Unloaded chunks" = older turns sitting on disk, untouched, until searched for
  - "Loading a chunk" = an FTS5 keyword search pulls in only the relevant old turns

Storage: a single SQLite file. Rows are small (role + text + timestamp),
so months of daily use typically stay in the low single-digit MB range,
and old chunks can be summarized/pruned to keep it flat over time.
"""

import sqlite3
import re
import time
from pathlib import Path

DB_PATH = Path.home() / ".jarvis" / "memory.db"


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Create tables if they don't exist. Safe to call every startup."""
    conn = _connect()
    cur = conn.cursor()

    # Raw message log — the "world data"
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            day TEXT NOT NULL,        -- YYYY-MM-DD, acts as the "chunk id"
            role TEXT NOT NULL,       -- 'user' or 'assistant'
            content TEXT NOT NULL
        )
    """)

    # FTS5 index for fast keyword search over old chunks without loading them all
    cur.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
            content, content='messages', content_rowid='id'
        )
    """)

    # Keep FTS in sync automatically
    cur.execute("""
        CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
            INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
        END;
    """)

    # Compact digests of pruned/old chunks — keeps long-term storage flat
    cur.execute("""
        CREATE TABLE IF NOT EXISTS digests (
            day TEXT PRIMARY KEY,
            summary TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def add_message(role: str, content: str):
    conn = _connect()
    day = time.strftime("%Y-%m-%d")
    conn.execute(
        "INSERT INTO messages (ts, day, role, content) VALUES (?, ?, ?, ?)",
        (time.time(), day, role, content),
    )
    conn.commit()
    conn.close()


def get_active_chunk(n: int = 20):
    """The 'always loaded' recent turns — like the chunk you're standing in."""
    conn = _connect()
    rows = conn.execute(
        "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (n,)
    ).fetchall()
    conn.close()
    return list(reversed(rows))  # chronological order


def _sanitize_fts_query(query: str) -> str:
    """
    FTS5 treats characters like ! " : * ( ) - as query syntax, so a plain
    sentence with punctuation (e.g. containing "!") can raise a syntax
    error instead of just searching. Strip to alphanumeric words and
    quote each one as a literal token, which is always safe to pass to MATCH.

    Joined with OR (not FTS5's default AND) since recall should surface a
    chunk that matches ANY relevant word from the question, not require
    every word in the question to appear verbatim in the old message.
    Short filler words are dropped so they don't drown out real keywords.
    """
    stopwords = {
        "a", "an", "the", "is", "was", "are", "were", "do", "did", "does",
        "i", "you", "my", "your", "me", "what", "when", "where", "who",
        "say", "said", "about", "did", "to", "of", "in", "on", "for", "it",
    }
    words = [w for w in re.findall(r"[A-Za-z0-9]+", query.lower()) if w not in stopwords]
    if not words:
        return ""
    return " OR ".join(f'"{w}"' for w in words)


def search_old_chunks(query: str, limit: int = 5):
    """
    On-demand chunk loading: keyword search across ALL history without
    ever pulling the full log into memory. Only matching rows come back.
    """
    safe_query = _sanitize_fts_query(query)
    if not safe_query:
        return []

    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT m.day, m.role, m.content
            FROM messages_fts f
            JOIN messages m ON m.id = f.rowid
            WHERE messages_fts MATCH ?
            ORDER BY m.id DESC
            LIMIT ?
            """,
            (safe_query, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        # Belt-and-suspenders: never let a search glitch crash the whole app
        rows = []
    finally:
        conn.close()
    return rows


def get_digest(day: str):
    conn = _connect()
    row = conn.execute("SELECT summary FROM digests WHERE day = ?", (day,)).fetchone()
    conn.close()
    return row[0] if row else None


def save_digest(day: str, summary: str):
    conn = _connect()
    conn.execute(
        "INSERT OR REPLACE INTO digests (day, summary) VALUES (?, ?)", (day, summary)
    )
    conn.commit()
    conn.close()


def prune_day(day: str):
    """
    Collapse a day's raw messages into its saved digest and delete the raw rows.
    Call this on old days to keep the DB size flat over months of use.
    Requires save_digest(day, ...) to have been called first.
    """
    if get_digest(day) is None:
        raise ValueError(f"No digest saved for {day} — save one before pruning.")
    conn = _connect()
    conn.execute("DELETE FROM messages WHERE day = ?", (day,))
    conn.commit()
    conn.close()


def db_size_kb() -> float:
    return DB_PATH.stat().st_size / 1024 if DB_PATH.exists() else 0.0
