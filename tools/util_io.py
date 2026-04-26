"""Shared IO helpers used by every tool in the WAT pipeline."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = ROOT / ".tmp"
CONFIG = ROOT / "config"
SEEN_PATH = TMP / "seen.json"
SEEN_CAP = 500
TMP.mkdir(exist_ok=True)


def read_json(path):
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    print(f"  wrote {p.relative_to(ROOT)}")


def load_env():
    """Minimal .env loader — avoids the python-dotenv dependency."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def now_utc():
    return datetime.now(timezone.utc)


def days_ago(n):
    from datetime import timedelta
    return now_utc() - timedelta(days=n)


def read_seen():
    """Return previously-delivered IDs as sets. Tolerates a missing file."""
    if not SEEN_PATH.exists():
        return {"provider_urls": set(), "video_ids": set()}
    data = read_json(SEEN_PATH)
    return {
        "provider_urls": set(data.get("provider_urls") or []),
        "video_ids": set(data.get("video_ids") or []),
    }


def commit_seen(urls=None, video_ids=None):
    """Append new IDs to .tmp/seen.json, FIFO-capped at SEEN_CAP per list."""
    existing = read_json(SEEN_PATH) if SEEN_PATH.exists() else {}
    prev_urls = list(existing.get("provider_urls") or [])
    prev_vids = list(existing.get("video_ids") or [])

    def _merge(prev, new):
        seen = set(prev)
        merged = list(prev)
        for x in (new or []):
            if x and x not in seen:
                merged.append(x)
                seen.add(x)
        return merged[-SEEN_CAP:]

    write_json(SEEN_PATH, {
        "last_updated": now_utc().isoformat(),
        "provider_urls": _merge(prev_urls, urls),
        "video_ids": _merge(prev_vids, video_ids),
    })


def parse_dt(s):
    """Parse ISO-ish datetime from feeds / APIs into a tz-aware UTC datetime."""
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    if not s:
        return None
    s = str(s).strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
