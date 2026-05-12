#!/bin/bash
set -e

PROJECT="/home/sapir_ubuntu/projects/claude_projects/AI_news_weekly_digest"
LOG="$PROJECT/.tmp/run_digest.log"

cd "$PROJECT"

exec >> "$LOG" 2>&1
echo ""
echo "========================================"
echo "Run started: $(date)"
echo "========================================"

.venv/bin/python tools/fetch_provider_news.py
.venv/bin/python tools/fetch_youtube_videos.py
.venv/bin/python tools/fetch_youtube_transcript.py
.venv/bin/python tools/summarize_with_gemini.py
.venv/bin/python tools/build_pptx_digest.py
.venv/bin/python tools/send_gmail.py

echo "Run completed: $(date)"
