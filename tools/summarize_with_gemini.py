"""Synthesize the week's content into a structured digest using Gemini.

Uses the google-genai SDK with JSON response mode. Falls back to flash
if pro hits a quota / availability error.
"""
import json
import os
import sys

from util_io import TMP, read_json, write_json, load_env, now_utc

load_env()
MODELS = ["gemini-2.5-flash", "gemini-2.0-flash"]

SYSTEM_PROMPT = """You are an expert AI-industry analyst producing a weekly briefing for a busy QA leader who also vibe-codes.

Your job: synthesize provider news, YouTube videos, and video transcripts into a JSON digest that will be rendered as a slide deck.

Tone: concise, professional, no hype. Prioritize what's actually useful to a practitioner.

Output MUST be a single JSON object matching this schema exactly — no prose, no markdown fences:
{
  "executive_summary": [string, ...],           // 5 bullets, each <= 25 words
  "top_stories": [                              // 5-8 items, ranked by importance
    {"headline": str, "provider": str, "why_it_matters": str, "url": str}
  ],
  "trending_videos": [                          // 5-9 items, max 2 per channel, from at least 4 different creators when material allows
    {"title": str, "channel": str, "views": int, "key_takeaway": str, "videoId": str}
  ],
  "prompt_tips": [                              // 3-6 items distilled from transcripts
    {"tip": str, "source_channel": str, "example": str}
  ],
  "tools_setups": [                             // 3-6 items — hands-on recommendations
    {"tool_or_setup": str, "use_case": str, "source": str}
  ],
  "industry_signals": [                         // 3-5 short trend observations
    {"signal": str, "evidence": str}
  ]
}

Rules:
- Deduplicate across sources.
- Favor items genuinely relevant to someone shipping AI features in production, and to a hobbyist "vibe coder" exploring agents, prompts, and tooling.
- If a section has no strong material, return fewer items rather than padding.
- Never fabricate URLs or videoIds — use only what appears in the input data. If unsure, leave url/videoId as "".
- Trending videos: never include 3 or more videos from the same channel. Aim for at least 4 unique creators.
- Topic dedup: if two or more candidate videos cover substantially the same topic (same news event, same tool launch, same technique), keep only the one with the highest like_view_ratio and drop the others. Near-duplicates count as duplicates.
"""


def _like_view_ratio(v):
    views = v.get("views") or 0
    likes = v.get("likes") or 0
    return round(likes / views, 4) if views > 0 else 0.0


def load_inputs():
    news = read_json(TMP / "provider_news.json")
    videos = read_json(TMP / "youtube_videos.json")
    transcripts = read_json(TMP / "transcripts.json")

    raw_videos = videos.get("videos", [])

    # Pre-balance: group by channel, keep top 3 per channel ranked by like/view ratio.
    # This prevents high-volume channels from flooding Gemini's menu.
    by_channel = {}
    for v in raw_videos:
        by_channel.setdefault(v["channel"], []).append(v)
    balanced = []
    for ch_videos in by_channel.values():
        ch_videos.sort(key=_like_view_ratio, reverse=True)
        balanced.extend(ch_videos[:3])
    balanced.sort(key=lambda v: v.get("views", 0) or 0, reverse=True)

    compact_videos = [{
        "videoId": v["videoId"],
        "title": v["title"],
        "channel": v["channel"],
        "views": v.get("views", 0),
        "like_view_ratio": _like_view_ratio(v),
        "publishedAt": v.get("publishedAt"),
        "description": (v.get("description") or "")[:300],
    } for v in balanced]

    # Cap provider news to top 30 most recent items — 103 items is far more than needed
    all_news = news.get("items", [])
    top_news = sorted(all_news, key=lambda x: x.get("published") or "", reverse=True)[:30]
    return {
        "provider_news": top_news,
        "videos": compact_videos,
        "transcripts": transcripts.get("transcripts", []),
        "_balanced_pool": balanced,  # kept for post-cap backfill
    }


