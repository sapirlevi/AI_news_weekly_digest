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
  "tools_and_tips": [                           // 12-15 candidate items — strict downstream validation keeps only verifiably-grounded actionable tips, so OVER-produce here. Final slide shows 4-8 survivors.
    {"title": str, "what": str, "source": str, "url": str}
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
- top_stories items MUST use article URLs from provider_news — NEVER use a YouTube URL in a top_stories url field.
- Trending videos: never include 3 or more videos from the same channel. Aim for at least 4 unique creators.
- Topic dedup: if two or more candidate videos cover substantially the same topic (same news event, same tool launch, same technique), keep only the one with the highest like_view_ratio and drop the others. Near-duplicates count as duplicates.

Rules specific to tools_and_tips:
- Produce 12–15 candidate items. Strict downstream validation will keep only those whose deep-link is verifiably grounded in the input transcript/body. OVER-produce; do not under-produce.
- This is ONE merged chapter — do NOT emit duplicates. If a "tool" and a "prompt tip" describe the same underlying thing (same skill, same framework, same product), emit it ONCE.
- Each item's "title" must be unique within tools_and_tips.
- Drop any candidate whose source content is not clearly about AI, LLMs, agents, prompting, or AI tooling. Generic productivity, gardening, lifestyle, side-hustle, or unrelated programming content must NOT appear.
- A "tip" is an actionable recipe — a specific tool, prompt, configuration, or workflow the reader can try. Examples of GOOD tips:
    * "Use Claude Code's skill-creator skill to bootstrap reusable instruction bundles"
    * "Combine Higgsfield with Claude Code for generative-image workflows"
    * "Add output_style: report to your AGENTS.md for structured replies"
- A "tip" is NOT a news headline. REJECT items like "OpenAI launches GPT-5" or "Anthropic raises $X" — those belong in top_stories. The "what" field must describe HOW to do something, not WHAT happened.
- Every item MUST have a non-empty "url" that is a clickable deep-link to the EXACT place the tip is mentioned:
    * If the tip is distilled from a YouTube transcript:
        - format: "https://youtu.be/{videoId}?t={N}"
        - {videoId} must appear in the input data
        - {N} = integer copied EXACTLY from a "[t=Ns]" marker in the transcript that appears just BEFORE the relevant content. Do NOT invent N.
        - Example: tip mentioned right after "[t=180s]" in video "abc123" → "https://youtu.be/abc123?t=180"
    * If the tip is distilled from an article (provider news):
        - format: "{article_url}#:~:text={encoded_phrase}"
        - {article_url} must be the article URL from the input data
        - {encoded_phrase} = a 4–10 word distinctive verbatim phrase copied EXACTLY from the immediate paragraph that DESCRIBES THE TIP (not intro/conclusion/sidebar text), then URL-encoded. The phrase MUST be a contiguous substring of the body — do not paraphrase.
        - Example: body contains "Webhooks deliver push-based notifications instead of polling" → url: "https://blog.google/.../event-driven-webhooks/#:~:text=push-based%20notifications%20instead%20of%20polling"
        - If the article has no body in the input data, do NOT use it as a tip source — pick a different source instead.
- Never invent a videoId, an article URL, a phrase, or a timestamp. If you cannot identify a valid grounded source for a candidate tip, drop the tip rather than guessing.
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

    compact_videos_raw = [{
        "videoId": v["videoId"],
        "title": v["title"],
        "channel": v["channel"],
        "views": v.get("views", 0),
        "like_view_ratio": _like_view_ratio(v),
        "publishedAt": v.get("publishedAt"),
        "description": (v.get("description") or "")[:300],
    } for v in balanced]

    # Topic filter: keep only AI-relevant videos
    compact_videos = [v for v in compact_videos_raw
                      if _is_ai_relevant(v["title"], v["description"])]
    dropped_v = len(compact_videos_raw) - len(compact_videos)

    # Cap provider news to top 30 most recent items — 103 items is far more than needed
    all_news = news.get("items", [])
    sorted_news = sorted(all_news, key=lambda x: x.get("published") or "", reverse=True)[:30]
    top_news = [n for n in sorted_news
                if _is_ai_relevant(n.get("title"), n.get("summary"), n.get("body"))]
    dropped_n = len(sorted_news) - len(top_news)

    # Topic filter: transcripts
    raw_transcripts = transcripts.get("transcripts", [])
    ai_video_ids = {v["videoId"] for v in compact_videos}
    filtered_transcripts = [t for t in raw_transcripts
                            if t.get("videoId") in ai_video_ids
                            or _is_ai_relevant(t.get("title"), t.get("transcript"))]
    dropped_t = len(raw_transcripts) - len(filtered_transcripts)

    print(f"topic filter: kept {len(compact_videos)} videos (-{dropped_v}), "
          f"kept {len(top_news)} articles (-{dropped_n}), "
          f"kept {len(filtered_transcripts)} transcripts (-{dropped_t})")

    return {
        "provider_news": top_news,
        "videos": compact_videos,
        "transcripts": filtered_transcripts,
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


import re as _re
from urllib.parse import unquote as _urlunquote

_YT_URL_RE = _re.compile(r"^https?://(?:www\.)?(?:youtu\.be/|youtube\.com/watch\?v=)([A-Za-z0-9_-]{6,})")
_TEXT_FRAG_RE = _re.compile(r"#:~:text=([^&]+)")

# ---------------------------------------------------------------------------
# Topic filter — keep only AI-relevant content; deny clearly off-topic items
# ---------------------------------------------------------------------------

AI_STRONG = {
    "ai", "a.i.", "artificial intelligence", "llm", "llms", "gpt", "gpt-4",
    "gpt-5", "chatgpt", "claude", "claude code", "gemini", "anthropic",
    "openai", "deepmind", "mistral", "perplexity", "cohere", "xai", "grok",
    "huggingface", "ollama", "llama",
    "agent", "agents", "agentic", "rag", "embedding", "embeddings",
    "transformer", "diffusion", "neural network", "machine learning",
    "fine-tune", "fine-tuning", "prompt engineering", "system prompt",
    "vision model", "multimodal", "function calling", "tool use",
    "context window", "inference", "generative ai",
    "copilot", "cursor", "vibe code", "vibe coding", "langchain",
    "llamaindex", "mcp",
    "stable diffusion", "midjourney", "higgsfield", "runway", "elevenlabs",
}

AI_DENY = {
    "n8n", "zapier", "ads", "advertising", "marketing funnel",
    "passive income", "side hustle", "dropshipping", "affiliate marketing",
    "make money online",
    "gardening", "fitness", "nutrition", "weight loss", "real estate",
    "crypto trading", "trading bot", "web3", "nft", "memecoin",
    "make.com", "airtable automation",
}

# Headline verbs (in title) and tip verbs (in what) for tip-quality filter
NEWS_VERBS = {
    "launches", "launched", "announces", "announced", "releases", "released",
    "unveils", "unveiled", "raises", "raised", "acquires", "acquired",
    "partners", "rolls out", "introduces", "introduced", "debuts",
}
TIP_VERBS = {
    "use", "set", "configure", "try", "run", "install", "add", "enable",
    "combine", "wrap", "prompt", "pass", "call", "ask", "create", "build",
    "leverage", "chain", "trigger", "automate",
}


def _word_in(kw: str, blob: str) -> bool:
    """Whole-word match for simple tokens; substring for multi-word/punctuated phrases."""
    if " " in kw or "." in kw or "-" in kw:
        return kw in blob
    return bool(_re.search(rf"\b{_re.escape(kw)}\b", blob))


def _is_ai_relevant(*texts) -> bool:
    """True iff at least one AI_STRONG term matches AND no AI_DENY term matches."""
    blob = " ".join((t or "").lower() for t in texts)
    if any(_word_in(kw, blob) for kw in AI_DENY):
        return False
    return any(_word_in(kw, blob) for kw in AI_STRONG)


def _looks_like_headline(title: str, what: str) -> bool:
    """True when the item reads like a news announcement rather than an actionable tip."""
    title_l = (title or "").lower()
    what_l = (what or "").lower()
    has_news = any(_word_in(v, title_l) for v in NEWS_VERBS)
    has_tip = any(_word_in(v, what_l) for v in TIP_VERBS)
    return has_news and not has_tip


def _normalize_tokens(text):
    text = (text or "").lower()
    text = _re.sub(r"[^a-z0-9\s]", " ", text)
    return {t for t in text.split() if len(t) > 2}


_T_MARKER_RE = _re.compile(r"\[t=(\d+)s\]")


def _yt_window_around(transcript: str, target_sec: int, tolerance_sec: int = 60) -> str:
    """Return the transcript text from the marker just before target_sec through
    the next marker (or +120s of text). Returns '' if no marker is within
    tolerance_sec of target_sec.
    """
    if not transcript:
        return ""
    markers = [(int(m.group(1)), m.start(), m.end())
               for m in _T_MARKER_RE.finditer(transcript)]
    if not markers:
        return ""
    candidates = [m for m in markers if m[0] <= target_sec]
    if not candidates:
        return ""
    sec, _start_idx, end_idx = candidates[-1]
    if target_sec - sec > tolerance_sec:
        return ""
    upper_sec = sec + 120
    next_starts = [m[1] for m in markers if m[0] > upper_sec]
    win_end = next_starts[0] if next_starts else len(transcript)
    return transcript[end_idx:win_end]


def _validate_url(url, valid_video_ids, body_by_article_base,
                  transcripts_by_id=None, tip_title="", tip_what=""):
    """Return a verified url for tools_and_tips, or '' to drop the item.

    Strict mode — no fallback to bare URL on failure:
    - YouTube: videoId must be known, ?t=N must be present AND grounded in the
      transcript (marker within 60s AND topic overlap with the tip).
    - Article: base URL must be known, #:~:text= fragment is REQUIRED, phrase
      must be in the body AND context around it must overlap with the tip topic.
    """
    if not url:
        return ""

    tip_tokens = _normalize_tokens((tip_title or "") + " " + (tip_what or ""))

    m = _YT_URL_RE.match(url)
    if m:
        vid = m.group(1)
        if vid not in valid_video_ids:
            return ""
        ts_match = _re.search(r"[?&]t=(\d+)", url)
        if not ts_match:
            return ""  # timestamp required
        target = int(ts_match.group(1))
        transcript = (transcripts_by_id or {}).get(vid, "")
        window = _yt_window_around(transcript, target, tolerance_sec=60)
        if not window:
            return ""  # no grounded marker
        win_tokens = _normalize_tokens(window)
        if not tip_tokens or not win_tokens:
            return ""
        jacc = len(tip_tokens & win_tokens) / len(tip_tokens | win_tokens)
        return url if jacc >= 0.15 else ""

    # Article path
    base = url.split("?")[0].split("#")[0].rstrip("/")
    if base not in body_by_article_base:
        return ""
    frag = _TEXT_FRAG_RE.search(url)
    if not frag:
        return ""  # fragment required for tools_and_tips
    phrase = _urlunquote(frag.group(1)).strip()
    body = body_by_article_base[base] or ""
    body_l = body.lower()
    phrase_l = phrase.lower()
    if not phrase or phrase_l not in body_l:
        return ""
    idx = body_l.find(phrase_l)
    win = body[max(0, idx - 300): idx + len(phrase) + 300]
    win_tokens = _normalize_tokens(win)
    if not tip_tokens or not win_tokens:
        return ""
    jacc = len(tip_tokens & win_tokens) / len(tip_tokens | win_tokens)
    return url if jacc >= 0.15 else ""


def sanitize_top_stories(items, body_by_article_base):
    """Drop any top_stories item whose URL is a YouTube link, not a known article URL,
    or whose content is not AI-relevant."""
    valid_article_bases = set(body_by_article_base.keys())
    out = []
    dropped = 0
    for story in items or []:
        url = story.get("url") or ""
        if _YT_URL_RE.match(url):
            print(f"  [top_stories drop] YouTube URL in article slot: {url[:80]}")
            dropped += 1
            continue
        base = ""
        if url:
            base = url.split("?")[0].split("#")[0].rstrip("/")
            if base not in valid_article_bases:
                print(f"  [top_stories drop] URL not in provider news: {url[:80]}")
                dropped += 1
                continue
        body = body_by_article_base.get(base, "")
        if not _is_ai_relevant(story.get("headline"), story.get("why_it_matters"), body):
            print(f"  [top_stories drop] not AI-relevant: {(story.get('headline') or '')[:80]}")
            dropped += 1
            continue
        out.append(story)
    if dropped:
        print(f"  top_stories: dropped {dropped} item(s) (invalid URL or not AI-relevant)")
    return out


def dedup_tools_and_tips(items, valid_video_ids, body_by_article_base, transcripts_by_id):
    """Validate urls (strict grounding), drop headlines, then dedup by url and token-overlap."""
    out = []
    seen_token_sets = []
    seen_urls = set()
    drops = {}

    for it in items or []:
        title = it.get("title", "")
        what = it.get("what", "")

        # Drop news headlines disguised as tips
        if _looks_like_headline(title, what):
            drops["headline_style"] = drops.get("headline_style", 0) + 1
            continue

        # Strict URL grounding — drop if link can't be verified
        it["url"] = _validate_url(
            it.get("url", ""), valid_video_ids, body_by_article_base,
            transcripts_by_id=transcripts_by_id,
            tip_title=title,
            tip_what=what,
        )
        if not it["url"]:
            drops["ungrounded_or_invalid"] = drops.get("ungrounded_or_invalid", 0) + 1
            continue

        # url-based dedup:
        # - YouTube: keep ?t= so different timestamps from the same video are distinct
        # - Articles: strip #:~:text= so same article with different phrases collapses
        is_yt = bool(_YT_URL_RE.match(it["url"]))
        url_key = it["url"].split("#")[0] if is_yt else it["url"].split("?")[0].split("#")[0].rstrip("/")
        if url_key in seen_urls:
            drops["dupes"] = drops.get("dupes", 0) + 1
            continue

        # title+what fuzzy dedup (Jaccard >= 0.6) — catches paraphrased duplicates
        toks = _normalize_tokens(title + " " + what)
        is_dup = False
        for prev in seen_token_sets:
            if not toks or not prev:
                continue
            jacc = len(toks & prev) / len(toks | prev)
            if jacc >= 0.6:
                is_dup = True
                break
        if is_dup:
            drops["dupes"] = drops.get("dupes", 0) + 1
            continue

        seen_token_sets.append(toks)
        seen_urls.add(url_key)
        out.append(it)

    total_dropped = sum(drops.values())
    drop_detail = ", ".join(f"{k}={v}" for k, v in drops.items()) if drops else "none"
    print(f"  tools_and_tips: kept {len(out)}, dropped {total_dropped} ({drop_detail})")
    if len(out) < 3:
        print(f"  WARNING: only {len(out)} tips survived validation — "
              f"source material may be thin OR validation is too strict")
    return out


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
    # Transcripts include videos not in the balanced pool; allow both as tip sources.
    valid_video_ids = {v["videoId"] for v in payload["videos"]}
    valid_video_ids |= {t["videoId"] for t in payload["transcripts"] if t.get("videoId")}
    body_by_article_base = {}
    for n in payload["provider_news"]:
        if n.get("url"):
            base = n["url"].split("?")[0].split("#")[0].rstrip("/")
            body_by_article_base[base] = n.get("body") or ""
    digest["top_stories"] = sanitize_top_stories(
        digest.get("top_stories"), body_by_article_base,
    )
    transcripts_by_id = {t["videoId"]: t.get("transcript", "")
                         for t in payload["transcripts"] if t.get("videoId")}
    digest["tools_and_tips"] = dedup_tools_and_tips(
        digest.get("tools_and_tips"), valid_video_ids, body_by_article_base, transcripts_by_id,
    )
    if len(digest["tools_and_tips"]) > 8:
        digest["tools_and_tips"] = digest["tools_and_tips"][:8]
    digest["_meta"] = {"generated_at": now_utc().isoformat(), "usage": usage}
    write_json(TMP / "digest.json", digest)
    print(f"Done. model={usage['model']}  in={usage['prompt_tokens']}  out={usage['output_tokens']}")


if __name__ == "__main__":
    main()
