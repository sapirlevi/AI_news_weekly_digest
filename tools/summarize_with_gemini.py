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
  "trending_videos": [                          // 5-8 items
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
"""


def load_inputs():
    news = read_json(TMP / "provider_news.json")
    videos = read_json(TMP / "youtube_videos.json")
    transcripts = read_json(TMP / "transcripts.json")
    compact_videos = [{
        "videoId": v["videoId"], "title": v["title"], "channel": v["channel"],
        "views": v.get("views", 0), "publishedAt": v.get("publishedAt"),
        "description": (v.get("description") or "")[:300],
    } for v in videos.get("videos", [])]
    # Cap provider news to top 30 most recent items — 103 items is far more than needed
    all_news = news.get("items", [])
    top_news = sorted(all_news, key=lambda x: x.get("published") or "", reverse=True)[:30]
    return {
        "provider_news": top_news,
        "videos": compact_videos,
        "transcripts": transcripts.get("transcripts", []),
    }


def build_user_content(payload):
    return (
        "Here is this week's raw material. Produce the JSON digest per the system schema.\n\n"
        "=== PROVIDER NEWS ===\n"
        f"{json.dumps(payload['provider_news'], indent=2)[:15000]}\n\n"
        "=== YOUTUBE VIDEOS (ranked by views) ===\n"
        f"{json.dumps(payload['videos'], indent=2)[:10000]}\n\n"
        "=== VIDEO TRANSCRIPTS (top-N) ===\n"
        f"{json.dumps(payload['transcripts'], indent=2)[:30000]}\n"
    )


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
    digest["_meta"] = {"generated_at": now_utc().isoformat(), "usage": usage}
    write_json(TMP / "digest.json", digest)
    print(f"Done. model={usage['model']}  in={usage['prompt_tokens']}  out={usage['output_tokens']}")


if __name__ == "__main__":
    main()
