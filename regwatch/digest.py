"""Generate a digest of regulatory developments new since the previous scrape.

The digest always contains a structured, deterministic section (counts, new
items grouped by country and topic). When an Anthropic API key is available
and LLM analysis is enabled, a "Policy Insights" section is appended with
analysis aimed at policy makers.
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

from .db import Database, utcnow

log = logging.getLogger("regwatch.digest")


def build_digest(db: Database, use_llm: bool = True) -> str:
    latest = db.latest_finished_run()
    if latest is None:
        return "# Regulatory Digest\n\nNo completed scrape runs yet. Run `python -m regwatch scrape` first.\n"

    previous = db.previous_finished_run(latest["id"])
    new_items = db.articles_in_run(latest["id"], relevant_only=True)

    period = (
        f"since previous scrape ({previous['finished_at']})"
        if previous
        else "first scrape (everything is new)"
    )

    lines = [
        "# Data Center & Cloud Regulatory Digest",
        "",
        f"Generated: {utcnow()}  ",
        f"Covers: run #{latest['id']} ({latest['finished_at']}), {period}  ",
        f"New relevant items: **{len(new_items)}**",
        "",
    ]

    if not new_items:
        lines.append("No new regulatory developments detected in this period.")
        return "\n".join(lines) + "\n"

    country_counts = Counter(c for a in new_items for c in (a["countries"] or ["Unattributed"]))
    topic_counts = Counter(t for a in new_items for t in (a["topics"] or ["general"]))
    stage_counts = Counter(a["doc_type"] for a in new_items)

    lines += [
        "## At a glance",
        "",
        "| Dimension | Breakdown |",
        "|---|---|",
        f"| Jurisdictions | {_fmt_counter(country_counts)} |",
        f"| Topics | {_fmt_counter(topic_counts)} |",
        f"| Document stage | {_fmt_counter(stage_counts)} |",
        "",
        "## New developments",
        "",
    ]

    for country in [c for c, _ in country_counts.most_common()]:
        items = [
            a for a in new_items
            if country in (a["countries"] or ["Unattributed"])
        ]
        lines.append(f"### {country}")
        lines.append("")
        for a in items:
            topics = ", ".join(a["topics"]) or "general"
            lang_note = ""
            if a.get("language", "en") != "en":
                lang_note = (
                    f"; translated from {a['language']}"
                    if a.get("translated")
                    else f"; original in {a['language']}, untranslated"
                )
            lines.append(
                f"- **{a['title']}** ({a['doc_type']}; {topics}{lang_note}) — "
                f"{a['source']}, {a['published_at'] or 'date unknown'}  \n"
                f"  {a['url']}"
            )
            if a.get("snippet"):
                lines.append(f"  > {a['snippet'][:300]}")
        lines.append("")

    digest = "\n".join(lines)

    if use_llm:
        insights = _llm_insights(new_items)
        if insights:
            digest += "\n## Policy Insights (LLM-generated)\n\n" + insights + "\n"
        else:
            digest += (
                "\n## Policy Insights\n\n"
                "_LLM analysis skipped (no Anthropic credentials available or "
                "the request failed — see logs). Set ANTHROPIC_API_KEY to enable._\n"
            )
    return digest


def write_digest(db: Database, out_dir: str | Path, use_llm: bool = True) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = build_digest(db, use_llm=use_llm)
    stamp = utcnow().replace(":", "").replace("-", "")[:13]  # YYYYMMDDTHHMM
    path = out_dir / f"digest-{stamp}.md"
    path.write_text(digest, encoding="utf-8")
    (out_dir / "latest-digest.md").write_text(digest, encoding="utf-8")
    return path


def _fmt_counter(counter: Counter) -> str:
    return ", ".join(f"{name} ({n})" for name, n in counter.most_common())


def _llm_insights(new_items: list[dict]) -> str | None:
    try:
        from .llm import generate_insights
        return generate_insights(new_items)
    except Exception as e:  # missing key, network, refusal — digest still works
        log.warning("LLM insights unavailable: %s", e)
        return None
