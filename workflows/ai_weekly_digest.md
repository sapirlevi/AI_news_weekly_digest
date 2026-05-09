# Workflow: AI Weekly Digest

## Objective
Produce a professional `.pptx` slide deck summarizing the past week in AI — top news from major providers, trending videos from a curated YouTube channel list, tools, prompts and setup tips distilled from transcripts and provider news, each linked to the exact moment / sentence, and supporting charts — then email it to the user.

## Required inputs
- `.env` with `YOUTUBE_API_KEY`, `GEMINI_API_KEY`, `FIRECRAWL_API_KEY`, `DIGEST_RECIPIENT_EMAIL`
- `credentials.json` in project root (Google OAuth client, covers Gmail API)
- `config/scraping_sources.json` — YouTube channel list, AI provider blogs, and QA blogs (see `qa_blogs` section)

## Tool sequence
Run each step. Each tool reads from `.tmp/` and writes the next artifact. On failure, read the error, fix, and rerun — do not skip steps.

| # | Tool | Input | Output |
|---|------|-------|--------|
| 1 | `tools/fetch_provider_news.py` | `config/scraping_sources.json` (providers + qa_blogs sections) | `.tmp/provider_news.json` |
| 2 | `tools/fetch_youtube_videos.py` | `config/scraping_sources.json` (channels), `YOUTUBE_API_KEY` | `.tmp/youtube_videos.json` |
| 3 | `tools/fetch_youtube_transcript.py` | `.tmp/youtube_videos.json` | `.tmp/transcripts.json` |
| 4 | `tools/summarize_with_gemini.py` | `.tmp/provider_news.json`, `.tmp/youtube_videos.json`, `.tmp/transcripts.json`, `GEMINI_API_KEY` | `.tmp/digest.json` |
| 5 | `tools/build_pptx_digest.py` | `.tmp/digest.json`, `.tmp/youtube_videos.json`, `.tmp/provider_news.json` | `.tmp/ai_digest_YYYY-MM-DD.pptx` |
| 6 | `tools/send_gmail.py` | `.tmp/ai_digest_*.pptx`, `DIGEST_RECIPIENT_EMAIL`, `credentials.json`/`token.json` | Email in user's inbox |

Or run the full chain:
```bash
python tools/fetch_provider_news.py && \
python tools/fetch_youtube_videos.py && \
python tools/fetch_youtube_transcript.py && \
python tools/summarize_with_gemini.py && \
python tools/build_pptx_digest.py && \
python tools/send_gmail.py
```

## Expected output
- `.pptx` saved to `.tmp/ai_digest_YYYY-MM-DD.pptx`
- Email delivered to `DIGEST_RECIPIENT_EMAIL` with the deck attached and an HTML summary body
- `.tmp/seen.json` updated with IDs to avoid repetition next week

## QA AI chapter

A 7th deck chapter — "QA × AI — Tools, Frameworks & How-Tos" — pulls from the `qa_blogs` section of `config/scraping_sources.json`. Key differences vs. general provider news:

- **14-day window** (vs. 7-day for general) — QA blogs publish less frequently.
- **No article-body fetch** — QA AI uses direct post URLs, no text-fragment deep links.
- **Relaxed AI-relevance filter** — accepts QA-automation vocab (e.g. "test agent", "self-healing test") in addition to general AI keywords.
- **Actionability filter** — Gemini drops think-pieces / "future of QA" essays in favor of items with concrete takeaways (new tools, frameworks, how-tos, strategies).
- **Cap**: 12 final items = 2 slide pages at 6 items/page.
- Cross-run dedup uses the same `seen.json["provider_urls"]` set as general provider items.

If BugRaptors returns 0 items, the fetcher logs a loud `⚠ BUGRAPTORS EMPTY` warning — investigate before continuing.

## Cross-run deduplication
- **Filter (steps 1 & 2):** the two fetchers read `.tmp/seen.json` and drop any news `url` or YouTube `videoId` that was delivered in a previous run. The Gemini prompt only ever sees fresh content, so token cost is unchanged or lower.
- **Commit (step 6):** *only after* `send_gmail.py` confirms a successful send, the URLs from `digest.json["top_stories"]` and the videoIds from `digest.json["trending_videos"]` are appended to `.tmp/seen.json`. A failed Gmail call leaves `seen.json` untouched, so no content is silently burned.
- **Storage:** FIFO-capped at 500 entries per list (~10–16 weeks of memory at current volume); the file is never sent to an LLM.
- **Reset:** `rm .tmp/seen.json` to clear all memory and start fresh.

## Edge cases & handling
- **Provider site fails** (layout change, 404): tool logs warning, omits that provider's items, continues. Deck footnotes "Sources unavailable: X".
- **Transcript missing** (video has none): skip, do not block. Summarizer uses title + description.
- **YouTube quota exhausted**: tool exits with clear message; rerun next day. Channel handle resolution is cached in `.tmp/channel_id_cache.json` to minimize quota use.
- **Gmail token expired**: delete `token.json` and rerun `send_gmail.py` to reauth.
- **Empty week** (no new content): still produces a deck with a "Quiet week" cover note.

## Rate limits / quotas to remember
- YouTube Data API v3: 10,000 units/day free. `playlistItems.list` = 1 unit, `videos.list` = 1 unit, `channels.list` = 1 unit. One full run ~ 30 units.
- Gemini: free tier on `gemini-2.5-flash` is generous (daily quota well above one digest/week); pro tier used first, falls back to flash on quota/error.
- Firecrawl: free tier covers ~500 scrapes/month. Per run: ~5 provider homepages (Firecrawl fallback) + ~7 QA blog homepages + up to 15 article-body scrapes for tip linking ≈ 27 scrapes; 4 runs/month ≈ 108 scrapes. QA items skip body fetching, keeping quota manageable.
- youtube-transcript-api: no key, but can be IP-throttled — keep top-N to ~15.

## Scheduling
Use the `schedule` skill to create a weekly trigger:
- Cron: `0 10 * * SUN` (every Sunday 10:00, local time)
- Action: run the six-command chain above.
