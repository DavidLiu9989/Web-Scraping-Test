"""Translate non-English articles to English via the Claude API.

Non-English items (e.g. Spanish coverage of a Real Decreto) are stored in
their original language first — the multilingual keyword lists in classify.py
get them past the relevance gate. This module then batch-translates the
relevant ones to English, keeps the original title/snippet alongside, and
re-classifies each item on the translated text (topic tagging is richer in
English). If translation fails or no credentials are available, items simply
stay in their original language, marked untranslated — they are never dropped.
"""

from __future__ import annotations

import json
import logging
import re

import anthropic

from .classify import classify
from .db import Database

log = logging.getLogger("regwatch.translate")

MODEL = "claude-opus-5"
BATCH_SIZE = 20

SYSTEM_PROMPT = """You are a professional translator specializing in legal and
regulatory news about digital infrastructure (data centers, cloud services).

You receive a JSON array of news items with fields: id, language, title,
snippet. Translate each title and snippet into English, faithfully and
completely. Keep official instrument names in the original language followed
by an English gloss in parentheses, e.g. "Real Decreto 123/2026 (Royal Decree
on data center energy efficiency)". Do not add commentary, do not summarize,
do not editorialize.

Return ONLY a JSON array (no markdown fences, no prose), one object per input
item: {"id": <same id>, "title_en": "...", "snippet_en": "..."}."""


def translate_pending(db: Database) -> int:
    """Translate all pending non-English articles. Returns count applied."""
    items = db.pending_translations()
    if not items:
        return 0
    log.info("translating %d non-English items", len(items))
    translations = translate_batch(items)
    applied = 0
    for art in items:
        tr = translations.get(art["id"])
        if not tr:
            log.warning("no translation returned for article %s", art["id"])
            continue
        db.apply_translation(
            art["id"], tr["title"], tr["snippet"], _merge_classification(art, tr)
        )
        applied += 1
    return applied


def translate_batch(items: list[dict]) -> dict[int, dict]:
    """Translate items in batches. Returns {article_id: {title, snippet}}."""
    client = anthropic.Anthropic()
    out: dict[int, dict] = {}
    for i in range(0, len(items), BATCH_SIZE):
        chunk = items[i : i + BATCH_SIZE]
        payload = [
            {
                "id": a["id"],
                "language": a["language"],
                "title": a["title"],
                "snippet": (a.get("snippet") or "")[:1200],
            }
            for a in chunk
        ]
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            # Server-side refusal fallbacks (see regwatch/llm.py).
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}
            ],
        ) as stream:
            response = stream.get_final_message()
        if response.stop_reason == "refusal":
            raise RuntimeError("model declined the translation request")
        text = "".join(b.text for b in response.content if b.type == "text")
        for row in _parse_json_array(text):
            try:
                out[int(row["id"])] = {
                    "title": row["title_en"].strip(),
                    "snippet": (row.get("snippet_en") or "").strip(),
                }
            except (KeyError, ValueError, AttributeError):
                log.warning("malformed translation row: %r", row)
    return out


def _parse_json_array(text: str) -> list[dict]:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON array in model response")
    return json.loads(match.group(0))


def _merge_classification(art: dict, tr: dict) -> dict:
    """Re-classify on English text; union with tags found in the original."""
    new = classify(tr["title"], tr["snippet"])
    return {
        "countries": sorted(set(art["countries"]) | set(new["countries"])),
        "topics": sorted(set(art["topics"]) | set(new["topics"])),
        # A stage detected in the original language beats the fallback "news".
        "doc_type": new["doc_type"] if new["doc_type"] != "news" else art["doc_type"],
        "relevance_score": max(art["relevance_score"], new["relevance_score"]),
    }
