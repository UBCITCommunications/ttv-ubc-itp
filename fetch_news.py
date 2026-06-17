#!/usr/bin/env python3
"""
Fetches UBC IT news RSS feed, extracts the feature image and clean summary
from each item's description HTML, writes news.json.

The feed uses Drupal RSS where the standard <description> contains the full
HTML of the article — including a 'field-announcement-feature-image' div with
the hero image we want. No <media:content> or <enclosure>, so we parse it out.
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import requests


FEED_URL     = "https://it.ubc.ca/news/rss.xml"
MAX_ITEMS    = 8
MAX_AGE_DAYS = 90
SUMMARY_LEN  = 350

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0 Safari/537.36 UBC-Signage-Bot/1.0",
    "Accept": "application/rss+xml, application/xml, text/xml",
}


def extract_feature_image(html):
    """
    Pull the feature image URL out of the description HTML.
    The Drupal pattern wraps it in <div class="field--name-field-announcement-feature-image">.
    """
    # First try: scoped to the feature-image div
    pattern = (
        r'field--name-field-announcement-feature-image.*?'
        r'<img[^>]+src="(https?://[^"]+)"'
    )
    m = re.search(pattern, html, flags=re.DOTALL)
    if m:
        return m.group(1)

    # Fallback: any <img src=> pointing at /feature-images/
    m = re.search(r'<img[^>]+src="(https?://[^"]+/feature-images/[^"]+)"', html)
    if m:
        return m.group(1)

    return None


def strip_html(html):
    """Strip HTML tags + decode common entities + collapse whitespace."""
    if not html:
        return ""

    # Drop the title duplicate that Drupal includes at the start
    html = re.sub(
        r'<span class="field field--name-title[^"]*"[^>]*>.*?</span>',
        '', html, flags=re.DOTALL
    )
    # Drop the feature-image and meta blocks before we strip tags
    html = re.sub(
        r'<div class="field field--name-field-announcement-feature-image".*?</div>\s*</div>',
        '', html, flags=re.DOTALL
    )
    # Drop any "Feature Image" visually-hidden label
    html = re.sub(
        r'<div class="field__label visually-hidden"[^>]*>[^<]*</div>',
        '', html, flags=re.DOTALL
    )
    html = re.sub(
        r'<span class="field field--name-uid[^"]*"[^>]*>.*?</span>',
        '', html, flags=re.DOTALL
    )
    html = re.sub(
        r'<span class="field field--name-created[^"]*"[^>]*>.*?</span>',
        '', html, flags=re.DOTALL
    )

 # Remove iframes/scripts/style blocks
    html = re.sub(r'<(iframe|script|style)[^>]*>.*?</\1>', ' ', html, flags=re.DOTALL)
    # Collapse ordinal superscripts before stripping tags
    html = re.sub(r'(\d)<sup>(st|nd|rd|th)</sup>', r'\1\2', html, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r'<[^>]+>', ' ', html)

    # Decode entities we care about
    replacements = {
        '&nbsp;': ' ', '&amp;': '&', '&lt;': '<', '&gt;': '>',
        '&#8217;': '’', '&#8220;': '“', '&#8221;': '”',
        '&#8211;': '–', '&#8212;': '—', '&quot;': '"', '&apos;': "'",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    # Numeric entities
    text = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), text)

    # Collapse whitespace
    return re.sub(r'\s+', ' ', text).strip()


def truncate_at_word(s, max_len):
    if len(s) <= max_len:
        return s
    cut = s[:max_len]
    last_space = cut.rfind(' ')
    return cut[:last_space if last_space > 0 else max_len].rstrip() + '…'


def main():
    print(f"Fetching {FEED_URL}")
    r = requests.get(FEED_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()

    # Parse RSS XML
    root = ET.fromstring(r.content)
    channel = root.find('channel')
    if channel is None:
        print("ERROR: no <channel> in feed", file=sys.stderr)
        sys.exit(1)

    items_raw = channel.findall('item')
    print(f"Feed has {len(items_raw)} items")

    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(days=MAX_AGE_DAYS)

    items = []
    for it in items_raw:
        title       = (it.findtext('title')       or '').strip()
        link        = (it.findtext('link')        or '').strip()
        description = (it.findtext('description') or '')
        pub_raw     = (it.findtext('pubDate')     or '').strip()

        # Parse pubDate
        try:
            pub_dt = parsedate_to_datetime(pub_raw)
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        except Exception:
            print(f"  skipping (bad pubDate): {title!r}")
            continue

        # Age filter
        if pub_dt < cutoff:
            print(f"  skipping (older than {MAX_AGE_DAYS}d): {title!r}")
            continue

        image = extract_feature_image(description)
        if not image:
            print(f"  skipping (no image): {title!r}")
            continue

        summary = truncate_at_word(strip_html(description), SUMMARY_LEN)

        items.append({
            "title":   title,
            "link":    link,
            "image":   image,
            "pub_iso": pub_dt.isoformat(),
            "summary": summary,
        })

        if len(items) >= MAX_ITEMS:
            break

    out = {
        "generated_at": now_utc.isoformat(),
        "count":        len(items),
        "items":        items,
    }

    with open('news.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(items)} items to news.json")


if __name__ == '__main__':
    main()
