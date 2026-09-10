"""CoherentConnect Newsletter — tenant profile, feeds, trigger taxonomy, scoring weights.

This is a self-contained distillation of the mother codebase's config: the country/
industry keyword bible + trigger-event filters + RSS/Google-News feeds, scoped here to
a single tenant (Coherent Market Insights) so the newsletter can run standalone.
"""
from __future__ import annotations

# ── The tenant (seller) profile ─────────────────────────────────────────────
TENANT = {
    "company": "Coherent Market Insights",
    "short": "CMI",
    "recipient_first_name": "Raj",
    "tagline": "Sales intelligence, made coherent.",
    # What CMI sells — used to frame the pitch / recommended action.
    "value_prop": (
        "analyst-verified syndicated and custom market-research reports: market sizing, "
        "competitive landscaping, patient/segment analysis, and go-to-market intelligence "
        "across healthcare, life sciences, chemicals, ICT and telecom."
    ),
    # CMI's coverage verticals. A prospect is relevant only if its news maps here.
    "industries": ["Healthcare", "Pharmaceuticals & Life Sciences", "Biotechnology",
                   "Chemicals & Materials", "ICT & Technology", "Telecom", "Medical Devices"],
    # Named competitors — used for the "What Competitors Are Up To" section.
    "competitors": [
        "Grand View Research", "MarketsandMarkets", "Precedence Research",
        "Allied Market Research", "Mordor Intelligence", "Fortune Business Insights",
        "Future Market Insights",
    ],
}

# ── CoherentLead's OWN tenant profile (AI-powered B2B prospecting/outreach SaaS) ──
# CoherentLead has no fixed target vertical of its own (per coherentlead.ai: "no matter
# how well you know your market") — any company running outbound sales is a fit. This is
# the DEFAULT profile used when no seller company is named (mirrors config.TENANT for CMI).
COHERENTLEAD_TENANT = {
    "company": "CoherentLead",
    "short": "CoherentLead",
    "recipient_first_name": "there",
    "tagline": "Transform outbound sales into a precision-driven process.",
    "value_prop": (
        "an AI-powered B2B prospecting and sales intelligence platform: AI-built ideal "
        "customer profiles, a 250M+ contact and company database, 7-layer email "
        "verification, LinkedIn prospect discovery, and live account intelligence — all "
        "from one workspace."
    ),
    # Broad, vertical-agnostic — any company building/scaling an outbound sales motion.
    "industries": ["B2B SaaS", "Fintech", "Enterprise Software", "High-Growth Startups",
                   "Manufacturing", "Chemicals & Materials", "Professional Services"],
    "competitors": ["Apollo.io", "Apollo", "ZoomInfo", "Lusha", "Clearbit", "Cognism"],
}

# ── Industry relevancy lexicon (keyword → the vertical it signals) ───────────
# Weighted keyword matching drives the "relevancy" score. Lowercased word-ish tokens.
INDUSTRY_KEYWORDS = {
    "Healthcare": ["healthcare", "hospital", "clinical", "patient", "therapy", "therapeutic",
                   "disease", "medical", "health", "care delivery", "payer", "provider"],
    "Pharmaceuticals & Life Sciences": ["pharma", "pharmaceutical", "drug", "molecule", "fda",
                   "phase 1", "phase 2", "phase 3", "trial", "indication", "oncology",
                   "vaccine", "biopharma", "life sciences", "clinical trial"],
    "Biotechnology": ["biotech", "biotechnology", "gene therapy", "mrna", "antibody", "cell therapy",
                   "genomics", "crispr", "fibrosis", "antifibrotic", "rare disease"],
    "Chemicals & Materials": ["chemical", "chemicals", "specialty chemical", "polymer", "coatings",
                   "materials", "petrochemical", "resin", "catalyst", "battery material"],
    "ICT & Technology": ["software", "ai", "artificial intelligence", "cloud", "semiconductor",
                   "chip", "data center", "saas", "enterprise software", "generative ai", "agentic"],
    "Telecom": ["telecom", "5g", "broadband", "spectrum", "fiber", "operator", "network", "wireless"],
    "Medical Devices": ["medical device", "diagnostic", "imaging", "implant", "wearable", "in-vitro"],
}

