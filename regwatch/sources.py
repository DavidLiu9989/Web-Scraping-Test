"""Load the source configuration and expand it into concrete feed URLs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "sources.yaml"


@dataclass
class Feed:
    url: str
    label: str
    kind: str  # "google-news" | "rss"


@dataclass
class SourceConfig:
    feeds: list[Feed]
    relevance_threshold: float
    max_age_days: int


def load_config(path: str | Path | None = None) -> SourceConfig:
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    with open(cfg_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    feeds: list[Feed] = []

    locales = raw.get("google_news_locales") or [
        {"hl": "en-US", "gl": "US", "ceid": "US:en"}
    ]
    for entry in raw.get("google_news_queries") or []:
        query = entry["query"]
        label = entry.get("label") or query[:40]
        for loc in locales:
            url = (
                "https://news.google.com/rss/search?"
                f"q={quote_plus(query + ' when:30d')}"
                f"&hl={loc['hl']}&gl={loc['gl']}&ceid={quote_plus(loc['ceid'])}"
            )
            feeds.append(Feed(url=url, label=f"{label} [{loc['gl']}]", kind="google-news"))

    for entry in raw.get("international_queries") or []:
        query = entry["query"]
        label = entry.get("label") or query[:40]
        url = (
            "https://news.google.com/rss/search?"
            f"q={quote_plus(query + ' when:30d')}"
            f"&hl={entry['hl']}&gl={entry['gl']}&ceid={quote_plus(entry['ceid'])}"
        )
        feeds.append(
            Feed(url=url, label=f"{label} [{entry['gl']}/{entry['hl']}]",
                 kind="google-news")
        )

    for entry in raw.get("rss_feeds") or []:
        feeds.append(
            Feed(url=entry["url"], label=entry.get("label") or entry["url"], kind="rss")
        )

    return SourceConfig(
        feeds=feeds,
        relevance_threshold=float(raw.get("relevance_threshold", 3.0)),
        max_age_days=int(raw.get("max_age_days", 45)),
    )
