"""Fetch videos uploaded in the last 7 days from each configured channel.

Uses YouTube Data API v3. Channel handle → channelId → uploads playlistId
is cached in .tmp/channel_id_cache.json so recurring runs cost almost
nothing quota-wise.
"""
import os
import re
import sys
from pathlib import Path

import requests

from util_io import (CONFIG, TMP, read_json, write_json,
                     load_env, days_ago, parse_dt, now_utc, read_seen)

load_env()
API_KEY = os.environ.get("YOUTUBE_API_KEY")
WINDOW = days_ago(7)
BASE = "https://www.googleapis.com/youtube/v3"
CACHE_PATH = TMP / "channel_id_cache.json"


def _get(path, **params):
    params["key"] = API_KEY
    r = requests.get(f"{BASE}/{path}", params=params, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"{path} -> {r.status_code}: {r.text[:300]}")
    return r.json()


def load_cache():
    if CACHE_PATH.exists():
        return read_json(CACHE_PATH)
    return {}


def handle_from_url(url):
    m = re.search(r"@([A-Za-z0-9_\-.]+)", url)
    return m.group(1) if m else None


def resolve_channel(handle, cache):
    if handle in cache:
        return cache[handle]
    data = _get("channels", part="snippet,contentDetails", forHandle=f"@{handle}")
    if not data.get("items"):
        raise RuntimeError(f"No channel found for @{handle}")
    item = data["items"][0]
    entry = {
        "channelId": item["id"],
        "title": item["snippet"]["title"],
        "uploadsPlaylistId": item["contentDetails"]["relatedPlaylists"]["uploads"],
    }
    cache[handle] = entry
    return entry


def fetch_recent_uploads(playlist_id, channel_title):
    items = []
    page_token = None
    while True:
        resp = _get("playlistItems", part="snippet,contentDetails",
                    playlistId=playlist_id, maxResults=20, pageToken=page_token or "")
        stop = False
        for it in resp.get("items", []):
            published = parse_dt(it["contentDetails"].get("videoPublishedAt")
                                 or it["snippet"].get("publishedAt"))
            if published is None:
                continue
            if published < WINDOW:
                stop = True
                continue
            sn = it["snippet"]
            items.append({
                "videoId": it["contentDetails"]["videoId"],
                "title": sn.get("title", ""),
                "description": (sn.get("description", "") or "")[:800],
                "channel": channel_title,
                "publishedAt": published.isoformat(),
                "thumbnailUrl": (sn.get("thumbnails", {}).get("high")
                                 or sn.get("thumbnails", {}).get("default") or {}).get("url", ""),
            })
        page_token = resp.get("nextPageToken")
        if stop or not page_token:
            break
    return items


def enrich_with_stats(videos):
    if not videos:
        return
    # videos.list accepts up to 50 ids per call
    for i in range(0, len(videos), 50):
        chunk = videos[i:i + 50]
        ids = ",".join(v["videoId"] for v in chunk)
        data = _get("videos", part="statistics,contentDetails", id=ids)
        by_id = {it["id"]: it for it in data.get("items", [])}
        for v in chunk:
            it = by_id.get(v["videoId"], {})
            stats = it.get("statistics", {})
            v["views"] = int(stats.get("viewCount", 0))
            v["likes"] = int(stats.get("likeCount", 0)) if "likeCount" in stats else None
            v["duration"] = it.get("contentDetails", {}).get("duration", "")


def main():
    if not API_KEY:
        print("ERROR: YOUTUBE_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    cfg = read_json(CONFIG / "youtube_channels.json")
    cache = load_cache()
    seen_ids = read_seen()["video_ids"]
    all_videos = []
    total_skipped = 0

    for url in cfg["channels"]:
        handle = handle_from_url(url)
        if not handle:
            print(f"  skipping unparseable URL: {url}", file=sys.stderr)
            continue
        print(f"[@{handle}]")
        try:
            ch = resolve_channel(handle, cache)
            videos = fetch_recent_uploads(ch["uploadsPlaylistId"], ch["title"])
            kept = [v for v in videos if v["videoId"] not in seen_ids]
            skipped = len(videos) - len(kept)
            total_skipped += skipped
            print(f"  {len(kept)} upload(s) in last 7 days ({skipped} already-delivered)")
            all_videos.extend(kept)
        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr)

    write_json(CACHE_PATH, cache)

    try:
        enrich_with_stats(all_videos)
    except Exception as e:
        print(f"  stats enrichment failed: {e}", file=sys.stderr)

    all_videos.sort(key=lambda v: v.get("views", 0), reverse=True)

    write_json(TMP / "youtube_videos.json", {
        "generated_at": now_utc().isoformat(),
        "window_start": WINDOW.isoformat(),
        "videos": all_videos,
    })
    print(f"Done. {len(all_videos)} videos across {len(cfg['channels'])} channels "
          f"({total_skipped} already-delivered skipped).")


if __name__ == "__main__":
    main()