# ── Trigger-event taxonomy (importance weight 0..1 + detection keywords) ─────
# A "trigger" is a live event that creates immediate demand for market research
# (funding needs market sizing; a trial needs competitive landscaping; etc.).
TRIGGER_TYPES = {
    "funding_round":       {"importance": 0.95, "keywords": ["raises", "raised", "funding", "series a",
                            "series b", "series c", "seed round", "debut round", "financing", "led by",
                            "million round", "closes $", "secures $", "backed by"]},
    "ipo":                 {"importance": 0.92, "keywords": ["ipo", "goes public", "public listing",
                            "files for ipo", "debut", "lists on", "stock market debut"]},
    "mna":                 {"importance": 0.88, "keywords": ["acquires", "acquisition", "merger",
                            "to acquire", "buys", "takeover", "merges with"]},
    "clinical_trial":      {"importance": 0.90, "keywords": ["phase 3", "phase 2", "pivotal trial",
                            "topline", "trial results", "enrolls", "primary endpoint", "readout"]},
    "regulatory_approval": {"importance": 0.85, "keywords": ["fda approval", "approved", "clearance",
                            "ema", "authorization", "green light", "designation"]},
    "product_launch":      {"importance": 0.70, "keywords": ["launches", "unveils", "rolls out",
                            "introduces", "debuts product", "new platform"]},
    "expansion":           {"importance": 0.72, "keywords": ["expands", "new plant", "new facility",
                            "opens factory", "capacity expansion", "enters market", "expansion into"]},
    "partnership":         {"importance": 0.60, "keywords": ["partners with", "partnership",
                            "collaboration", "joint venture", "teams up", "alliance"]},
    "exec_hire":           {"importance": 0.50, "keywords": ["appoints", "names new", "hires",
                            "joins as", "new ceo", "new cfo", "chief"]},
}

# Money-scale boosters — a big number amplifies importance.
BIG_MONEY_HINTS = ["billion", "$1b", "$2b", "$500m", "$400m", "$300m", "$250m", "$200m",
                   "$180m", "$150m", "$100m", "crore"]

# ── Feeds / queries ─────────────────────────────────────────────────────────
# Locale-parameterized so each target country pulls its own Google-News edition.
GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"
GN_DEFAULT_LOCALE = ("en-US", "US", "US:en")
LOOKBACK_HOURS = 96  # signals older than this are dropped

# ── Target countries (compact port of the mother repo's config_countries/) ──
# Each: Google-News locale (hl, gl, ceid) + geo-match signals used to HARD-FILTER
# collected articles down to that country. "Global" = no locale bias, no filter.
COUNTRIES = {
    "Global": {"name": "Global", "gn": GN_DEFAULT_LOCALE, "aliases": [], "nationality": "",
               "cities": [], "currency": [], "tld": [], "outlets": []},
    "India": {"name": "India", "gn": ("en-IN", "IN", "IN:en"),
              "aliases": ["india", "indian", "bharat"], "nationality": "indian",
              "cities": ["mumbai", "delhi", "new delhi", "bengaluru", "bangalore", "chennai",
                         "hyderabad", "pune", "kolkata", "gurugram", "gurgaon", "noida", "ahmedabad"],
              "currency": ["₹", "rupee", "rupees", "crore", "lakh", "inr"], "tld": [".in"],
              "outlets": ["economic times", "livemint", "mint", "business standard", "moneycontrol",
                          "the hindu", "times of india", "ndtv", "financial express", "et now", "inc42",
                          "yourstory", "entrackr"]},
    "United States": {"name": "United States", "gn": ("en-US", "US", "US:en"),
              "aliases": ["united states", "u.s.", "us-based", "america", "american", " usa"],
              "nationality": "american",
              "cities": ["new york", "san francisco", "boston", "chicago", "los angeles", "seattle",
                         "austin", "silicon valley", "washington", "houston", "atlanta"],
              "currency": [], "tld": [], "outlets": ["cnbc", "wall street journal", "wsj", "bloomberg",
                          "techcrunch", "the new york times", "forbes", "reuters us", "axios"]},
    "United Kingdom": {"name": "United Kingdom", "gn": ("en-GB", "GB", "GB:en"),
              "aliases": ["uk", "u.k.", "britain", "british", "england", "united kingdom"],
              "nationality": "british",
              "cities": ["london", "manchester", "birmingham", "cambridge", "oxford", "edinburgh",
                         "glasgow", "leeds", "bristol"],
              "currency": ["£", "pound", "gbp", "pence"], "tld": [".co.uk", ".uk"],
              "outlets": ["bbc", "the guardian", "financial times", "sky news", "the telegraph",
                          "city a.m.", "uktech", "sifted"]},
    "Canada": {"name": "Canada", "gn": ("en-CA", "CA", "CA:en"),
              "aliases": ["canada", "canadian"], "nationality": "canadian",
              "cities": ["toronto", "vancouver", "montreal", "ottawa", "calgary", "waterloo", "edmonton"],
              "currency": ["cad", "c$"], "tld": [".ca"],
              "outlets": ["the globe and mail", "cbc", "financial post", "betakit", "the logic"]},
    "Australia": {"name": "Australia", "gn": ("en-AU", "AU", "AU:en"),
              "aliases": ["australia", "australian", "aussie"], "nationality": "australian",
              "cities": ["sydney", "melbourne", "brisbane", "perth", "adelaide", "canberra"],
              "currency": ["a$", "aud"], "tld": [".com.au", ".au"],
              "outlets": ["afr", "australian financial review", "abc news", "smart company", "startupdaily"]},
    "Singapore": {"name": "Singapore", "gn": ("en-SG", "SG", "SG:en"),
              "aliases": ["singapore", "singaporean", "sg"], "nationality": "singaporean",
              "cities": ["singapore"], "currency": ["s$", "sgd"], "tld": [".sg"],
              "outlets": ["straits times", "business times", "cna", "tech in asia", "e27"]},
    "United Arab Emirates": {"name": "United Arab Emirates", "gn": ("en-AE", "AE", "AE:en"),
              "aliases": ["uae", "u.a.e.", "emirati", "emirates"], "nationality": "emirati",
              "cities": ["dubai", "abu dhabi", "sharjah"], "currency": ["aed", "dirham"], "tld": [".ae"],
              "outlets": ["the national", "khaleej times", "gulf news", "arabian business", "wamda"]},
    "Germany": {"name": "Germany", "gn": ("en-DE", "DE", "DE:en"),
              "aliases": ["germany", "german", "deutschland"], "nationality": "german",
              "cities": ["berlin", "munich", "münchen", "frankfurt", "hamburg", "cologne", "stuttgart"],
              "currency": ["€", "euro"], "tld": [".de"],
              "outlets": ["handelsblatt", "der spiegel", "deutsche welle", "gründerszene", "tagesschau"]},
    "Japan": {"name": "Japan", "gn": ("en-JP", "JP", "JP:en"),
              "aliases": ["japan", "japanese"], "nationality": "japanese",
              "cities": ["tokyo", "osaka", "kyoto", "yokohama", "nagoya"], "currency": ["¥", "yen", "jpy"],
              "tld": [".jp"], "outlets": ["nikkei", "japan times", "kyodo", "nhk"]},
    "Brazil": {"name": "Brazil", "gn": ("en-419", "BR", "BR:en"),
              "aliases": ["brazil", "brazilian", "brasil"], "nationality": "brazilian",
              "cities": ["são paulo", "sao paulo", "rio de janeiro", "brasília", "belo horizonte"],
              "currency": ["r$", "real", "reais", "brl"], "tld": [".br", ".com.br"],
              "outlets": ["valor", "exame", "folha", "startse", "neofeed"]},
    "Nigeria": {"name": "Nigeria", "gn": ("en-NG", "NG", "NG:en"),
              "aliases": ["nigeria", "nigerian"], "nationality": "nigerian",
              "cities": ["lagos", "abuja", "ibadan", "port harcourt"], "currency": ["₦", "naira", "ngn"],
              "tld": [".ng", ".com.ng"], "outlets": ["techcabal", "nairametrics", "premium times",
                          "the guardian nigeria", "businessday"]},
}


