"""Command-line interface for regwatch."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .db import Database
from .digest import build_digest, write_digest
from .export import export_jsonl, export_markdown
from .scraper import Scraper
from .sources import load_config

DEFAULT_DB = "data/regwatch.db"
DEFAULT_EXPORT_DIR = "data"
DEFAULT_REPORT_DIR = "reports"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="regwatch",
        description="Monitor how countries regulate data centers and cloud services.",
    )
    parser.add_argument("--db", default=DEFAULT_DB, help="path to SQLite database")
    parser.add_argument("--config", default=None, help="path to sources.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scrape = sub.add_parser("scrape", help="scrape all sources once")
    p_scrape.add_argument(
        "--no-content", action="store_true",
        help="skip fetching full article text (faster)",
    )

    p_export = sub.add_parser("export", help="export LLM-friendly corpus")
    p_export.add_argument("--out-dir", default=DEFAULT_EXPORT_DIR)
    p_export.add_argument(
        "--format", choices=["jsonl", "markdown", "both"], default="both"
    )

    p_digest = sub.add_parser(
        "digest", help="digest of changes since the previous scrape"
    )
    p_digest.add_argument("--out-dir", default=DEFAULT_REPORT_DIR)
    p_digest.add_argument("--no-llm", action="store_true",
                          help="skip the LLM policy-insights section")
    p_digest.add_argument("--stdout", action="store_true",
                          help="print digest instead of writing files")

    p_run = sub.add_parser("run", help="scrape + export + digest (periodic entrypoint)")
    p_run.add_argument("--no-content", action="store_true")
    p_run.add_argument("--no-llm", action="store_true")
    p_run.add_argument("--export-dir", default=DEFAULT_EXPORT_DIR)
    p_run.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)

    sub.add_parser("sources", help="list configured feeds")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    config = load_config(args.config)

    if args.command == "sources":
        for feed in config.feeds:
            print(f"[{feed.kind:11s}] {feed.label}\n              {feed.url}")
        print(f"\n{len(config.feeds)} feeds, relevance threshold "
              f"{config.relevance_threshold}, max age {config.max_age_days}d")
        return 0

    db = Database(args.db)
    try:
        if args.command == "scrape":
            _scrape(db, config, not args.no_content)
        elif args.command == "export":
            _export(db, args.out_dir, args.format)
        elif args.command == "digest":
            if args.stdout:
                print(build_digest(db, use_llm=not args.no_llm))
            else:
                path = write_digest(db, args.out_dir, use_llm=not args.no_llm)
                print(f"digest written to {path}")
        elif args.command == "run":
            _scrape(db, config, not args.no_content)
            _export(db, args.export_dir, "both")
            path = write_digest(db, args.report_dir, use_llm=not args.no_llm)
            print(f"digest written to {path}")
    finally:
        db.close()
    return 0


def _scrape(db: Database, config, fetch_content: bool) -> None:
    print(f"scraping {len(config.feeds)} feeds...")
    stats = Scraper(db, config, fetch_content=fetch_content).run()
    print(
        f"run #{stats['run_id']}: {stats['entries_seen']} entries seen, "
        f"{stats['new_articles']} new, {stats['new_relevant']} new relevant"
    )


def _export(db: Database, out_dir: str, fmt: str) -> None:
    out = Path(out_dir)
    if fmt in ("jsonl", "both"):
        n = export_jsonl(db, out / "corpus.jsonl")
        print(f"exported {n} articles to {out / 'corpus.jsonl'}")
    if fmt in ("markdown", "both"):
        n = export_markdown(db, out / "corpus.md")
        print(f"exported {n} articles to {out / 'corpus.md'}")


if __name__ == "__main__":
    sys.exit(main())
