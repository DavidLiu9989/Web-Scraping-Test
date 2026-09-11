"""Export the article database in LLM-friendly formats.

Two formats:
  - JSONL: one clean JSON object per line, for programmatic use / RAG ingestion.
  - Markdown corpus: grouped by country then topic, with a metadata header per
    item, designed to be pasted or attached directly into an LLM conversation
    alongside a user's own policy documents.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .db import Database, utcnow

EXPORT_FIELDS = [
    "url", "title", "source", "published_at", "first_seen_at",
    "countries", "topics", "doc_type", "relevance_score", "snippet",
]


def export_jsonl(db: Database, path: str | Path, include_content: bool = True) -> int:
    """Write all relevant articles to JSONL. Returns count."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    articles = db.relevant_articles()
    with open(path, "w", encoding="utf-8") as f:
        for art in articles:
            record = {k: art.get(k) for k in EXPORT_FIELDS}
            if include_content and art.get("content"):
                record["content"] = art["content"]
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(articles)


def export_markdown(db: Database, path: str | Path) -> int:
    """Write a country/topic-grouped markdown corpus. Returns article count."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    articles = db.relevant_articles()

    by_country: dict[str, list[dict]] = defaultdict(list)
    for art in articles:
        countries = art["countries"] or ["Unattributed"]
        for c in countries:
            by_country[c].append(art)

    lines = [
        "# Data Center & Cloud Services Regulatory Corpus",
        "",
        f"Generated: {utcnow()}  ",
        f"Articles: {len(articles)}  ",
        "Scope: regulatory requirements for security & resilience and "
        "sustainability of data centers and cloud services, worldwide.",
        "",
        "Each item carries structured metadata (jurisdiction, topics, document "
        "stage, date, source) so an LLM can compare this corpus against other "
        "policy documents.",
        "",
    ]

    for country in sorted(by_country):
        items = by_country[country]
        lines.append(f"## {country} ({len(items)} items)")
        lines.append("")
        for art in items:
            lines.append(f"### {art['title']}")
            lines.append("")
            lines.append(f"- **Jurisdictions:** {', '.join(art['countries']) or 'unattributed'}")
            lines.append(f"- **Topics:** {', '.join(art['topics']) or 'general'}")
            lines.append(f"- **Document stage:** {art['doc_type']}")
            lines.append(f"- **Published:** {art['published_at'] or 'unknown'}")
            lines.append(f"- **Source:** {art['source']} — {art['url']}")
            lines.append("")
            if art.get("snippet"):
                lines.append(art["snippet"])
                lines.append("")
            if art.get("content"):
                lines.append("<details><summary>Full text</summary>")
                lines.append("")
                lines.append(art["content"])
                lines.append("")
                lines.append("</details>")
                lines.append("")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return len(articles)
