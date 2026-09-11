"""Classify scraped items: relevance, topics, countries, document type.

Everything here is deliberately keyword-based and transparent, so a policy
analyst can read this file and understand exactly why an article was kept
or dropped, and tune the lists without touching the rest of the code.
"""

from __future__ import annotations

import re
import string

# An article is relevant only if it mentions digital infrastructure AND a
# regulatory action. Score = infra_hits + regulatory_hits + topic bonuses.

INFRA_TERMS = [
    "data center", "data centre", "datacenter", "datacentre",
    "cloud service", "cloud services", "cloud provider", "cloud computing",
    "cloud infrastructure", "cloud resilience", "cloud security",
    "cloud sovereignty", "cloud switching", "sovereign cloud",
    "hyperscale", "colocation", "co-location",
    "digital infrastructure", "server farm", "compute infrastructure",
    "ai infrastructure", "iaas", "paas",
]

REGULATORY_TERMS = [
    "regulation", "regulate", "regulator", "regulatory", "legislation",
    "law", "bill", "act ", "statute", "decree", "ordinance", "directive",
    "consultation", "public comment", "draft rule", "rulemaking",
    "requirement", "mandate", "mandatory", "compliance", "licens",
    "permit", "moratorium", "restriction", "ban ", "policy", "framework",
    "standard", "code of practice", "code of conduct", "guideline",
    "oversight", "designation", "obligation", "enforce", "penalt",
    "ministry", "parliament", "commission", "authority", "government",
]

TOPIC_SECURITY = [
    "security", "cybersecurity", "cyber-security", "cyber attack",
    "resilience", "resilient", "critical infrastructure", "critical entity",
    "incident report", "outage", "downtime", "business continuity",
    "disaster recovery", "redundancy", "nis2", "nis 2", "dora",
    "operational resilience", "sovereignty", "sovereign cloud",
    "data localization", "data localisation", "data residency",
    "third-party risk", "concentration risk", "systemically important",
]

TOPIC_SUSTAINABILITY = [
    "sustainab", "energy efficiency", "energy consumption", "power usage",
    "pue", "carbon", "emission", "renewable", "green", "climate",
    "water usage", "water consumption", "cooling", "waste heat",
    "heat reuse", "grid", "electricity", "megawatt", "net zero", "net-zero",
    "environmental", "moratorium", "planning permission", "land use",
    "energy report", "taxonomy",
]

# Signals that an item is regulatory noise rather than regulatory news.
NEGATIVE_TERMS = [
    "stock", "shares", "earnings", "dividend", "price target",
    "investment analyst", "how to invest", "coupon", "review of the best",
]

DOC_TYPE_PATTERNS = [
    ("consultation", ["consultation", "public comment", "request for comment",
                      "call for evidence", "feedback period", "seeks views",
                      "seeks comment", "comment period"]),
    ("draft", ["draft law", "draft bill", "draft rule", "draft regulation",
               "proposed rule", "proposed law", "proposal", "bill introduced",
               "tabled", "draft"]),
    ("enacted", ["signed into law", "enacted", "comes into force",
                 "takes effect", "came into effect", "adopted", "passed",
                 "approved by parliament", "finalized", "finalised",
                 "published in the official"]),
    ("guidance", ["guidance", "guideline", "code of practice",
                  "code of conduct", "advisory", "circular", "standard"]),
]

