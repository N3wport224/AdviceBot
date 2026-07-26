"""Transcribe downloaded audio with a local Whisper model (faster-whisper).

Produces one JSON file per video in data/transcripts/, each containing
timestamped chunks of ~CHUNK_TARGET_WORDS words ready for the corpus builder.

Run:  python -m pipeline.transcribe
"""

from __future__ import annotations

import argparse
import json
import logging

from config import (
    AUDIO_DIR,
    CHUNK_TARGET_WORDS,
    METADATA_DIR,
    TRANSCRIPTS_DIR,
    WHISPER_MODEL_SIZE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("transcribe")

# Only feed real audio files to Whisper — interrupted yt-dlp downloads leave
# .part/.ytdl files in the same directory.
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".webm", ".wav", ".opus", ".ogg", ".flac", ".aac"}

_model = None


def get_model():
    """Lazy-load the Whisper model (CPU int8 by default; auto-uses GPU if present)."""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        log.info("Loading faster-whisper model '%s'…", WHISPER_MODEL_SIZE)
        try:
            _model = WhisperModel(WHISPER_MODEL_SIZE, device="auto", compute_type="int8")
        except Exception:
            _model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def format_timestamp(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def chunk_segments(segments, target_words: int = CHUNK_TARGET_WORDS) -> list[dict]:
    """Group Whisper segments into ~target_words chunks, keeping start timestamps."""
    chunks: list[dict] = []
    current_text: list[str] = []
    current_words = 0
    current_start: float | None = None

    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        if current_start is None:
            current_start = seg.start
        current_text.append(text)
        current_words += len(text.split())
        if current_words >= target_words:
            chunks.append({"timestamp": format_timestamp(current_start), "text": " ".join(current_text)})
            current_text, current_words, current_start = [], 0, None

    if current_text:
        chunks.append({"timestamp": format_timestamp(current_start or 0.0), "text": " ".join(current_text)})
    return chunks


def transcribe_audio_file(audio_path) -> list[dict]:
    """Transcribe one audio file into timestamped chunks."""
    model = get_model()
    log.info("Transcribing %s…", audio_path.name)
    segments, info = model.transcribe(str(audio_path), beam_size=5, vad_filter=True)
    chunks = chunk_segments(segments)
    log.info("  → %d chunks (detected language: %s)", len(chunks), info.language)
    return chunks


def transcribe_all(force: bool = False) -> int:
    """Transcribe every audio file that has metadata but no transcript yet."""
    count = 0
    for audio_path in sorted(AUDIO_DIR.iterdir()):
        if not audio_path.is_file() or audio_path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        video_id = audio_path.stem
        out_path = TRANSCRIPTS_DIR / f"{video_id}.json"
        meta_path = METADATA_DIR / f"{video_id}.json"
        if out_path.exists() and not force:
            continue
        if not meta_path.exists():
            log.warning("No metadata for %s, skipping", video_id)
            continue

        metadata = json.loads(meta_path.read_text())
        try:
            chunks = transcribe_audio_file(audio_path)
        except Exception as exc:
            log.error("Transcription failed for %s: %s", video_id, exc)
            continue

        out_path.write_text(
            json.dumps(
                {
                    "video_id": video_id,
                    "video_title": metadata.get("title", ""),
                    "url": metadata.get("url", ""),
                    "chunks": chunks,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        count += 1
    log.info("Transcribed %d new videos → %s", count, TRANSCRIPTS_DIR)
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Transcribe downloaded audio with faster-whisper")
    parser.add_argument("--force", action="store_true", help="Re-transcribe even if output exists")
    args = parser.parse_args()
    transcribe_all(force=args.force)
