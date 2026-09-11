"""SQLite storage for scraped articles and scrape runs."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    articles_seen INTEGER DEFAULT 0,
    articles_new INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    source TEXT,
    source_feed TEXT,
    published_at TEXT,
    first_seen_at TEXT NOT NULL,
    first_seen_run INTEGER NOT NULL REFERENCES runs(id),
    countries TEXT NOT NULL DEFAULT '[]',   -- JSON list
    topics TEXT NOT NULL DEFAULT '[]',      -- JSON list
    doc_type TEXT,                          -- consultation | draft | enacted | guidance | news
    relevance_score REAL NOT NULL DEFAULT 0,
    relevant INTEGER NOT NULL DEFAULT 0,
    snippet TEXT,
    content TEXT
);

CREATE INDEX IF NOT EXISTS idx_articles_run ON articles(first_seen_run);
CREATE INDEX IF NOT EXISTS idx_articles_norm_title ON articles(normalized_title);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Database:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # -- runs -------------------------------------------------------------

    def start_run(self) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (started_at) VALUES (?)", (utcnow(),)
        )
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, seen: int, new: int) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, articles_seen = ?, articles_new = ? WHERE id = ?",
            (utcnow(), seen, new, run_id),
        )
        self.conn.commit()

    def latest_finished_run(self) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def previous_finished_run(self, before_run_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM runs WHERE finished_at IS NOT NULL AND id < ? ORDER BY id DESC LIMIT 1",
            (before_run_id,),
        ).fetchone()

    # -- articles ---------------------------------------------------------

    def has_url(self, url: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM articles WHERE url = ?", (url,)
        ).fetchone()
        return row is not None

    def has_similar_title(self, normalized_title: str) -> bool:
        if not normalized_title:
            return False
        row = self.conn.execute(
            "SELECT 1 FROM articles WHERE normalized_title = ?", (normalized_title,)
        ).fetchone()
        return row is not None

    def insert_article(self, art: dict) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO articles (
                url, title, normalized_title, source, source_feed, published_at,
                first_seen_at, first_seen_run, countries, topics, doc_type,
                relevance_score, relevant, snippet, content
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                art["url"],
                art["title"],
                art["normalized_title"],
                art.get("source"),
                art.get("source_feed"),
                art.get("published_at"),
                utcnow(),
                art["first_seen_run"],
                json.dumps(art.get("countries", [])),
                json.dumps(art.get("topics", [])),
                art.get("doc_type"),
                art.get("relevance_score", 0),
                1 if art.get("relevant") else 0,
                art.get("snippet"),
                art.get("content"),
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def relevant_articles(self, since_run: int | None = None) -> list[dict]:
        """Relevant articles, optionally only those first seen after run `since_run`."""
        sql = "SELECT * FROM articles WHERE relevant = 1"
        params: tuple = ()
        if since_run is not None:
            sql += " AND first_seen_run > ?"
            params = (since_run,)
        sql += " ORDER BY published_at DESC"
        return [self._to_dict(r) for r in self.conn.execute(sql, params)]

    def articles_in_run(self, run_id: int, relevant_only: bool = True) -> list[dict]:
        sql = "SELECT * FROM articles WHERE first_seen_run = ?"
        if relevant_only:
            sql += " AND relevant = 1"
        sql += " ORDER BY relevance_score DESC"
        return [self._to_dict(r) for r in self.conn.execute(sql, (run_id,))]

    @staticmethod
    def _to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["countries"] = json.loads(d.get("countries") or "[]")
        d["topics"] = json.loads(d.get("topics") or "[]")
        return d
