# AI News Weekly Digest

An automated agent that produces a weekly AI news briefing as a PowerPoint deck and emails it to you.

Each run it:
1. Scrapes the latest news from major AI providers (OpenAI, Anthropic, Google, Meta, etc.)
2. Fetches recent videos from a curated list of AI YouTube channels
3. Downloads and parses video transcripts
4. Summarizes everything with Gemini
5. Builds a `.pptx` slide deck with top stories, trending videos, and key takeaways
6. Emails the deck to you via Gmail

Built on the **WAT framework** (Workflows, Agents, Tools) — markdown SOPs drive an AI agent that orchestrates deterministic Python/JS scripts.

## Setup

### Prerequisites
- Python 3.9+
- Node.js 18+

### Install dependencies

```bash
pip install -r requirements.txt
npm install
```

### Configure credentials

Create a `.env` file in the project root:

```env
YOUTUBE_API_KEY=...
GEMINI_API_KEY=...
FIRECRAWL_API_KEY=...
DIGEST_RECIPIENT_EMAIL=you@example.com
```

Also place your Google OAuth `credentials.json` in the project root (needed for Gmail sending). On first run, a `token.json` will be generated automatically.

### Configure sources

Edit `config/scraping_sources.json` to set which YouTube channels, AI provider blogs, and QA blogs to scrape.

## Run

```bash
python tools/fetch_provider_news.py && \
python tools/fetch_youtube_videos.py && \
python tools/fetch_youtube_transcript.py && \
python tools/summarize_with_gemini.py && \
python tools/build_pptx_digest.py && \
python tools/send_gmail.py
```

Output is saved to `.tmp/ai_digest_YYYY-MM-DD.pptx` and emailed to `DIGEST_RECIPIENT_EMAIL`.

## Project structure

```
tools/        # Python/JS scripts for each pipeline step
workflows/    # Markdown SOPs that describe the full workflow
config/       # Source configuration (channels, providers)
.tmp/         # Intermediate files (gitignored, regenerated each run)
```
