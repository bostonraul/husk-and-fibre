#!/usr/bin/env python3
"""Send mapped Soul Agri intelligence briefings through Resend."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from pathlib import Path
from urllib.parse import quote

import requests
from dateutil import parser as date_parser


ROOT = Path(__file__).resolve().parents[1]
FEED_FILE = ROOT / "intelligence.json"
LOCAL_SUBSCRIBERS = ROOT / "subscribers.json"
RESEND_URL = "https://api.resend.com/emails"
SITE_URL = "https://bostonraul.github.io/husk-and-fibre/"

SEGMENT_ALIASES = {
    "all": "all",
    "biochar": "biochar",
    "activated-carbon": "biochar",
    "activated carbon": "biochar",
    "bbm": "bbm",
    "bio-based": "bbm",
    "bio-based materials": "bbm",
    "microbial": "microbial",
    "biofertilizers": "microbial",
    "biofertiliser": "microbial",
    "biologicals": "microbial",
    "carbon-credit": "carbon-credits",
    "carbon-credits": "carbon-credits",
    "carbon credit": "carbon-credits",
    "agro-products": "agro-processing",
    "agro-product": "agro-processing",
    "agro-processing": "agro-processing",
    "agro processing": "agro-processing",
    "regenerative": "regenerative",
    "regenerative farming": "regenerative",
    "permaculture": "agroforestry",
    "agroforestry": "agroforestry",
    "innovations": "innovations",
    "innovation": "innovations",
    "new-launches": "innovations",
    "new launches": "innovations",
}

GEOGRAPHY_ALIASES = {
    "all": "All",
    "india": "India",
    "uganda": "Uganda",
    "world": "Rest of World",
    "rest of world": "Rest of World",
    "rest of the world": "Rest of World",
    "global": "Rest of World",
}


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


def load_feed() -> dict:
    payload = json.loads(FEED_FILE.read_text(encoding="utf-8"))
    if not isinstance(payload.get("reports"), list):
        raise ValueError("intelligence.json is missing reports")
    return payload


def load_subscribers() -> list[dict]:
    raw = os.environ.get("SUBSCRIBERS_JSON", "").strip()
    if raw:
        data = json.loads(raw)
    elif LOCAL_SUBSCRIBERS.exists():
        data = json.loads(LOCAL_SUBSCRIBERS.read_text(encoding="utf-8"))
    else:
        return []
    if isinstance(data, dict):
        data = data.get("subscribers", [])
    if not isinstance(data, list):
        raise ValueError("Subscriber list must be a JSON array")
    return [normalize_subscriber(item) for item in data if normalize_subscriber(item)]


def normalize_subscriber(item: dict) -> dict | None:
    _, email = parseaddr(str(item.get("email", "")).strip())
    if "@" not in email or "." not in email.split("@")[-1]:
        return None
    cadence = str(item.get("cadence", "weekly")).strip().lower()
    if cadence not in {"daily", "weekly"}:
        cadence = "weekly"
    geographies = {
        GEOGRAPHY_ALIASES.get(str(value).strip().lower(), str(value).strip())
        for value in item.get("geographies", ["All"])
    }
    if not geographies or "All" in geographies:
        geographies = {"All"}
    segments = {
        SEGMENT_ALIASES.get(str(value).strip().lower(), str(value).strip().lower())
        for value in item.get("segments", ["all"])
    }
    if not segments or "all" in segments:
        segments = {"all"}
    return {
        "email": email,
        "name": str(item.get("name") or "").strip(),
        "cadence": cadence,
        "geographies": geographies,
        "segments": segments,
    }


def report_segment(report: dict) -> str:
    return str(report.get("segment") or SEGMENT_ALIASES.get(
        str(report.get("sector", "")).strip().lower(), ""
    ))


def matches_subscriber(report: dict, subscriber: dict) -> bool:
    geography = report.get("geography")
    if "All" not in subscriber["geographies"] and geography not in subscriber["geographies"]:
        return False
    if "all" in subscriber["segments"]:
        return True
    return report_segment(report) in subscriber["segments"]


def select_reports(reports: list[dict], subscriber: dict, cadence: str) -> list[dict]:
    now = datetime.now(timezone.utc)
    window = timedelta(days=3) if cadence == "daily" else timedelta(days=8)
    matched = [report for report in reports if matches_subscriber(report, subscriber)]
    matched.sort(key=lambda item: parse_date(item.get("published_at")), reverse=True)
    recent = [
        report for report in matched
        if parse_date(report.get("published_at")) >= now - window
    ]
    if recent:
        return recent[:12]
    # Quiet window: still send the latest matching items so a first run is not empty.
    return matched[:8]


def synopsis_text(reports: list[dict], cadence: str) -> str:
    geos = sorted({item.get("geography", "Market") for item in reports})
    sectors = sorted({item.get("sector", "sector") for item in reports})
    horizon = "the past day" if cadence == "daily" else "this week"
    return (
        f"{len(reports)} {cadence} signals from {horizon} across "
        f"{', '.join(geos)} covering {', '.join(sectors[:4])}."
    )


def escape(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def unsubscribe_url(email: str) -> str:
    return f"{SITE_URL}unsubscribe.html?email={quote(email)}"


def render_email(subscriber: dict, reports: list[dict], cadence: str, from_email: str) -> tuple[str, str, str]:
    greeting = subscriber["name"] or "there"
    unsub = unsubscribe_url(subscriber["email"])
    mailto_unsub = (
        f"mailto:{from_email}?subject=Unsubscribe%20Soul%20Agri%20briefing"
        f"&body=Please%20unsubscribe%20{quote(subscriber['email'])}"
    )
    subject = (
        f"Soul Agri {'daily' if cadence == 'daily' else 'weekly'} intelligence"
        f" · {datetime.now(timezone.utc).strftime('%d %b %Y')}"
    )
    grouped: dict[str, list[dict]] = defaultdict(list)
    for report in reports:
        grouped[report.get("geography") or "Markets"].append(report)

    blocks = []
    for geography, items in grouped.items():
        cards = "".join(
            f"""
            <tr>
              <td style="padding:0 0 18px;">
                <div style="font:500 11px/1 DM Mono,ui-monospace,monospace;letter-spacing:.06em;text-transform:uppercase;color:#C96B4F;">
                  {escape(item.get("sector"))} · {escape(item.get("date"))}
                </div>
                <h3 style="margin:8px 0 6px;font:600 18px/1.25 Newsreader,Georgia,serif;color:#3A2A24;">
                  {escape(item.get("headline"))}
                </h3>
                <p style="margin:0 0 8px;font:400 14px/1.55 Instrument Sans,Arial,sans-serif;color:#7A5C52;">
                  {escape(item.get("summary"))}
                </p>
                <a href="{escape(item.get("source_url"))}" style="color:#8E4334;font:500 13px/1 Instrument Sans,Arial,sans-serif;">
                  {escape(item.get("source"))} ↗
                </a>
              </td>
            </tr>
            """
            for item in items
        )
        blocks.append(
            f"""
            <tr><td style="padding:22px 0 8px;font:600 13px/1 Instrument Sans,Arial,sans-serif;color:#8E4334;text-transform:uppercase;letter-spacing:.08em;">{escape(geography)}</td></tr>
            {cards}
            """
        )

    html = f"""
    <div style="margin:0;padding:28px 16px;background:#F7EDE6;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;margin:0 auto;background:#FFF8F3;border:1px solid #E5CABB;border-radius:18px;">
        <tr>
          <td style="padding:28px 28px 18px;">
            <a href="{SITE_URL}" style="display:inline-block;font:500 11px/1 DM Mono,ui-monospace,monospace;letter-spacing:.08em;text-transform:uppercase;color:#C96B4F;text-decoration:none;">Soul Agri – Husk &amp; Fibre</a>
            <div style="margin:8px 0 0;">
              <a href="{SITE_URL}" style="font:500 13px/1.4 Instrument Sans,Arial,sans-serif;color:#8E4334;">Visit the website ↗</a>
            </div>
            <h1 style="margin:14px 0 8px;font:600 28px/1.1 Newsreader,Georgia,serif;color:#3A2A24;">
              {cadence.title()} intelligence briefing
            </h1>
            <p style="margin:0;font:400 15px/1.55 Instrument Sans,Arial,sans-serif;color:#7A5C52;">
              Hello {escape(greeting)}, {escape(synopsis_text(reports, cadence))}
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:0 28px 10px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{''.join(blocks)}</table>
          </td>
        </tr>
        <tr>
          <td style="padding:8px 28px 28px;font:400 12px/1.5 Instrument Sans,Arial,sans-serif;color:#7A5C52;">
            You receive this because you were added to the Soul Agri mapped briefing list.
            <a href="{SITE_URL}" style="color:#8E4334;">Open the live intelligence desk</a>.
            <div style="margin-top:14px;padding-top:14px;border-top:1px solid #E5CABB;">
              Soul Agri – Husk &amp; Fibre ·
              <a href="{unsub}" style="color:#8E4334;">Unsubscribe</a>
              ·
              <a href="{mailto_unsub}" style="color:#8E4334;">Email us to stop</a>
            </div>
          </td>
        </tr>
      </table>
    </div>
    """
    text_lines = [
        "Soul Agri – Husk & Fibre",
        f"{cadence.title()} intelligence briefing",
        "",
        f"Hello {greeting}, {synopsis_text(reports, cadence)}",
        f"Website: {SITE_URL}",
        "",
    ]
    for geography, items in grouped.items():
        text_lines.append(geography.upper())
        for item in items:
            text_lines.extend([
                f"- {item.get('headline')}",
                f"  {item.get('summary')}",
                f"  {item.get('source_url')}",
                "",
            ])
    text_lines.extend([
        "You receive this because you were added to the Soul Agri mapped briefing list.",
        f"Unsubscribe: {unsub}",
    ])
    return subject, html, "\n".join(text_lines)


def sanitize_from_address(value: str) -> str:
    cleaned = value.strip().strip('"').strip("'").replace("\r", " ").replace("\n", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    _, email = parseaddr(cleaned)
    if "@" in email and "." in email.split("@")[-1]:
        return cleaned
    raise ValueError(
        "RESEND_FROM is not a valid sender. Use either "
        "`briefings@yourdomain.com` or `Soul Agri <briefings@yourdomain.com>` "
        "with no extra quotes."
    )


def send_email(
    api_key: str,
    from_address: str,
    from_email: str,
    to_address: str,
    subject: str,
    html: str,
    text: str,
) -> None:
    unsub = unsubscribe_url(to_address)
    response = requests.post(
        RESEND_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": from_address,
            "to": [to_address],
            "reply_to": from_email,
            "subject": subject,
            "html": html,
            "text": text,
            "headers": {
                "List-Unsubscribe": f"<mailto:{from_email}?subject=unsubscribe>, <{unsub}>",
                "List-Id": "<briefings.soul-agri.husk-and-fibre>",
            },
            "tags": [
                {"name": "cadence", "value": "briefing"},
            ],
        },
        timeout=30,
    )
    if response.status_code >= 300:
        raise RuntimeError(f"Resend rejected {mask_email(to_address)}: {response.status_code} {response.text}")


def mask_email(value: str) -> str:
    name, _, domain = value.partition("@")
    return f"{name[:1]}***@{domain}" if domain else "***"


def run() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cadence", choices=("daily", "weekly"), default="weekly")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    feed = load_feed()
    subscribers = [item for item in load_subscribers() if item["cadence"] == args.cadence]
    if not subscribers:
        print(f"No {args.cadence} subscribers configured.")
        return 0

    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    raw_from = os.environ.get("RESEND_FROM", "").strip()
    if not args.dry_run and (not api_key or not raw_from):
        print("RESEND_API_KEY and RESEND_FROM are required to send mail.", file=sys.stderr)
        return 1
    try:
        from_address = sanitize_from_address(raw_from) if raw_from else ""
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    from_email = parseaddr(from_address)[1] if from_address else "briefings@localhost"
    if from_address:
        print(f"Sending as {mask_email(from_email)}")

    sent = 0
    skipped = 0
    for subscriber in subscribers:
        reports = select_reports(feed["reports"], subscriber, args.cadence)
        if not reports:
            skipped += 1
            print(f"  skip {mask_email(subscriber['email'])}: no reports match this geography/segments")
            continue
        subject, html, text = render_email(subscriber, reports, args.cadence, from_email)
        print(f"  {args.cadence} {mask_email(subscriber['email'])}: {len(reports)} reports")
        if not args.dry_run:
            send_email(api_key, from_address, from_email, subscriber["email"], subject, html, text)
            time.sleep(0.4)
        sent += 1

    print(f"{'Prepared' if args.dry_run else 'Sent'} {sent} {args.cadence} briefings; skipped {skipped}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
