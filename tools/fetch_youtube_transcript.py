"""Pull transcripts for the top-N videos (by views) from youtube_videos.json.

Uses youtube-transcript-api (no API key). Missing transcripts are skipped.
Set YOUTUBE_COOKIES env var to the contents of a Netscape-format cookies.txt
to bypass IP-based blocking in cloud environments.
"""
import os
import sys
import tempfile

from util_io import TMP, read_json, write_json, now_utc

TOP_N = 8
MAX_CHARS = 8000


def _build_session():
    """Return a requests.Session with YouTube cookies loaded, or a plain Session."""
    from requests import Session
    session = Session()
    content = os.environ.get("YOUTUBE_COOKIES", "").strip()
    if not content:
        return session, False
    # Write to a temp file so MozillaCookieJar can parse the Netscape format
    from http.cookiejar import MozillaCookieJar
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    f.write(content)
    f.close()
    jar = MozillaCookieJar()
    jar.load(f.name, ignore_discard=True, ignore_expires=True)
    session.cookies = jar
    return session, True


def main():
    data = read_json(TMP / "youtube_videos.json")
    videos = data.get("videos", [])
    if not videos:
        print("No videos to transcribe.")
        write_json(TMP / "transcripts.json",
                   {"generated_at": now_utc().isoformat(), "transcripts": [], "blocked": False})
        return

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        print("ERROR: pip install youtube-transcript-api", file=sys.stderr)
        sys.exit(1)

    session, has_cookies = _build_session()
    if has_cookies:
        print("  using YouTube cookies for auth")
    else:
        print("  no YOUTUBE_COOKIES set — running unauthenticated (may be blocked in cloud)")

    api = YouTubeTranscriptApi(http_client=session)

    top = videos[:TOP_N]
    out = []
    blocked_count = 0
    for v in top:
        vid = v["videoId"]
        print(f"[{vid}] {v['title'][:70]}")
        try:
            fetched = api.fetch(vid, languages=["en", "en-US", "en-GB"])
            parts = []
            last_marker = -1e9
            for snip in fetched:
                if not snip.text:
                    continue
                start = float(getattr(snip, "start", 0) or 0)
                if start - last_marker >= 30:
                    parts.append(f"[t={int(start)}s]")
                    last_marker = start
                parts.append(snip.text)
            text = " ".join(parts).strip()
            if not text:
                print("  empty transcript, skipping")
                continue
            if len(text) > MAX_CHARS:
                text = text[:MAX_CHARS] + "…"
            out.append({
                "videoId": vid,
                "title": v["title"],
                "channel": v["channel"],
                "views": v.get("views", 0),
                "transcript": text,
            })
        except Exception as e:
            err_name = type(e).__name__
            print(f"  no transcript: {err_name}")
            if "RequestBlocked" in err_name or "blocked" in str(e).lower():
                blocked_count += 1

    all_blocked = blocked_count > 0 and len(out) == 0
    write_json(TMP / "transcripts.json",
               {"generated_at": now_utc().isoformat(), "transcripts": out,
                "blocked": all_blocked})
    if all_blocked:
        print("  ⚠ ALL transcripts blocked — YouTube cookies may have expired")
    print(f"Done. {len(out)} transcripts captured.")


if __name__ == "__main__":
    main()
