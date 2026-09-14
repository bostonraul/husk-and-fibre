#!/usr/bin/env python3
"""
Husk & Fibre — automated ingestion pipeline
============================================
Runs on a schedule (cron / GitHub Actions) with NO human review step.
It pulls fresh stories about agro-waste materials & products, scores
them for "business potential", finds a matching official video, and
writes the results into data.json for the website to render.

WHAT THIS DOES NOT DO (by design, and why):
  - It does NOT download video files from YouTube or Instagram.
    Scraping/downloading video off those platforms breaks their
    Terms of Service and creators' copyright, even for a personal
    dashboard. Instead it stores the official YouTube video ID and
    the site embeds YouTube's own player (iframe) — fully legal,
    the creator keeps their views, and it's genuinely more reliable
    than a downloaded file that can go stale or get taken down.
  - It does NOT auto-publish without any check at all. "Fully
    automated" here means no human has to read and approve each
    item before it goes live — but a lightweight, code-based
    relevance filter still runs (keyword + material match) so the
    feed doesn't fill with unrelated news. That filter is code, not
    a person, so the "no human step" requirement is met.

SOURCES USED
  1. NewsAPI / GNews (or any news API) — general news search
  2. RSS feeds from Down To Earth, The Better India, Mongabay-India,
     Circularity focused trade press — no API key required
  3. YouTube Data API v3 — search for a matching official video for
     each story, so every entry gets *a* video, not a downloaded one

SETUP
  pip install feedparser requests python-dateutil --break-system-packages
  export NEWSAPI_KEY=...      # https://newsapi.org (optional)
  export YOUTUBE_API_KEY=...  # https://console.cloud.google.com -> YouTube Data API v3
  python scrape_and_score.py

SCHEDULING (pick one)
  - GitHub Actions: .github/workflows/refresh.yml (cron: '0 */6 * * *')
    then `git commit` the updated data.json and let GitHub Pages serve it.
  - A cheap always-on box / Render/Railway cron job running this on a timer.
  - crontab -e  ->  0 */6 * * *  cd /path/to/agrofeed && python3 pipeline/scrape_and_score.py
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import feedparser
import requests

# ---------------------------------------------------------------------------
# 1. CONFIG — the materials this feed cares about, and how to recognise them
# ---------------------------------------------------------------------------

MATERIAL_KEYWORDS = {
    "Coconut":  ["coconut", "coir", "copra", "areca"],
    "Banana":   ["banana fiber", "banana fibre", "banana stem", "banana pseudostem"],
    "Bamboo":   ["bamboo"],
    "Palm":     ["palm leaf", "palm frond", "date palm", "areca leaf", "palm strand"],
    "Mango":    ["mango pulp", "mango leather", "mango waste"],
    "Grass / Straw": ["rice straw", "wheat straw", "sugarcane bagasse", "paddy straw", "grass fibre"],
}

BUSINESS_SIGNAL_WORDS = [
    "startup", "business", "market", "export", "revenue", "turnover",
    "manufactur", "factory", "investment", "profit", "entrepreneur",
    "scale", "demand", "supply chain", "commercializ", "commercialis",
]

# Free, no-key-required RSS feeds that regularly cover this beat.
RSS_FEEDS = [
    "https://www.downtoearth.org.in/rss/environment",
    "https://thebetterindia.com/feed/",
    "https://india.mongabay.com/feed/",
]

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data.json")


# ---------------------------------------------------------------------------
# 2. COLLECT — pull raw candidate stories
# ---------------------------------------------------------------------------

def fetch_rss_candidates():
    candidates = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"  ! could not read {url}: {e}", file=sys.stderr)
            continue
        for entry in feed.entries[:40]:
            candidates.append({
                "headline": entry.get("title", ""),
                "summary": re.sub("<[^<]+?>", "", entry.get("summary", "")),
                "url": entry.get("link", ""),
                "published": entry.get("published", ""),
                "source": feed.feed.get("title", url),
            })
    return candidates


def fetch_newsapi_candidates(query):
    api_key = os.environ.get("NEWSAPI_KEY")
    if not api_key:
        return []
    try:
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={"q": query, "language": "en", "sortBy": "publishedAt", "pageSize": 20},
            headers={"X-Api-Key": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
    except Exception as e:
        print(f"  ! NewsAPI query '{query}' failed: {e}", file=sys.stderr)
        return []
    return [
        {
            "headline": a.get("title", ""),
            "summary": a.get("description") or "",
            "url": a.get("url", ""),
            "published": a.get("publishedAt", ""),
            "source": (a.get("source") or {}).get("name", "news"),
        }
        for a in articles
    ]


# ---------------------------------------------------------------------------
# 3. FILTER + TAG — code-based relevance check (this is the "no human" gate)
# ---------------------------------------------------------------------------

def tag_material(text):
    text_lower = text.lower()
    for material, keywords in MATERIAL_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return material
    return None


def business_signal_score(text):
    text_lower = text.lower()
    hits = sum(1 for w in BUSINESS_SIGNAL_WORDS if w in text_lower)
    return min(5, 1 + hits)  # 1..5 scale, purely heuristic — refine with real modelling later


def relevant_and_scored(candidate):
    joined = f"{candidate['headline']} {candidate['summary']}"
    material = tag_material(joined)
    if not material:
        return None
    candidate["material"] = material
    candidate["potential_score"] = business_signal_score(joined)
    return candidate


# ---------------------------------------------------------------------------
# 4. FIND A VIDEO — official YouTube search, never a downloaded file
# ---------------------------------------------------------------------------

def find_youtube_video(query):
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        return None
    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": 1,
                "order": "relevance",
                "key": api_key,
            },
            timeout=15,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if items:
            return items[0]["id"]["videoId"]
    except Exception as e:
        print(f"  ! YouTube search failed for '{query}': {e}", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# 5. WRITE — merge into data.json, newest first, de-duplicated by URL
# ---------------------------------------------------------------------------

def load_existing():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"generated_at": "", "stories": []}


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def run():
    print("Collecting candidates...")
    candidates = fetch_rss_candidates()
    for material_kw in ["coconut business India", "banana fiber startup",
                         "bamboo plastic substitute", "palm leaf products business",
                         "mango leather startup"]:
        candidates += fetch_newsapi_candidates(material_kw)

    print(f"  {len(candidates)} raw candidates collected")

    existing = load_existing()
    known_urls = {s.get("source_url") for s in existing["stories"] if s.get("source_url")}

    new_stories = []
    for c in candidates:
        if c["url"] in known_urls:
            continue
        scored = relevant_and_scored(c)
        if not scored:
            continue
        video_id = find_youtube_video(f"{scored['material']} {scored['headline']}")
        new_stories.append({
            "id": slugify(scored["headline"]) or slugify(scored["url"]),
            "material": scored["material"],
            "region": "Unspecified — refine with NER in a later pass",
            "headline": scored["headline"],
            "dek": scored["summary"][:180],
            "potential_score": scored["potential_score"],
            "potential_label": ["", "Low", "Fair", "Moderate", "High", "Very High"][scored["potential_score"]],
            "capital_note": "Not yet assessed",
            "video_youtube": video_id,
            "video_caption": "Auto-matched video — verify relevance before featuring prominently",
            "body": scored["summary"],
            "why_it_matters": "Auto-generated entry — pipeline flagged this via keyword + business-signal scoring.",
            "source_url": c["url"],
            "sources": [{"name": scored.get("source", "source"), "url": c["url"]}],
        })

    print(f"  {len(new_stories)} passed the relevance filter and are new")

    existing["stories"] = new_stories + existing["stories"]
    existing["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(existing['stories'])} total stories to {DATA_FILE}")


if __name__ == "__main__":
    run()
