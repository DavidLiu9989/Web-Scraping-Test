# regwatch — Data Center & Cloud Regulatory Monitor

`regwatch` monitors how countries around the world are regulating **data
centers and cloud services**, across two policy areas:

- **Security & resilience** of digital infrastructure (critical-infrastructure
  designation, incident reporting, operational resilience, sovereignty /
  localization, concentration risk…)
- **Sustainability** of digital infrastructure (energy efficiency, water
  usage, carbon reporting, grid access, planning moratoria…)

Instead of googling repeatedly, run `regwatch` periodically. It:

1. **Scrapes** Google News RSS queries and regulator/trade-press feeds
   (no API keys required for scraping).
2. **Classifies** each item — relevance score, topics, jurisdictions, and
   document stage (consultation → draft → enacted → guidance).
3. **Stores** everything in SQLite with per-run history, so each scrape knows
   exactly what is new versus already seen.
4. **Exports** an LLM-friendly corpus (`data/corpus.jsonl` and
   `data/corpus.md`) that you can hand to an LLM together with your own
   policy documents to compare what's new vs. existing.
5. **Generates a digest** (`reports/latest-digest.md`) of developments new
   since the previous scrape — and, when an Anthropic API key is available,
   appends an LLM-written **Policy Insights** section: stringency signals,
   emerging regulatory areas, and suggested follow-ups for policy makers.

## Quick start

```bash
pip install -r requirements.txt

# One-off full cycle: scrape → export corpus → write digest
python -m regwatch run

# Or step by step
python -m regwatch scrape          # fetch + classify + store new items
python -m regwatch export          # write data/corpus.jsonl + data/corpus.md
python -m regwatch digest          # write reports/digest-<timestamp>.md
python -m regwatch digest --stdout # print instead of writing
python -m regwatch sources         # show configured feeds
```

Useful flags:

- `--no-llm` — skip the LLM insights section (digest is still generated)
- `--no-content` — skip fetching full article text (much faster)
- `-v` — verbose logging
- `--db path.db`, `--config path.yaml` — override defaults

## LLM insights (optional)

Set `ANTHROPIC_API_KEY` (or log in with `ant auth login`) to enable the
Policy Insights section. It uses Claude (`claude-opus-5`) with server-side
refusal fallbacks enabled, so a transient safety decline transparently
retries on a fallback model. Without credentials everything else still works.

## Outputs

| File | Purpose |
|---|---|
| `data/regwatch.db` | SQLite database — articles + scrape-run history |
| `data/corpus.jsonl` | One JSON object per relevant article; ideal for RAG / programmatic use |
| `data/corpus.md` | Markdown corpus grouped by country → item, with metadata headers; paste into an LLM chat alongside your own documents |
| `reports/digest-<ts>.md` | Point-in-time digest of what changed in that scrape |
| `reports/latest-digest.md` | Always the most recent digest |

### Using the corpus with an LLM

The corpus is designed for exactly the comparison workflow you'd do manually:

> *"Here is my existing requirements document and `corpus.md` from regwatch.
> What requirements are other countries imposing that ours doesn't cover?
> Where are ours more/less stringent?"*

Each item carries jurisdiction, topics, document stage, date, source, and URL
so the LLM can ground and cite its comparisons.

## Scheduling

A GitHub Actions workflow (`.github/workflows/regwatch.yml`) runs the full
cycle every Monday and Thursday at 06:00 UTC and commits updated data and
digests back to the repository. Add an `ANTHROPIC_API_KEY` repository secret
to enable LLM insights in scheduled runs; trigger manually via
*Actions → regwatch scheduled scrape → Run workflow*.

## Tuning coverage

Everything is configured in [`config/sources.yaml`](config/sources.yaml):

- **`google_news_queries`** — add/remove search queries (each expands into a
  Google News RSS feed per configured locale).
- **`rss_feeds`** — direct RSS/Atom feeds (regulators, ministries, trade press).
- **`google_news_locales`** — add locales to surface region-specific coverage.
- **`relevance_threshold`** — raise for precision, lower for recall.

The classifier keyword lists (topics, country/regulator signals, document
stage) live in [`regwatch/classify.py`](regwatch/classify.py) and are meant
to be edited — they're plain Python lists with comments.

## How "what's new" works

Every scrape is a numbered run. An article's `first_seen_run` records the run
that discovered it (deduplicated by URL and near-duplicate title). The digest
reports articles first seen in the latest run — i.e. everything that appeared
between the previous scrape and now.