# Country detection: names, adjectives, and regulator/ministry names that
# strongly imply a jurisdiction. Order does not matter; all matches recorded.
COUNTRY_SIGNALS: dict[str, list[str]] = {
    "European Union": ["european union", "eu ", " eu.", "european commission",
                       "european parliament", "enisa", "nis2", "nis 2",
                       "dora", "eu data act", "energy efficiency directive",
                       "brussels", "eu-wide"],
    "United States": ["united states", "u.s.", "us federal", "american",
                      "fcc", "ferc", "nist", "cisa", "white house",
                      "congress", "senate bill", "state of virginia",
                      "virginia", "texas", "california", "georgia",
                      "ohio", "oregon", "utah", "arizona", "washington state"],
    "United Kingdom": ["united kingdom", "uk ", "u.k.", "britain", "british",
                       "ofcom", "ofgem", "westminster", "dsit",
                       "national grid uk", "england", "scotland", "wales"],
    "Singapore": ["singapore", "imda", "csa singapore",
                  "cyber security agency of singapore", "mci singapore"],
    "Germany": ["germany", "german", "bnetza", "bundesnetzagentur",
                "bsi ", "energy efficiency act", "energieeffizienzgesetz"],
    "France": ["france", "french", "anssi", "arcep", "cnil"],
    "Netherlands": ["netherlands", "dutch", "amsterdam", "acm "],
    "Ireland": ["ireland", "irish", "eirgrid", "cru ", "dublin"],
    "China": ["china", "chinese", "cac ", "miit", "beijing",
              "east data west computing"],
    "India": ["india", "indian", "meity", "trai", "new delhi"],
    "Japan": ["japan", "japanese", "meti", "tokyo"],
    "South Korea": ["south korea", "korean", "kcc ", "msit", "seoul"],
    "Australia": ["australia", "australian", "acsc", "acma", "canberra"],
    "Malaysia": ["malaysia", "malaysian", "mcmc", "kuala lumpur", "johor"],
    "Indonesia": ["indonesia", "indonesian", "kominfo", "jakarta"],
    "Vietnam": ["vietnam", "vietnamese", "hanoi"],
    "Thailand": ["thailand", "thai ", "bangkok", "nbtc"],
    "Philippines": ["philippines", "filipino", "manila", "dict "],
    "Saudi Arabia": ["saudi", "cst ", "citc", "riyadh", "neom"],
    "United Arab Emirates": ["uae", "united arab emirates", "emirati",
                             "dubai", "abu dhabi", "tdra"],
    "Brazil": ["brazil", "brazilian", "anatel", "brasilia"],
    "Canada": ["canada", "canadian", "crtc", "ottawa", "ontario", "quebec"],
    "Spain": ["spain", "spanish", "madrid", "aragon"],
    "Italy": ["italy", "italian", "agcom", "rome", "milan"],
    "Poland": ["poland", "polish", "warsaw"],
    "Sweden": ["sweden", "swedish", "stockholm"],
    "Norway": ["norway", "norwegian", "oslo"],
    "Denmark": ["denmark", "danish", "copenhagen"],
    "Finland": ["finland", "finnish", "helsinki"],
    "Switzerland": ["switzerland", "swiss", "zurich"],
    "New Zealand": ["new zealand", "wellington", "auckland"],
    "South Africa": ["south africa", "johannesburg", "icasa"],
    "Nigeria": ["nigeria", "nigerian", "ncc ", "lagos"],
    "Kenya": ["kenya", "kenyan", "nairobi"],
    "Israel": ["israel", "israeli", "tel aviv"],
    "Chile": ["chile", "chilean", "santiago"],
    "Mexico": ["mexico", "mexican", "queretaro"],
    "Taiwan": ["taiwan", "taiwanese", "taipei"],
    "Hong Kong": ["hong kong", "ofca"],
}

_PUNCT_TABLE = str.maketrans("", "", string.punctuation)


def normalize_title(title: str) -> str:
    """Normalize a title for near-duplicate detection across outlets."""
    t = title.lower().translate(_PUNCT_TABLE)
    return re.sub(r"\s+", " ", t).strip()


def _count_hits(text: str, terms: list[str]) -> int:
    return sum(1 for t in terms if t in text)


def classify(title: str, snippet: str = "", content: str = "") -> dict:
    """Score and tag one article. Returns relevance + topic/country/doc_type."""
    text = " ".join(filter(None, [title, snippet, content[:5000]])).lower()
    # Pad so word-boundary-ish terms like "uk " match at string end too.
    text = f" {text} "

    infra = _count_hits(text, INFRA_TERMS)
    reg = _count_hits(text, REGULATORY_TERMS)
    sec = _count_hits(text, TOPIC_SECURITY)
    sus = _count_hits(text, TOPIC_SUSTAINABILITY)
    neg = _count_hits(text, NEGATIVE_TERMS)

    topics = []
    if sec:
        topics.append("security-resilience")
    if sus:
        topics.append("sustainability")

    # Both gates must pass; topic hits sweeten the score, noise terms sour it.
    if infra == 0 or reg == 0:
        score = 0.0
    else:
        score = min(infra, 3) + min(reg, 4) + min(sec + sus, 4) - 2 * neg

    doc_type = "news"
    for dtype, patterns in DOC_TYPE_PATTERNS:
        if any(p in text for p in patterns):
            doc_type = dtype
            break

    countries = [
        country
        for country, signals in COUNTRY_SIGNALS.items()
        if any(s in text for s in signals)
    ]

    return {
        "relevance_score": round(score, 1),
        "topics": topics,
        "countries": countries,
        "doc_type": doc_type,
    }
