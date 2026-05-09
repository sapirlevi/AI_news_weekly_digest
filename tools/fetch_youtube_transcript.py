"""Pull transcripts for the top-N videos (by views) from youtube_videos.json.

Uses youtube-transcript-api (no API key). Missing transcripts are skipped.
"""
import sys

from util_io import TMP, read_json, write_json, now_utc

TOP_N = 8
MAX_CHARS = 8000


def main():
    data = read_json(TMP / "youtube_videos.json")
    videos = data.get("videos", [])
    if not videos:
        print("No videos to transcribe.")
        write_json(TMP / "transcripts.json",
                   {"generated_at": now_utc().isoformat(), "transcripts": []})
        return

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        print("ERROR: pip install youtube-transcript-api", file=sys.stderr)
        sys.exit(1)

    top = videos[:TOP_N]
    out = []
    for v in top:
        vid = v["videoId"]
        print(f"[{vid}] {v['title'][:70]}")
        try:
            fetched = YouTubeTranscriptApi().fetch(vid, languages=["en", "en-US", "en-GB"])
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
            print(f"  no transcript: {type(e).__name__}")

    write_json(TMP / "transcripts.json",
               {"generated_at": now_utc().isoformat(), "transcripts": out})
    print(f"Done. {len(out)} transcripts captured.")


if __name__ == "__main__":
    main()
