# Workflow: AI Weekly Digest

## Objective
Produce a professional `.pptx` slide deck summarizing the past week in AI — top news from major providers, trending videos from a curated YouTube channel list, tools, prompts and setup tips distilled from transcripts and provider news, each linked to the exact moment / sentence, and supporting charts — then email it to the user.

## Required inputs
- `.env` with `YOUTUBE_API_KEY`, `GEMINI_API_KEY`, `FIRECRAWL_API_KEY`, `DIGEST_RECIPIENT_EMAIL`
- `credentials.json` in project root (Google OAuth client, covers Gmail API)
- `config/youtube_channels.json` — channel list and provider sources

## Tool sequence
Run each step. Each tool reads from `.tmp/` and writes the next artifact. On failure, read the error, fix, and rerun — do not skip steps.

| # | Tool | Input | Output |
|---|------|-------|--------|
| 1 | `tools/fetch_provider_news.py` | `config/youtube_channels.json` (providers section) | `.tmp/provider_news.json` |
| 2 | `tools/fetch_youtube_videos.py` | `config/youtube_channels.json` (channels), `YOUTUBE_API_KEY` | `.tmp/youtube_videos.json` |
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
- Firecrawl: free tier covers ~500 scrapes/month. Per run: ~7 provider homepages + up to 15 article-body scrapes for tip linking ≈ 22 scrapes; 4 runs/month ≈ 88 scrapes.
- youtube-transcript-api: no key, but can be IP-throttled — keep top-N to ~15.

## Scheduling
Use the `schedule` skill to create a weekly trigger:
- Cron: `0 10 * * SUN` (every Sunday 10:00, local time)
- Action: run the six-command chain above.