# ── Market-research firms (CMI's own competitors) + PR wires ────────────────
# In the CMI lead-nurture newsletter we must NOT cite these as sources or reproduce their
# market estimates — CMI would never quote a rival research firm's numbers to its own client.
# Articles from these sources (and generic "market size / forecast" report-PR) are dropped;
# any market figures are presented as Coherent Market Insights' OWN intelligence.
RESEARCH_FIRM_SOURCES = [
    "grand view", "grandview", "fortune business insights", "marketsandmarkets", "markets and markets",
    "precedence research", "mordor intelligence", "allied market", "future market insights",
    "imarc", "market research future", "researchandmarkets", "research and markets", "vantage market",
    "polaris market", "straits research", "data bridge", "databridge", "the business research company",
    "expert market research", "custom market insights", "spherical insights", "fact.mr", "factmr",
    "persistence market", "transparency market", "verified market", "emergen research", "skyquest",
    "insightace", "maximize market", "cognitive market", "astute analytica", "market.us", "market us",
    "meticulous research", "next move strategy", "roots analysis", "delveinsight", "delve insight",
    "coherent market insights", "openpr", "globenewswire", "globe newswire", "prnewswire", "pr newswire",
    "einpresswire", "ein presswire", "digital journal", "benzinga", "yahoo finance market",
    "kenneth research", "zion market", "acumen research", "credence research", "prophecy market",
    "sns insider", "towards healthcare", "biospace market",
]

# Report-PR headline patterns (a competitor's report title, not a real news event).
import re as _re
_REPORT_PR_RE = _re.compile(
    r"market\s+(size|share|report|forecast|analysis|outlook|trends?|research|revenue|growth\s+analysis)"
    r"|\bcagr\b|forecast\s+(to|till|until|period|by)\s*,?\s*20\d\d|to\s+reach\s+(usd|us\$|\$|inr)"
    r"|\|\s*(report|forecast|industry|20\d\d)|\bmn\b.*\b20\d\d\b|\(7mm\)|worth\s+(usd|us\$|\$)",
    _re.I,
)


