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
    # -- non-English (es, fr, de, pt, it, nl, id, ja, ko, zh, vi) --
    "centro de datos", "centros de datos", "servicios en la nube",
    "infraestructura digital",
    "centre de données", "centres de données", "services en nuage",
    "informatique en nuage", "infrastructure numérique",
    "rechenzentrum", "rechenzentren", "cloud-dienste",
    "digitale infrastruktur",
    "centro de dados", "centros de dados", "serviços em nuvem",
    "infraestrutura digital",
    "centro dati", "centri dati", "servizi cloud",
    "infrastruttura digitale",
    "clouddiensten", "digitale infrastructuur",
    "pusat data", "layanan cloud", "infrastruktur digital",
    "データセンター", "クラウドサービス",
    "데이터센터", "클라우드",
    "数据中心", "資料中心", "云服务", "雲端服務",
    "trung tâm dữ liệu", "dịch vụ đám mây",
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
    # -- non-English --
    "regulación", "reglamento", "real decreto", "decreto", "ley ",
    "anteproyecto", "consulta pública", "normativa", "obligación",
    "requisito", "licencia", "sanción",
    "réglementation", "règlement", "décret", "loi ", "arrêté",
    "consultation publique", "obligation", "exigence",
    "verordnung", "gesetz", "regulierung", "vorschrift", "konsultation",
    "pflicht", "genehmigung", "anforderung",
    "regulamentação", "regulamento", "lei federal", "portaria",
    "regolamento", "legge", "consultazione", "obbligo",
    "regelgeving", "wetgeving", "vergunning", "consultatie",
    "regulasi", "peraturan", "undang-undang", "izin", "kewajiban",
    "規制", "法律", "省令", "義務", "法案",
    "규제", "법률", "법안", "의무", "고시",
    "监管", "法规", "条例", "法規", "管理办法", "办法",
    "quy định", "nghị định", "luật", "thông tư",
]

TOPIC_SECURITY = [
    "security", "cybersecurity", "cyber-security", "cyber attack",
    "resilience", "resilient", "critical infrastructure", "critical entity",
    "incident report", "outage", "downtime", "business continuity",
    "disaster recovery", "redundancy", "nis2", "nis 2", "dora",
    "operational resilience", "sovereignty", "sovereign cloud",
    "data localization", "data localisation", "data residency",
    "third-party risk", "concentration risk", "systemically important",
    # -- non-English --
    "seguridad", "resiliencia", "ciberseguridad", "infraestructura crítica",
    "soberanía", "localización de datos",
    "sécurité", "résilience", "cybersécurité", "infrastructure critique",
    "souveraineté",
    "sicherheit", "cybersicherheit", "resilienz", "kritische infrastruktur",
    "segurança", "cibersegurança", "resiliência",
    "sicurezza", "resilienza",
    "beveiliging", "weerbaarheid",
    "keamanan", "ketahanan",
    "セキュリティ", "サイバー", "強靭",
    "보안", "안보", "복원력",
    "网络安全", "資安", "韧性",
    "an ninh mạng",
]

TOPIC_SUSTAINABILITY = [
    "sustainab", "energy efficiency", "energy consumption", "power usage",
    "pue", "carbon", "emission", "renewable", "green", "climate",
    "water usage", "water consumption", "cooling", "waste heat",
    "heat reuse", "grid", "electricity", "megawatt", "net zero", "net-zero",
    "environmental", "moratorium", "planning permission", "land use",
    "energy report", "taxonomy",
    # -- non-English --
    "sostenibilidad", "eficiencia energética", "consumo de agua",
    "energía renovable", "huella de carbono",
    "durabilité", "efficacité énergétique", "consommation d'eau",
    "émissions", "chaleur fatale",
    "nachhaltigkeit", "energieeffizienz", "wasserverbrauch", "abwärme",
    "emissionen", "stromverbrauch",
    "sustentabilidade", "eficiência energética",
    "sostenibilità", "efficienza energetica", "emissioni",
    "duurzaamheid", "energieverbruik",
    "keberlanjutan", "efisiensi energi",
    "省エネ", "再生可能エネルギー", "エネルギー効率", "脱炭素",
    "에너지 효율", "탄소", "재생에너지",
    "能效", "碳排放", "可再生能源", "節能",
    "hiệu quả năng lượng", "năng lượng tái tạo",
]

# Signals that an item is regulatory noise rather than regulatory news.
NEGATIVE_TERMS = [
    "stock", "shares", "earnings", "dividend", "price target",
    "investment analyst", "how to invest", "coupon", "review of the best",
]

