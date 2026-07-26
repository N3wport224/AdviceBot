# Sabrina Zohar Advice Chatbot

An end-to-end pipeline that (1) collects and transcribes content from "The Sabrina
Zohar Show" (YouTube + a mock Instagram/Facebook adapter), (2) structures it into a
unified JSONL corpus, and (3) serves a Claude-powered advice interface that answers
text questions **and** analyzes screenshots (e.g. dating-app conversations) in
Sabrina's coaching style, grounded in the scraped corpus via RAG.

## Project layout

```
AdviceBot/
├── config.py                  # Central configuration (paths, models, channel URLs)
├── run_pipeline.py            # Orchestrates: scrape → transcribe → process → index
├── scrapers/
│   ├── youtube_scraper.py     # yt-dlp: channel metadata + audio download
│   └── instagram_scraper.py   # instaloader adapter w/ graceful mock fallback
├── pipeline/
│   ├── transcribe.py          # faster-whisper transcription → timestamped chunks
│   ├── process.py             # Cleaning + unified JSONL corpus
│   └── retriever.py           # RAG index (sentence-transformers, TF-IDF fallback)
├── advisor/
│   ├── prompts.py             # Sabrina-style system prompt
│   └── sabrina_advisor.py     # generate_sabrina_advice(query, image_path) + CLI
└── data/                      # Created at runtime (gitignored)
    ├── raw/                   #   audio files + per-video metadata
    ├── transcripts/           #   per-video transcript chunks
    └── processed/             #   sabrina_corpus.jsonl + vector index
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Optional (better retrieval quality than the TF-IDF fallback):
pip install sentence-transformers

cp .env.example .env   # then add your ANTHROPIC_API_KEY
```

`ffmpeg` must be on PATH for yt-dlp audio extraction (`apt install ffmpeg` /
`brew install ffmpeg`).

## Usage

### 1. Build the corpus

```bash
# Full pipeline: scrape N videos → transcribe → clean → build the RAG index
python run_pipeline.py --max-videos 25

# Or run stages individually
python -m scrapers.youtube_scraper --max-videos 25
python -m pipeline.transcribe
python -m scrapers.instagram_scraper          # mock/stub unless authenticated
python -m pipeline.process
python -m pipeline.retriever --rebuild
```

### 2. Ask for advice

```bash
# Text question
python -m advisor.sabrina_advisor "He takes 8 hours to text back but says he likes me. What do I do?"

# Screenshot of a conversation (+ optional question)
python -m advisor.sabrina_advisor "Is this guy breadcrumbing me?" --image ./screenshot.png

# Interactive chat
python -m advisor.sabrina_advisor --chat
```

Or from Python:

```python
from advisor.sabrina_advisor import generate_sabrina_advice

reply = generate_sabrina_advice(
    "Should I text him first?",
    image_path="convo.png",   # optional
)
print(reply)
```

## Corpus record schema

Every record in `data/processed/sabrina_corpus.jsonl`:

```json
{
  "source_platform": "youtube",
  "video_title": "Why You Keep Chasing Emotionally Unavailable People",
  "url": "https://www.youtube.com/watch?v=...",
  "timestamp": "00:12:41",
  "transcript_text": "...cleaned transcript chunk...",
  "video_id": "abc123",
  "chunk_id": "abc123_0007"
}
```

## Desktop app (.exe, no terminal window)

`gui_app.py` is a tkinter chat app (question box + "Attach screenshot…") that
runs entirely windowless-console: packaged with PyInstaller `--windowed`, it
opens straight into the chat UI and never shows a terminal. On first run it
prompts for your Anthropic API key and saves it to a `.env` next to the exe.

Two ways to get the exe:

1. **GitHub Actions (no local toolchain needed):** the `build-windows-exe`
   workflow builds `SabrinaAdvisor.exe` on a Windows runner on every push (or
   manually via "Run workflow"). Download the `SabrinaAdvisor-windows` artifact
   from the run page, put the exe anywhere (e.g. your Desktop), done.
2. **Locally on Windows:** double-click `build_exe.bat` (needs Python 3.11+).
   The exe lands in `dist\SabrinaAdvisor.exe`.

To ground answers in the scraped corpus, copy the `data/` folder (built by
`run_pipeline.py`) into the same directory as the exe. Without it the app still
works — it just answers from the persona prompt alone.

## Notes & caveats

- **Model:** the original spec named `claude-3-5-sonnet`, which was retired by
  Anthropic in Oct 2025 and now returns a 404. This project defaults to its
  documented replacement, **`claude-sonnet-5`** (override with the
  `ANTHROPIC_MODEL` env var). Note that Claude Sonnet 5 rejects `temperature` —
  style is steered entirely through the system prompt.
- **Instagram/Facebook:** Meta heavily restricts programmatic access. The adapter
  attempts a real `instaloader` fetch when credentials/session are available and
  otherwise degrades to a clearly-labeled mock dataset so the downstream pipeline
  stays testable. For production use, apply for the official Meta Graph API /
  oEmbed access.
- **Terms of service:** scrape only content you have the right to use, respect
  robots.txt / platform ToS, and keep this corpus for personal/research use unless
  you have permission from the creator.
- **System prompt:** `advisor/prompts.py` contains a drafted persona prompt built
  from the "no-BS, empathetic, nervous-system-regulated, anti-self-abandonment"
  brief. Swap in your exact prompt text there if you have one.
- **Not therapy:** the assistant is instructed to redirect crisis/safety topics to
  professional resources.
