"""Fetch news items from major AI provider blogs.

Strategy:
  1. Prefer RSS when the provider offers one (free, reliable, structured).
  2. Fall back to Firecrawl for JS-heavy / unstructured provider sites.
     Firecrawl returns clean markdown which we parse for article links +
     dates. Requires FIRECRAWL_API_KEY in .env.

Any provider that fails is logged and skipped — the pipeline continues.
"""
import os
import re
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

import requests

from util_io import (CONFIG, TMP, read_json, write_json, load_env,
                     days_ago, parse_dt, now_utc, read_seen)

load_env()

HEADERS = {"User-Agent": "Mozilla/5.0 (AI-Weekly-Digest/1.0)"}
WINDOW = days_ago(7)
TIMEOUT = 30
MAX_ITEMS_PER_PROVIDER = 25
ISO_DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
MD_LINK_RE = re.compile(r"\[([^\]]{10,180})\]\((https?://[^\s)]+)\)")


def fetch_rss(url):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    items = []
    for item in root.iter("item"):
        items.append({
            "title": (item.findtext("title") or "").strip(),
            "url": (item.findtext("link") or "").strip(),
            "published": item.findtext("pubDate") or item.findtext(
                "{http://purl.org/dc/elements/1.1/}date"),
            "summary": (item.findtext("description") or "").strip()[:600],
        })
    ns = "{http://www.w3.org/2005/Atom}"
    for entry in root.iter(f"{ns}entry"):
        link_el = entry.find(f"{ns}link")
        items.append({
            "title": (entry.findtext(f"{ns}title") or "").strip(),
            "url": link_el.get("href") if link_el is not None else "",
            "published": entry.findtext(f"{ns}published") or entry.findtext(f"{ns}updated"),
            "summary": (entry.findtext(f"{ns}summary")
                        or entry.findtext(f"{ns}content") or "").strip()[:600],
        })
    return items


def fetch_firecrawl(url, api_key):
    """Scrape a page with Firecrawl, return parsed article-like links.

    Firecrawl returns clean markdown; we extract anchors that look like
    dated articles and attach the nearest ISO date we can find.
    """
    r = requests.post(
        "https://api.firecrawl.dev/v2/scrape",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"url": url, "formats": ["markdown"], "onlyMainContent": True},
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    md = (data.get("data") or {}).get("markdown") or data.get("markdown") or ""
    items, seen = [], set()
    for m in MD_LINK_RE.finditer(md):
        title, href = m.group(1).strip(), m.group(2).strip()
        if href in seen or not title or len(title) < 15:
            continue
        if not re.search(r"/(blog|news|research|post|article|hub|discover)/", href, re.I):
            continue
        # Look for a date within 200 chars of this link (before or after)
        window = md[max(0, m.start() - 200):m.end() + 200]
        date_match = ISO_DATE_RE.search(window)
        seen.add(href)
        items.append({
            "title": title,
            "url": urljoin(url, href),
            "published": date_match.group(1) if date_match else None,
            "summary": "",
        })
        if len(items) >= MAX_ITEMS_PER_PROVIDER:
            break
    return items


def within_window(item):
    dt = parse_dt(item.get("published"))
    if dt is None:
        return True  # keep when date unknown; summarizer filters semantically
    return dt >= WINDOW


def main():
    cfg = read_json(CONFIG / "youtube_channels.json")
    providers = cfg["providers"]
    firecrawl_key = os.environ.get("FIRECRAWL_API_KEY")
    seen_urls = read_seen()["provider_urls"]

    all_items, failures, total_skipped = [], [], 0
    for name, src in providers.items():
        print(f"[{name}]")
        try:
            if src.get("rss"):
                raw = fetch_rss(src["rss"])
                method = "rss"
            elif firecrawl_key:
                raw = fetch_firecrawl(src["homepage"], firecrawl_key)
                method = "firecrawl"
            else:
                raise RuntimeError("no RSS and FIRECRAWL_API_KEY not set — skipping")

            in_window = [i for i in raw if within_window(i) and i.get("title")]
            kept = [i for i in in_window if i.get("url") not in seen_urls]
            skipped = len(in_window) - len(kept)
            total_skipped += skipped
            for i in kept:
                i["provider"] = name
                i["source_method"] = method
            print(f"  [{method}] {len(kept)} item(s) in window (of {len(raw)} fetched, {skipped} already-delivered)")
            all_items.extend(kept)
        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr)
            failures.append({"provider": name, "error": str(e)})

    out = {
        "generated_at": now_utc().isoformat(),
        "window_start": WINDOW.isoformat(),
        "items": all_items,
        "failures": failures,
    }
    write_json(TMP / "provider_news.json", out)
    print(f"Done. {len(all_items)} items, {total_skipped} already-delivered skipped, "
          f"{len(failures)} provider(s) failed.")


if __name__ == "__main__":
    main()