DOC_TYPE_PATTERNS = [
    ("consultation", ["consultation", "public comment", "request for comment",
                      "call for evidence", "feedback period", "seeks views",
                      "seeks comment", "comment period",
                      "consulta pública", "consultation publique",
                      "audiencia pública", "konsultation", "consultazione",
                      "consultatie", "パブリックコメント", "의견수렴",
                      "征求意见"]),
    ("draft", ["draft law", "draft bill", "draft rule", "draft regulation",
               "proposed rule", "proposed law", "proposal", "bill introduced",
               "tabled", "draft",
               "anteproyecto", "proyecto de ley", "proyecto de real decreto",
               "projet de loi", "projet de décret", "gesetzentwurf", "entwurf",
               "disegno di legge", "projeto de lei", "rancangan",
               "法案", "草案", "dự thảo"]),
    ("enacted", ["signed into law", "enacted", "comes into force",
                 "takes effect", "came into effect", "adopted", "passed",
                 "approved by parliament", "finalized", "finalised",
                 "published in the official",
                 "real decreto", "entra en vigor", "publicado en el boe",
                 "aprobado", "aprueba", "promulgado",
                 "entrée en vigueur", "adopté", "promulgué",
                 "in kraft", "verabschiedet", "beschlossen",
                 "entra em vigore", "entra em vigor", "entrata in vigore",
                 "施行", "公布", "시행", "ban hành"]),
    ("guidance", ["guidance", "guideline", "code of practice",
                  "code of conduct", "advisory", "circular", "standard",
                  "directrices", "lignes directrices", "leitlinien",
                  "diretrizes", "linee guida", "richtlijn",
                  "ガイドライン", "指針", "지침"]),
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
                "bsi ", "energy efficiency act", "energieeffizienzgesetz",
                "deutschland", "bundesregierung"],
    "France": ["france", "french", "anssi", "arcep", "cnil",
               "journal officiel", "française"],
    "Netherlands": ["netherlands", "dutch", "amsterdam", "acm ",
                    "nederland", "nederlandse"],
    "Ireland": ["ireland", "irish", "eirgrid", "cru ", "dublin"],
    "China": ["china", "chinese", "cac ", "miit", "beijing",
              "east data west computing", "中国", "工信部",
              "国家互联网信息办公室"],
    "India": ["india", "indian", "meity", "trai", "new delhi"],
    "Japan": ["japan", "japanese", "meti", "tokyo", "日本", "総務省",
              "経済産業省"],
    "South Korea": ["south korea", "korean", "kcc ", "msit", "seoul",
                    "한국", "대한민국", "과기정통부"],
    "Australia": ["australia", "australian", "acsc", "acma", "canberra"],
    "Malaysia": ["malaysia", "malaysian", "mcmc", "kuala lumpur", "johor"],
    "Indonesia": ["indonesia", "indonesian", "kominfo", "jakarta",
                  "menkominfo"],
    "Vietnam": ["vietnam", "vietnamese", "hanoi", "việt nam"],
    "Thailand": ["thailand", "thai ", "bangkok", "nbtc"],
    "Philippines": ["philippines", "filipino", "manila", "dict "],
    "Saudi Arabia": ["saudi", "cst ", "citc", "riyadh", "neom"],
    "United Arab Emirates": ["uae", "united arab emirates", "emirati",
                             "dubai", "abu dhabi", "tdra"],
    "Brazil": ["brazil", "brazilian", "anatel", "brasilia", "brasil",
               "brasileiro"],
    "Canada": ["canada", "canadian", "crtc", "ottawa", "ontario", "quebec"],
    "Spain": ["spain", "spanish", "madrid", "aragon", "españa", "español",
              "real decreto", "boe ", "cnmc", "miteco",
              "gobierno de españa"],
    "Italy": ["italy", "italian", "agcom", "rome", "milan", "italia",
              "italiano"],
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
    "Mexico": ["mexico", "mexican", "queretaro", "méxico", "mexicano"],
    "Taiwan": ["taiwan", "taiwanese", "taipei", "台灣", "臺灣"],
    "Hong Kong": ["hong kong", "ofca"],
    "Portugal": ["portugal", "portuguese", "anacom", "lisbon",
                 "portuguesa"],
    "Argentina": ["argentina", "buenos aires", "enacom"],
    "Colombia": ["colombia", "bogotá", "bogota"],
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
