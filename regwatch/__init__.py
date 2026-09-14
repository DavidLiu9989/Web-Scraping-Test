"""regwatch - monitor how countries regulate data centers and cloud services.

Scrapes news and regulator feeds, classifies items by topic/country,
stores them in SQLite, exports an LLM-friendly corpus, and generates
a digest of what changed since the previous scrape.
"""

__version__ = "0.1.0"
