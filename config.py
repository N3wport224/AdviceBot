"""Central configuration for the Sabrina Zohar Advice Bot pipeline."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Paths -----------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent
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
# "The Sabrina Zohar Show" — full episodes tab of the channel.
YOUTUBE_CHANNEL_URL = "https://www.youtube.com/@sabrina.zohar/videos"
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
