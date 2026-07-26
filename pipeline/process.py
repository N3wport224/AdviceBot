"""Clean transcripts + Instagram captions into one unified JSONL corpus.

Output schema (data/processed/sabrina_corpus.jsonl), one record per line:
  source_platform, video_title, url, timestamp, transcript_text, video_id, chunk_id

Run:  python -m pipeline.process
"""

from __future__ import annotations

import json
import logging
import re

from config import CORPUS_PATH, INSTAGRAM_RAW_PATH, TRANSCRIPTS_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("process")

# Sponsor/CTA boilerplate that adds noise to a coaching-style corpus.
BOILERPLATE_PATTERNS = [
    r"\bthis episode is (?:brought to you|sponsored) by\b.{0,200}",
    r"\buse (?:code|promo code)\s+\w+.{0,80}",
    r"\bdon'?t forget to (?:like|subscribe|rate|review|follow)\b.{0,120}",
    r"\bhit (?:the|that) subscribe button\b.{0,80}",
    r"\blink in (?:my )?bio\b.{0,60}",
]
FILLERS = re.compile(r"\b(?:um+|uh+|erm+)\b[, ]*", re.IGNORECASE)


def clean_text(text: str) -> str:
    """Normalize whitespace, strip fillers and sponsor/CTA boilerplate."""
    for pattern in BOILERPLATE_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    text = FILLERS.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def load_youtube_records() -> list[dict]:
    records = []
    for path in sorted(TRANSCRIPTS_DIR.glob("*.json")):
        doc = json.loads(path.read_text())
        for i, chunk in enumerate(doc.get("chunks", [])):
            text = clean_text(chunk["text"])
            if len(text.split()) < 20:  # drop fragments too short to be useful
                continue
            records.append(
                {
                    "source_platform": "youtube",
                    "video_title": doc.get("video_title", ""),
                    "url": doc.get("url", ""),
                    "timestamp": chunk.get("timestamp", "00:00:00"),
                    "transcript_text": text,
                    "video_id": doc.get("video_id", path.stem),
                    "chunk_id": f"{doc.get('video_id', path.stem)}_{i:04d}",
                }
            )
    return records


def load_instagram_records() -> list[dict]:
    if not INSTAGRAM_RAW_PATH.exists():
        return []
    records = []
    for line in INSTAGRAM_RAW_PATH.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        text = clean_text(r["transcript_text"])
        if not text:
            continue
        r["transcript_text"] = text
        r["chunk_id"] = f"{r['video_id']}_0000"
        r.pop("is_video", None)
        records.append(r)
    return records


def build_corpus() -> int:
    """Merge all sources, dedupe, and write the unified corpus JSONL."""
    records = load_youtube_records() + load_instagram_records()

    seen: set[str] = set()
    deduped = []
    for r in records:
        key = r["transcript_text"][:200].lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    with open(CORPUS_PATH, "w", encoding="utf-8") as f:
        for r in deduped:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    log.info("Corpus built: %d records → %s", len(deduped), CORPUS_PATH)
    return len(deduped)


if __name__ == "__main__":
    build_corpus()
