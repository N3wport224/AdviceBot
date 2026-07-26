"""Central configuration for the Sabrina Zohar Advice Bot pipeline."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# --- Paths -----------------------------------------------------------------
# When frozen by PyInstaller (the desktop .exe), anchor data and .env next to
# the executable so the app works from a desktop shortcut regardless of cwd.
IS_FROZEN = bool(getattr(sys, "frozen", False))
ROOT_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent

load_dotenv(ROOT_DIR / ".env")
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"                      # audio + per-video metadata
AUDIO_DIR = RAW_DIR / "audio"
METADATA_DIR = RAW_DIR / "metadata"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"      # per-video chunked transcripts
PROCESSED_DIR = DATA_DIR / "processed"

CORPUS_PATH = PROCESSED_DIR / "sabrina_corpus.jsonl"
INSTAGRAM_RAW_PATH = RAW_DIR / "instagram_posts.jsonl"
INDEX_PATH = PROCESSED_DIR / "rag_index.pkl"

for _d in (AUDIO_DIR, METADATA_DIR, TRANSCRIPTS_DIR, PROCESSED_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Sources ---------------------------------------------------------------
# Sabrina Zohar's channel (host of "The Sabrina Zohar Show"), addressed by its
# permanent channel ID — verified against multiple sources; @-handles can change
# and her YouTube handle differs from her @sabrina.zohar Instagram/TikTok handle.
YOUTUBE_CHANNEL_URL = "https://www.youtube.com/channel/UCSKQduzS78E6-I9tx0jqjpw/videos"
INSTAGRAM_TARGET_PROFILE = os.getenv("INSTAGRAM_TARGET_PROFILE", "sabrina.zohar")

# --- Transcription ---------------------------------------------------------
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")
# Target size of each transcript chunk, in words. ~180 words ≈ 60–75s of speech.
CHUNK_TARGET_WORDS = 180

# --- LLM -------------------------------------------------------------------
# claude-3-5-sonnet (the originally requested model) was retired in Oct 2025;
# claude-sonnet-5 is Anthropic's documented drop-in replacement.
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
MAX_RESPONSE_TOKENS = 4096
RAG_TOP_K = 6
