"""Instagram/Facebook adapter for Sabrina Zohar's reels/posts.

Meta aggressively rate-limits and legally restricts unauthenticated scraping, so
this module is a *robust adapter*:

  1. If instaloader is installed AND a logged-in session is available, it pulls
     real captions/video titles from the target profile.
  2. Otherwise it degrades to a clearly-labeled MOCK dataset with the same
     schema, so the downstream pipeline (cleaning, indexing, RAG) is testable
     end-to-end without credentials.

For production, use the official Meta Graph API / oEmbed endpoints instead.

Run:  python -m scrapers.instagram_scraper [--limit 50] [--login USERNAME]
"""

from __future__ import annotations

import argparse
import json
import logging
import os

from config import INSTAGRAM_RAW_PATH, INSTAGRAM_TARGET_PROFILE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("instagram_scraper")

# Representative themes from Sabrina's short-form content — used only when a real
# fetch is impossible, so the pipeline has data to flow through.
MOCK_POSTS = [
    {
        "shortcode": "MOCK_0001",
        "caption": (
            "If you have to convince someone to choose you, they already made their "
            "choice. Stop negotiating your worth. The right person doesn't leave you "
            "guessing — consistency is the bare minimum, not the prize."
        ),
        "date": "2025-11-02",
        "is_video": True,
    },
    {
        "shortcode": "MOCK_0002",
        "caption": (
            "Anxious attachment isn't 'caring too much.' It's your nervous system "
            "screaming for certainty. Regulate first, then respond. You can't hear "
            "your intuition when your body is in survival mode."
        ),
        "date": "2025-10-21",
        "is_video": True,
    },
    {
        "shortcode": "MOCK_0003",
        "caption": (
            "You're not dating him. You're dating his potential. The version of him "
            "you built in your head after date two. Look at what he DOES, not what "
            "you hope he'll become."
        ),
        "date": "2025-09-30",
        "is_video": True,
    },
    {
        "shortcode": "MOCK_0004",
        "caption": (
            "Slow down. Chemistry is not compatibility. Intensity is not intimacy. "
            "If it feels like a drug, that's activation — not love."
        ),
        "date": "2025-09-14",
        "is_video": False,
    },
    {
        "shortcode": "MOCK_0005",
        "caption": (
            "Self-abandonment looks like: shrinking your needs so someone stays, "
            "calling it 'being easygoing.' You're allowed to have standards. The "
            "goal isn't to need less — it's to choose people who can meet you."
        ),
        "date": "2025-08-28",
        "is_video": True,
    },
]


def _record(shortcode: str, caption: str, date: str, is_video: bool, mock: bool) -> dict:
    return {
        "source_platform": "instagram" if not mock else "instagram_mock",
        "video_title": caption.split(".")[0][:90],
        "url": f"https://www.instagram.com/p/{shortcode}/",
        "timestamp": date,
        "transcript_text": caption,
        "video_id": shortcode,
        "is_video": is_video,
    }


def fetch_real_posts(profile_name: str, limit: int, login_user: str | None) -> list[dict] | None:
    """Attempt a real instaloader fetch. Returns None if unavailable/blocked."""
    try:
        import instaloader
    except ImportError:
        log.warning("instaloader not installed — falling back to mock data")
        return None

    loader = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        save_metadata=False,
        quiet=True,
    )
    try:
        if login_user:
            # Reuses a session file created by `instaloader --login USERNAME`
            loader.load_session_from_file(login_user)
        profile = instaloader.Profile.from_username(loader.context, profile_name)
        records = []
        for i, post in enumerate(profile.get_posts()):
            if i >= limit:
                break
            records.append(
                _record(
                    shortcode=post.shortcode,
                    caption=(post.caption or "").strip(),
                    date=post.date_utc.strftime("%Y-%m-%d"),
                    is_video=post.is_video,
                    mock=False,
                )
            )
        log.info("Fetched %d real posts from @%s", len(records), profile_name)
        return records
    except Exception as exc:
        log.warning("Instagram fetch failed (%s: %s) — falling back to mock data", type(exc).__name__, exc)
        return None


def scrape_instagram(limit: int = 50, login_user: str | None = None) -> list[dict]:
    """Fetch posts (real when possible, mock otherwise) and write raw JSONL."""
    login_user = login_user or os.getenv("INSTAGRAM_USERNAME") or None
    records = fetch_real_posts(INSTAGRAM_TARGET_PROFILE, limit, login_user)
    if records is None:
        log.info("Using MOCK Instagram dataset (%d posts)", len(MOCK_POSTS))
        records = [_record(mock=True, **p) for p in MOCK_POSTS]

    records = [r for r in records if r["transcript_text"]]
    with open(INSTAGRAM_RAW_PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    log.info("Wrote %d Instagram records → %s", len(records), INSTAGRAM_RAW_PATH)
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape (or mock) Sabrina Zohar Instagram content")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--login", type=str, default=None, help="Instagram username with a saved instaloader session")
    args = parser.parse_args()
    scrape_instagram(limit=args.limit, login_user=args.login)
