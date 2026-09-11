"""Optional LLM analysis of new regulatory developments, via the Claude API."""

from __future__ import annotations

import json

import anthropic

MODEL = "claude-opus-5"

SYSTEM_PROMPT = """You are a regulatory analyst advising policy makers on how
countries regulate data centers and cloud services, covering two policy areas:
(1) security & resilience of digital infrastructure, and (2) sustainability of
digital infrastructure.

You will receive a JSON list of newly detected news items (title, jurisdiction,
topics, document stage, date, source, snippet, and sometimes article text).

Write a concise briefing in markdown (no top-level heading; start at ###) with:

### What's new
The genuinely significant regulatory developments, grouped by jurisdiction.
Distinguish binding requirements from drafts/consultations from commentary.

### Stringency signals
Where requirements appear to be tightening or loosening, and for whom
(operators, cloud providers, customers). Note first-mover jurisdictions whose
approach others tend to copy.

### Emerging regulatory areas
Themes that several jurisdictions are starting to regulate (e.g. incident
reporting, energy/water disclosure, grid access, localization) — these signal
where a policy maker may face pressure to act next.

### Suggested follow-ups
2-4 concrete items worth a deeper read (name the item and why).

Ground every claim in the provided items; cite jurisdiction and source inline
like (Germany — Datacenter Dynamics). If the items are mostly noise, say so
plainly rather than inventing significance. News snippets can be inaccurate:
flag anything that should be verified against the primary legal text."""


def generate_insights(new_items: list[dict]) -> str:
    """Analyze new items and return a markdown insights section.

    Raises on any failure (no credentials, network, refusal) — the caller
    treats the LLM section as best-effort.
    """
    payload = [
        {
            "title": a["title"],
            "countries": a["countries"],
            "topics": a["topics"],
            "doc_type": a["doc_type"],
            "published_at": a["published_at"],
            "source": a["source"],
            "url": a["url"],
            "snippet": a.get("snippet") or "",
            "content": (a.get("content") or "")[:3000],
        }
        for a in new_items
    ]

    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        # Server-side refusal fallbacks: if a safety classifier declines,
        # the API transparently retries on a fallback model in the same call.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[
            {
                "role": "user",
                "content": (
                    "Newly detected items since the previous scrape:\n\n"
                    + json.dumps(payload, ensure_ascii=False, indent=1)
                ),
            }
        ],
    ) as stream:
        response = stream.get_final_message()

    if response.stop_reason == "refusal":
        raise RuntimeError("model declined the analysis request")

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise RuntimeError("empty response from model")
    return text
