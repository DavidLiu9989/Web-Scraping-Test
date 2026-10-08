"""Offline end-to-end test: fixture feed entries through the full pipeline.

Run with:  python tests/test_pipeline.py   (or pytest)
No network access required — feed fetching is stubbed.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from regwatch.classify import classify, normalize_title
from regwatch.db import Database
from regwatch.digest import build_digest
from regwatch.export import export_jsonl, export_markdown
from regwatch.scraper import Scraper
from regwatch.sources import Feed, SourceConfig


def entry(title, link, summary="", source_title=None):
    now = datetime.now(timezone.utc).timetuple()
    e = SimpleNamespace(
        title=title, link=link, summary=summary, published_parsed=now
    )
    if source_title:
        e.source = SimpleNamespace(title=source_title)
    return e


FIXTURE_ENTRIES = [
    entry(
        "Germany tightens data center energy efficiency law with new PUE mandate - Example News",
        "https://example.com/germany-eneff",
        "The Energieeffizienzgesetz amendment imposes mandatory PUE limits and "
        "waste heat reuse requirements on data centre operators, with penalties "
        "for non-compliance from 2027.",
    ),
    entry(
        "Singapore IMDA opens consultation on cloud services resilience requirements - Tech Daily",
        "https://example.com/sg-cloud",
        "The Infocomm Media Development Authority seeks public comment on draft "
        "regulation covering incident reporting and business continuity for "
        "cloud providers designated as critical infrastructure.",
    ),
    # Same story from another outlet: near-duplicate title must be deduped
    entry(
        "Singapore IMDA opens consultation on cloud services resilience requirements - Other Outlet",
        "https://other.example.com/sg-cloud-dupe",
        "IMDA consultation on cloud resilience.",
    ),
    # Irrelevant: infra term but no regulatory action
    entry(
        "Top 10 data center stocks to buy now - Finance Blog",
        "https://example.com/stocks",
        "Analysts share their favorite data center shares and price targets "
        "for investors this quarter.",
    ),
    # Irrelevant: regulatory but not digital infrastructure
    entry(
        "Parliament passes new fishing quota regulation - Wire",
        "https://example.com/fish",
        "The new law imposes quota requirements on trawlers.",
    ),
]


def fake_config():
    return SourceConfig(
        feeds=[Feed(url="https://fake.test/feed", label="fixture", kind="google-news")],
        relevance_threshold=3.0,
        max_age_days=45,
    )


def test_classify():
    r = classify(
        "EU adopts data centre sustainability reporting directive",
        "Mandatory energy and water usage reporting for operators.",
    )
    assert r["relevance_score"] >= 3.0, r
    assert "sustainability" in r["topics"], r
    assert "European Union" in r["countries"], r

    noise = classify("Best cloud stocks to buy", "price target dividend shares")
    assert noise["relevance_score"] < 3.0, noise

    assert normalize_title("Hello,  World!") == normalize_title("hello world")
    print("classify: OK")


def test_pipeline():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        db = Database(tmp / "test.db")
        scraper = Scraper(db, fake_config(), fetch_content=False)
        scraper._fetch_feed = lambda feed: FIXTURE_ENTRIES

        stats = scraper.run()
        assert stats["entries_seen"] == 5, stats
        # dupe title collapses 2 SG stories into 1 → 4 stored
        assert stats["new_articles"] == 4, stats
        assert stats["new_relevant"] == 2, stats

        arts = db.relevant_articles()
        countries = {c for a in arts for c in a["countries"]}
        assert {"Germany", "Singapore"} <= countries, countries
        sg = next(a for a in arts if "Singapore" in a["countries"])
        assert sg["doc_type"] == "consultation", sg
        assert "security-resilience" in sg["topics"], sg

        # second run over identical feed: nothing new
        stats2 = scraper.run()
        assert stats2["new_articles"] == 0, stats2

        n = export_jsonl(db, tmp / "corpus.jsonl")
        assert n == 2
        n = export_markdown(db, tmp / "corpus.md")
        assert n == 2
        corpus = (tmp / "corpus.md").read_text()
        assert "## Germany" in corpus and "## Singapore" in corpus

        digest = build_digest(db, use_llm=False)
        assert "No new regulatory developments" in digest, digest

        # digest for the first run's articles: rebuild against run 1
        first_run_items = db.articles_in_run(1)
        assert len(first_run_items) == 2
        db.close()
    print("pipeline: OK")


SPANISH_ENTRY = entry(
    "España aprueba un real decreto con requisitos de eficiencia energética "
    "para los centros de datos - El País",
    "https://example.com/es-decreto",
    "El Gobierno de España ha aprobado un real decreto que impone requisitos "
    "de eficiencia energética y de reutilización del calor residual a los "
    "centros de datos, con sanciones por incumplimiento a partir de 2027.",
)

CANNED_TRANSLATION = {
    "title": "Spain approves Real Decreto (Royal Decree) with energy "
             "efficiency requirements for data centers",
    "snippet": "The Spanish government approved a royal decree imposing "
               "energy efficiency and waste heat reuse requirements on data "
               "centers, with penalties for non-compliance from 2027.",
}


def test_multilingual():
    import regwatch.translate as tr

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        db = Database(tmp / "test.db")
        scraper = Scraper(db, fake_config(), fetch_content=False)
        scraper._fetch_feed = lambda feed: [SPANISH_ENTRY]
        stats = scraper.run()
        assert stats["new_relevant"] == 1, stats

        # Stored in Spanish, gated by multilingual keywords, tagged correctly
        art = db.relevant_articles()[0]
        assert art["language"] == "es", art["language"]
        assert "Spain" in art["countries"], art
        assert art["doc_type"] == "enacted", art
        assert "sustainability" in art["topics"], art
        assert db.pending_translations(), "should be queued for translation"

        # Translation applied (LLM stubbed out)
        original = tr.translate_batch
        tr.translate_batch = lambda items: {items[0]["id"]: dict(CANNED_TRANSLATION)}
        try:
            n = tr.translate_pending(db)
        finally:
            tr.translate_batch = original
        assert n == 1

        art = db.relevant_articles()[0]
        assert art["translated"] == 1
        assert art["title"].startswith("Spain approves"), art["title"]
        assert art["original_title"].startswith("España"), art["original_title"]
        assert art["doc_type"] == "enacted", art  # stage survives re-classification
        assert not db.pending_translations()

        # Untranslated fallback is visible in the digest; translated note too
        digest = build_digest(db, use_llm=False)
        assert "translated from es" in digest, digest
        db.close()
    print("multilingual: OK")


if __name__ == "__main__":
    test_classify()
    test_pipeline()
    test_multilingual()
    print("all tests passed")
