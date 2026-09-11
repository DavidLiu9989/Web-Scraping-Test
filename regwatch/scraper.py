"""Fetch feeds, extract article text, classify, and store new items."""

from __future__ import annotations

import base64
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

from .classify import classify, normalize_title
from .db import Database
from .sources import Feed, SourceConfig

log = logging.getLogger("regwatch.scraper")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 regwatch/0.1"
)
FETCH_TIMEOUT = 20
FEED_DELAY_SECONDS = 1.0  # politeness delay between feed fetches


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def _parse_date(entry) -> str | None:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", parsed)
    return None


def _decode_google_news_url(url: str) -> str | None:
    """Best-effort decode of a news.google.com/rss/articles/<id> link.

    Older article ids are base64-encoded protobufs that embed the target URL
    in plain sight; newer ("AU_yqL...") ids are not decodable offline.
    """
    m = re.search(r"/articles/([^?/]+)", url)
    if not m:
        return None
    token = m.group(1)
    if token.startswith("AU_yqL"):
        return None
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded)
        urls = re.findall(rb"https?://[^\x00-\x20\x7f-\xff]+", raw)
        for u in urls:
            decoded = u.decode("utf-8", errors="ignore")
            if "google.com" not in decoded:
                return decoded
    except Exception:
        return None
    return None


def _extract_text(html: str) -> str:
    """Pull readable article text out of an HTML page."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    container = soup.find("article") or soup.find("main") or soup.body or soup
    paragraphs = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    text = "\n".join(p for p in paragraphs if len(p) > 60)
    return text[:20000]


def _clean_snippet(summary_html: str) -> str:
    text = BeautifulSoup(summary_html or "", "html.parser").get_text(" ", strip=True)
    return text[:1000]


class Scraper:
    def __init__(self, db: Database, config: SourceConfig, fetch_content: bool = True):
        self.db = db
        self.config = config
        self.fetch_content = fetch_content
        self.http = _session()

    def run(self) -> dict:
        """Scrape all feeds once. Returns stats for reporting."""
        run_id = self.db.start_run()
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.config.max_age_days)
        seen = 0
        new = 0
        new_relevant = 0

        for feed in self.config.feeds:
            entries = self._fetch_feed(feed)
            log.info("feed %-45s %d entries", feed.label, len(entries))
            for entry in entries:
                seen += 1
                stored = self._process_entry(entry, feed, run_id, cutoff)
                if stored is not None:
                    new += 1
                    if stored:
                        new_relevant += 1
            time.sleep(FEED_DELAY_SECONDS)

        self.db.finish_run(run_id, seen, new)
        return {
            "run_id": run_id,
            "entries_seen": seen,
            "new_articles": new,
            "new_relevant": new_relevant,
        }

    def _fetch_feed(self, feed: Feed) -> list:
        try:
            resp = self.http.get(feed.url, timeout=FETCH_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            log.warning("feed %s failed: %s", feed.label, e)
            return []
        parsed = feedparser.parse(resp.content)
        return list(parsed.entries)

    def _process_entry(self, entry, feed: Feed, run_id: int, cutoff) -> bool | None:
        """Store one feed entry if new. Returns None if skipped/duplicate,
        else whether the stored article was relevant."""
        url = getattr(entry, "link", None)
        title = (getattr(entry, "title", "") or "").strip()
        if not url or not title:
            return None

        # Google News titles end with " - Source Name"; split it off.
        source = None
        if feed.kind == "google-news":
            src = getattr(entry, "source", None)
            source = getattr(src, "title", None) if src else None
            if source is None and " - " in title:
                title, source = title.rsplit(" - ", 1)
            decoded = _decode_google_news_url(url)
            if decoded:
                url = decoded
        if not source:
            source = urlparse(url).netloc

        published_at = _parse_date(entry)
        if published_at:
            pub_dt = datetime.strptime(published_at, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            if pub_dt < cutoff:
                return None

        norm = normalize_title(title)
        if self.db.has_url(url) or self.db.has_similar_title(norm):
            return None

        snippet = _clean_snippet(getattr(entry, "summary", ""))
        result = classify(title, snippet)
        relevant_so_far = result["relevance_score"] >= self.config.relevance_threshold

        # Only spend a page fetch on items that already look relevant.
        content = ""
        final_url = url
        if self.fetch_content and relevant_so_far and "news.google.com" not in url:
            final_url, content = self._fetch_article(url)
            if content:
                result = classify(title, snippet, content)

        relevant = result["relevance_score"] >= self.config.relevance_threshold
        self.db.insert_article(
            {
                "url": final_url if not self.db.has_url(final_url) else url,
                "title": title,
                "normalized_title": norm,
                "source": source,
                "source_feed": feed.label,
                "published_at": published_at,
                "first_seen_run": run_id,
                "countries": result["countries"],
                "topics": result["topics"],
                "doc_type": result["doc_type"],
                "relevance_score": result["relevance_score"],
                "relevant": relevant,
                "snippet": snippet,
                "content": content,
            }
        )
        return relevant

    def _fetch_article(self, url: str) -> tuple[str, str]:
        try:
            resp = self.http.get(url, timeout=FETCH_TIMEOUT, allow_redirects=True)
            resp.raise_for_status()
            if "text/html" not in resp.headers.get("Content-Type", "text/html"):
                return resp.url, ""
            return resp.url, _extract_text(resp.text)
        except requests.RequestException as e:
            log.debug("article fetch failed %s: %s", url, e)
            return url, ""
