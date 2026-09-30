#!/usr/bin/env python3
"""Build the daily Global Agri & Bio-Economy Intelligence feed."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import requests
from dateutil import parser as date_parser


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = ROOT / "intelligence.json"
MAX_REPORTS = 80
MAX_AGE_DAYS = 30

SEARCHES = [
    ("India", "Activated Carbon, Charcoal & Biochar", "biochar India"),
    ("India", "Activated Carbon, Charcoal & Biochar", "\"activated carbon\" India"),
    ("India", "Biologicals & Microbial Crop Inputs", "\"agricultural biologicals\" India"),
    ("India", "Agri-Products & Agro-Processing", "\"agro processing\" India investment"),
    ("India", "Carbon Credits & Nursery Plantations", "\"carbon credits\" India agriculture"),
    ("Uganda", "Activated Carbon, Charcoal & Biochar", "biochar Uganda"),
    ("Uganda", "Agri-Products & Agro-Processing", "\"agro processing\" Uganda investment"),
    ("Uganda", "Agri-Products & Agro-Processing", "\"agriculture technology\" Uganda"),
    ("Uganda", "Carbon Credits & Nursery Plantations", "\"carbon credits\" Uganda forestry"),
    ("Rest of World", "Activated Carbon, Charcoal & Biochar", "biochar market acquisition"),
    ("Rest of World", "Activated Carbon, Charcoal & Biochar", "\"activated carbon\" investment"),
    ("Rest of World", "Biologicals & Microbial Crop Inputs", "\"agricultural biologicals\" funding acquisition"),
    ("Rest of World", "Agri-Products & Agro-Processing", "\"agro processing\" investment"),
    ("Rest of World", "Carbon Credits & Nursery Plantations", "\"carbon removal\" forestry investment"),
]

SECTOR_KEYWORDS = {
    "Activated Carbon, Charcoal & Biochar": [
        "activated carbon", "activated charcoal", "biochar", "charcoal",
        "pyrolysis", "carbonization", "carbonisation",
    ],
    "Biologicals & Microbial Crop Inputs": [
        "biologicals", "biostimulant", "biofertilizer", "biofertiliser",
        "microbial", "biopesticide", "crop input", "soil microbe",
    ],
    "Agri-Products & Agro-Processing": [
        "agro-processing", "agro processing", "food processing", "farm technology",
        "agritech", "agri-tech", "precision agriculture", "farm robot", "crop processing",
        "agricultural processing", "post-harvest", "post harvest", "agriculture",
        "agricultural", "farming", "farmers",
    ],
    "Carbon Credits & Nursery Plantations": [
        "carbon credit", "carbon market", "carbon removal", "afforestation",
        "reforestation", "nursery", "plantation", "tree planting", "nature-based",
    ],
}

THEME_KEYWORDS = {
    "deals": [
        "acquisition", "acquires", "merger", "joint venture", "partnership",
        "market entry", "strategic alliance", "stake in", "buyout",
    ],
    "capital": [
        "funding", "fundraise", "raises", "investment round", "debt", "loan",
        "investor", "financing", "capital raise", "series a", "series b",
    ],
    "regulatory": [
        "regulation", "policy", "government", "subsidy", "incentive", "compliance",
        "standard", "mandate", "tax", "ccts", "ministry", "legislation",
    ],
    "innovation": [
        "innovation", "technology", "launches", "pilot", "commercialize",
        "commercialise", "digital", "dmrv", "robot", "advanced", "new process",
    ],
}

PESTEL_KEYWORDS = {
    "Political": ["government", "ministry", "election", "public policy"],
    "Economic": ["market", "price", "trade", "export", "inflation", "demand"],
    "Social": ["farmer", "community", "livelihood", "employment", "smallholder"],
    "Technological": ["technology", "digital", "robot", "dmrv", "innovation"],
    "Environmental": ["climate", "emission", "soil", "forest", "sustainable", "carbon"],
    "Legal": ["regulation", "compliance", "law", "standard", "certification"],
}

BUSINESS_TERMS = [
    "company", "startup", "business", "market", "investment", "funding", "revenue",
    "commercial", "factory", "plant", "project", "export", "buyer", "contract",
    "policy", "regulation", "partnership", "acquisition", "technology",
    "innovat", "financ", "entrepreneur",
]

SIGNALS = {
    "regulatory": "Review eligibility, compliance timelines and incentive access before committing capital.",
    "deals": "Track counterparties, valuation signals and local market-access advantages created by the transaction.",
    "capital": "Compare the funding structure with project maturity, contracted demand and expected cash-flow timing.",
    "innovation": "Assess field performance, unit economics and the route from pilot deployment to repeatable commercial scale.",
    "pestel": "Monitor the development for changes to demand, operating risk, market access and investment timing.",
}


def clean_text(value: str | None) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalized_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def parse_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = date_parser.parse(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return datetime.now(timezone.utc)


def google_news_url(query: str, geography: str) -> str:
    if geography == "Uganda":
        locale = "hl=en-UG&gl=UG&ceid=UG:en"
    elif geography == "India":
        locale = "hl=en-IN&gl=IN&ceid=IN:en"
    else:
        locale = "hl=en-US&gl=US&ceid=US:en"
    return f"https://news.google.com/rss/search?q={quote_plus(query + ' when:7d')}&{locale}"


def fetch_google_news() -> list[dict]:
    candidates: list[dict] = []
    for geography, sector_hint, query in SEARCHES:
        feed = feedparser.parse(
            google_news_url(query, geography),
            agent="HuskAndFibre/1.0 (+https://github.com/)",
        )
        if getattr(feed, "bozo", False) and not feed.entries:
            print(f"  ! feed failed for {query}: {feed.bozo_exception}", file=sys.stderr)
            continue
        for entry in feed.entries[:15]:
            source = clean_text((entry.get("source") or {}).get("title")) or "Google News"
            headline = clean_text(entry.get("title"))
            suffix = f" - {source}"
            if source and headline.endswith(suffix):
                headline = headline[: -len(suffix)]
            candidates.append({
                "headline": headline,
                "summary": clean_text(entry.get("summary")),
                "url": entry.get("link", ""),
                "published": entry.get("published", ""),
                "source": source,
                "geography_hint": geography,
                "sector_hint": sector_hint,
            })
    return candidates


def fetch_newsapi() -> list[dict]:
    api_key = os.environ.get("NEWSAPI_KEY")
    if not api_key:
        return []
    candidates: list[dict] = []
    for geography, sector_hint, query in SEARCHES:
        try:
            response = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 10,
                    "searchIn": "title,description",
                },
                headers={"X-Api-Key": api_key},
                timeout=20,
            )
            response.raise_for_status()
        except requests.RequestException as error:
            print(f"  ! NewsAPI failed for {query}: {error}", file=sys.stderr)
            continue
        for article in response.json().get("articles", []):
            candidates.append({
                "headline": clean_text(article.get("title")),
                "summary": clean_text(article.get("description")),
                "url": article.get("url", ""),
                "published": article.get("publishedAt", ""),
                "source": clean_text((article.get("source") or {}).get("name")) or "NewsAPI",
                "geography_hint": geography,
                "sector_hint": sector_hint,
            })
    return candidates


def classify_sector(text: str) -> str | None:
    lowered = text.lower()
    scores = {
        sector: sum(keyword in lowered for keyword in keywords)
        for sector, keywords in SECTOR_KEYWORDS.items()
    }
    sector, score = max(scores.items(), key=lambda item: item[1])
    return sector if score else None


def classify_theme(text: str) -> str:
    lowered = text.lower()
    scores = {
        theme: sum(keyword in lowered for keyword in keywords)
        for theme, keywords in THEME_KEYWORDS.items()
    }
    theme, score = max(scores.items(), key=lambda item: item[1])
    return theme if score else "pestel"


def classify_geography(text: str, hint: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ["uganda", "kampala", "ugandan"]):
        return "Uganda"
    if any(term in lowered for term in ["india", "indian", "delhi", "mumbai", "bengaluru"]):
        return "India"
    return hint


def pestel_factors(text: str) -> list[str]:
    lowered = text.lower()
    return [
        factor
        for factor, keywords in PESTEL_KEYWORDS.items()
        if any(keyword in lowered for keyword in keywords)
    ][:4]


def relevance_score(text: str) -> int:
    lowered = text.lower()
    return sum(term in lowered for term in BUSINESS_TERMS)


def make_summary(candidate: dict, sector: str) -> str:
    summary = candidate["summary"]
    if summary and normalized_title(candidate["headline"]) not in normalized_title(summary):
        return summary[:420]
    return (
        f"This development affects the {sector.lower()} value chain. "
        "Open the original report for transaction details, timing and named counterparties."
    )


def to_report(candidate: dict) -> dict | None:
    if not candidate["headline"] or not candidate["url"]:
        return None
    text = f"{candidate['headline']} {candidate['summary']}"
    lowered = text.lower()
    hint = candidate["geography_hint"]
    if hint == "India" and not any(term in lowered for term in ["india", "indian"]):
        return None
    sector = classify_sector(text)
    if not sector or relevance_score(text) < 1:
        return None
    theme = classify_theme(text)
    published = parse_date(candidate["published"])
    if published < datetime.now(timezone.utc) - timedelta(days=10):
        return None
    cadence = "weekly" if theme == "pestel" else "daily"
    date_label = (
        f"Week {published.strftime('%V')} · {published.year}"
        if cadence == "weekly"
        else published.strftime("%d %b %Y")
    )
    identifier = hashlib.sha1(candidate["url"].encode("utf-8")).hexdigest()[:14]
    report = {
        "id": identifier,
        "cadence": cadence,
        "theme": theme,
        "geography": classify_geography(text, candidate["geography_hint"]),
        "sector": sector,
        "date": date_label,
        "published_at": published.isoformat(),
        "headline": candidate["headline"][:180],
        "summary": make_summary(candidate, sector),
        "signal": SIGNALS[theme],
        "source": candidate["source"],
        "source_url": candidate["url"],
    }
    factors = pestel_factors(text)
    if factors:
        report["pestel"] = factors
    return report


def load_existing() -> list[dict]:
    if not OUTPUT_FILE.exists():
        return []
    try:
        payload = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        return payload.get("reports", [])
    except (OSError, json.JSONDecodeError):
        return []


def existing_report_is_relevant(report: dict) -> bool:
    text = report.get("headline", "").lower()
    geography = report.get("geography")
    if geography == "India" and not any(term in text for term in ["india", "indian"]):
        return False
    return classify_sector(text) is not None


def run() -> int:
    print("Collecting daily intelligence...")
    candidates = fetch_google_news() + fetch_newsapi()
    print(f"  {len(candidates)} raw candidates")

    reports: list[dict] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for candidate in candidates:
        report = to_report(candidate)
        if not report:
            continue
        title_key = normalized_title(report["headline"])
        if report["source_url"] in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(report["source_url"])
        seen_titles.add(title_key)
        reports.append(report)

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    for report in load_existing():
        if not existing_report_is_relevant(report):
            continue
        url = report.get("source_url", "")
        title_key = normalized_title(report.get("headline", ""))
        published = parse_date(report.get("published_at"))
        if published < cutoff or url in seen_urls or title_key in seen_titles:
            continue
        reports.append(report)
        seen_urls.add(url)
        seen_titles.add(title_key)

    reports.sort(key=lambda report: parse_date(report.get("published_at")), reverse=True)
    reports = reports[:MAX_REPORTS]
    if not reports:
        print("No relevant intelligence found; existing feed was not replaced.", file=sys.stderr)
        return 1

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reports": reports,
    }
    OUTPUT_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(reports)} reports to {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