def build_user_content(payload):
    return (
        "Here is this week's raw material. Produce the JSON digest per the system schema.\n\n"
        "=== PROVIDER NEWS ===\n"
        f"{json.dumps(payload['provider_news'], indent=2)[:15000]}\n\n"
        "=== YOUTUBE VIDEOS (pre-balanced: top 3 per channel by like/view ratio, then sorted by views) ===\n"
        f"{json.dumps(payload['videos'], indent=2)[:10000]}\n\n"
        "=== VIDEO TRANSCRIPTS (top-N) ===\n"
        f"{json.dumps(payload['transcripts'], indent=2)[:30000]}\n"
    )


def enforce_channel_cap(digest, pool, max_per_channel=2, target=9):
    """Hard-cap trending_videos to max_per_channel per channel.

    If the cap prunes below `target`, backfill from the pre-balanced pool
    using unused videos from channels still under the cap, ranked by
    like/view ratio. Backfilled entries use their description as a
    placeholder key_takeaway.
    """
    seen_counts = {}
    kept = []
    dropped = 0
    for v in digest.get("trending_videos", []):
        ch = v.get("channel", "")
        if seen_counts.get(ch, 0) < max_per_channel:
            seen_counts[ch] = seen_counts.get(ch, 0) + 1
            kept.append(v)
        else:
            dropped += 1

    chosen_ids = {v.get("videoId") for v in kept}
    backfilled = 0
    if len(kept) < target:
        candidates = [
            v for v in pool
            if v.get("videoId") not in chosen_ids
            and seen_counts.get(v["channel"], 0) < max_per_channel
        ]
        candidates.sort(key=_like_view_ratio, reverse=True)
        for v in candidates:
            if len(kept) >= target:
                break
            ch = v["channel"]
            if seen_counts.get(ch, 0) >= max_per_channel:
                continue
            desc = (v.get("description") or "").strip()
            takeaway = desc[:160] if desc else v.get("title", "")
            kept.append({
                "videoId": v["videoId"],
                "title": v["title"],
                "channel": ch,
                "views": v.get("views", 0),
                "key_takeaway": takeaway,
            })
            seen_counts[ch] = seen_counts.get(ch, 0) + 1
            backfilled += 1

    digest["trending_videos"] = kept[:target]
    print(f"  trending_videos: kept {len(kept[:target])}, "
          f"dropped {dropped} over-cap, backfilled {backfilled}")


def call_gemini(payload):
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("ERROR: pip install google-genai", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY (or GOOGLE_API_KEY) not set in .env", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    user_content = build_user_content(payload)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        temperature=0.3,
    )

    def _send(model):
        return client.models.generate_content(
            model=model, contents=user_content, config=config,
        )

    import time
    models_to_try = MODELS
    resp, used = None, None
    for model in models_to_try:
        for attempt in range(3):
            try:
                resp = _send(model)
                used = model
                break
            except Exception as e:
                err = str(e)
                print(f"  {model} attempt {attempt+1} failed: {err[:120]}", file=sys.stderr)
                if "429" in err or "RESOURCE_EXHAUSTED" in err or "503" in err or "UNAVAILABLE" in err:
                    wait = 65 * (attempt + 1)  # must exceed 60s RPM window
                    print(f"  Waiting {wait}s before retry...", file=sys.stderr)
                    time.sleep(wait)
                else:
                    break  # non-retryable error, move to next model
        if resp is not None:
            break
    if resp is None:
        print("ERROR: all Gemini models exhausted after retries", file=sys.stderr)
        sys.exit(1)

    text = (resp.text or "").strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    digest = json.loads(text)
    usage_md = getattr(resp, "usage_metadata", None)
    usage = {
        "model": used,
        "prompt_tokens": getattr(usage_md, "prompt_token_count", None),
        "output_tokens": getattr(usage_md, "candidates_token_count", None),
        "total_tokens": getattr(usage_md, "total_token_count", None),
    }
    return digest, usage


def main():
    payload = load_inputs()
    digest, usage = call_gemini(payload)
    enforce_channel_cap(digest, payload["_balanced_pool"])
    digest["_meta"] = {"generated_at": now_utc().isoformat(), "usage": usage}
    write_json(TMP / "digest.json", digest)
    print(f"Done. model={usage['model']}  in={usage['prompt_tokens']}  out={usage['output_tokens']}")


if __name__ == "__main__":
    main()
