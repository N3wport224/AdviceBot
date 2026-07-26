"""Orchestrate the full data pipeline: scrape → transcribe → process → index.

Run:  python run_pipeline.py --max-videos 25 [--skip-youtube] [--skip-instagram]
"""

from __future__ import annotations

import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pipeline")


def main():
    parser = argparse.ArgumentParser(description="Sabrina Zohar Advice Bot — data pipeline")
    parser.add_argument("--max-videos", type=int, default=25)
    parser.add_argument("--skip-youtube", action="store_true")
    parser.add_argument("--skip-instagram", action="store_true")
    args = parser.parse_args()

    if not args.skip_youtube:
        log.info("=== Stage 1/4: YouTube extraction ===")
        from scrapers.youtube_scraper import scrape_channel

        scrape_channel(max_videos=args.max_videos)

        log.info("=== Stage 2/4: Whisper transcription ===")
        from pipeline.transcribe import transcribe_all

        transcribe_all()

    if not args.skip_instagram:
        log.info("=== Stage 3a: Instagram adapter ===")
        from scrapers.instagram_scraper import scrape_instagram

        scrape_instagram()

    log.info("=== Stage 3b: Corpus build ===")
    from pipeline.process import build_corpus

    n = build_corpus()
    if n == 0:
        log.error("Corpus is empty — nothing to index. Check earlier stages.")
        return

    log.info("=== Stage 4/4: RAG index ===")
    from pipeline.retriever import CorpusRetriever

    CorpusRetriever().build().save()
    log.info("Pipeline complete. Try: python -m advisor.sabrina_advisor \"Should I text him first?\"")


if __name__ == "__main__":
    main()