def is_research_pr(source: str, title: str) -> bool:
    """True if an article is a rival research firm's output or generic market-report PR."""
    s = (source or "").lower()
    if any(firm in s for firm in RESEARCH_FIRM_SOURCES):
        return True
    return bool(_REPORT_PR_RE.search(title or ""))


def get_country(name: str) -> dict:
    """Resolve a country by name/alias → its profile dict. Unknown → Global."""
    if not name:
        return COUNTRIES["Global"]
    n = name.strip().lower()
    for key, prof in COUNTRIES.items():
        if key.lower() == n or n in [a.strip().lower() for a in prof.get("aliases", [])] or prof["name"].lower() == n:
            return prof
    return COUNTRIES["Global"]

# Trigger discovery queries (company-level buying triggers in CMI's verticals).
TRIGGER_QUERIES = [
    "biotech funding round", "pharma Series B financing", "drug developer raises million",
    "phase 3 clinical trial start", "FDA approval drug", "gene therapy funding",
    "medical device FDA clearance", "specialty chemicals capacity expansion",
    "semiconductor plant investment", "5G network investment", "healthcare startup raises",
    "life sciences IPO", "biopharma acquisition", "oncology drug financing",
]
# Industry / structural queries ("Industry News" section).
INDUSTRY_QUERIES = [
    "AI agents market research", "market research industry trends 2026",
    "syndicated research market", "B2B data market report", "market intelligence AI disruption",
    "generative AI enterprise adoption research",
]

# ── CoherentLead's own relevancy lexicon (vertical-agnostic — buying trigger keywords) ──
# CoherentLead's "Ideal Customer" is any company about to scale outbound sales, not a
# fixed industry — so relevancy keys off the SITUATION (new sales hire, funding, market
# expansion) more than the vertical. Verticals here are broad buckets for scoring only.
COHERENTLEAD_INDUSTRY_KEYWORDS = {
    "B2B SaaS": ["saas", "software", "platform", "subscription", "b2b software", "enterprise software"],
    "Fintech": ["fintech", "payments", "banking", "financial platform", "lending", "insurtech"],
    "Enterprise Software": ["enterprise software", "erp", "crm", "workflow platform", "b2b platform"],
    "High-Growth Startups": ["series a", "series b", "series c", "startup", "raises", "funding round"],
    "Manufacturing": ["manufacturing", "factory", "production line", "industrial", "plant"],
    "Chemicals & Materials": ["chemical", "specialty chemical", "formulation", "materials", "agrochemical"],
    "Professional Services": ["consulting", "agency", "professional services", "services firm"],
}

# Trigger discovery queries — the moments that create a fresh need for outbound
# infrastructure: new funding, a first sales hire, market/geo expansion, no CRM hygiene.
COHERENTLEAD_TRIGGER_QUERIES = [
    "startup raises Series A funding", "startup raises Series B funding",
    "company hires VP of Sales", "company hires first sales hire", "builds outbound sales team",
    "company expands into new markets", "company opens new office expansion",
    "startup hires Head of Revenue Operations", "company scales go-to-market team",
    "raises funding round hiring", "company launches sales team from scratch",
]
# Structural / industry queries for CoherentLead's own "Industry Outlook" (B2B sales tooling).
COHERENTLEAD_INDUSTRY_QUERIES = [
    "B2B sales intelligence market trends", "outbound sales AI tools 2026",
    "sales prospecting automation trends", "email deliverability best practices 2026",
    "AI sales development trends",
]

# ── Scoring matrix weights (relevancy x freshness x importance) ─────────────
SCORING = {
    "w_relevancy": 0.40,
    "w_freshness": 0.25,
    "w_importance": 0.35,
    # Freshness decay (hours → factor). Piecewise, mirrors mother repo's freshness_score.
    "freshness_bands": [(24, 1.00), (48, 0.85), (72, 0.65), (96, 0.45), (168, 0.25)],
    "freshness_floor": 0.10,
    # Minimum composite for a signal to be eligible for the newsletter at all.
    "min_composite": 0.18,
}

# ── LLM settings ────────────────────────────────────────────────────────────
# Provider order: DeepSeek first (as requested); auto-fallback to OpenAI if a call
# fails (e.g. DeepSeek 402 Insufficient Balance). Flip LLM_PROVIDER=deepseek/openai in .env.
LLM = {
    "provider": "deepseek",              # "deepseek" | "openai"  (env LLM_PROVIDER overrides)
    "deepseek_model": "deepseek-chat",
    "deepseek_base_url": "https://api.deepseek.com",
    "openai_model": "gpt-4o-mini",
    "fallback_to_openai": True,
    "temperature": 0.4,
}
