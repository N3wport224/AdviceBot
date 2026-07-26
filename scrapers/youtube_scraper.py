"""YouTube extraction for "The Sabrina Zohar Show".

Uses yt-dlp to (1) enumerate videos on the channel, (2) save per-video metadata,
and (3) download audio-only files for local Whisper transcription.

Run:  python -m scrapers.youtube_scraper --max-videos 25
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import yt_dlp

from config import AUDIO_DIR, METADATA_DIR, YOUTUBE_CHANNEL_URL

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("youtube_scraper")


def list_channel_videos(channel_url: str = YOUTUBE_CHANNEL_URL, max_videos: int | None = None) -> list[dict]:
    """Return lightweight entries (id, title, url) for videos on the channel.

    Uses extract_flat so no media is downloaded during enumeration.
    """
    ydl_opts = {
        "quiet": True,
        "extract_flat": "in_playlist",
        "playlistend": max_videos,
        "ignoreerrors": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)

    # With ignoreerrors=True, yt-dlp returns None instead of raising when the
    # channel is unreachable (network/proxy block, bad URL, region lock).
    if info is None:
        log.error("Could not enumerate %s — channel unreachable or blocked", channel_url)
        return []

    entries = [e for e in (info.get("entries") or []) if e]
    videos = []
    for e in entries:
        video_id = e.get("id")
        if not video_id:  # deleted/private videos can yield sparse flat entries
            continue
        videos.append(
            {
                "video_id": video_id,
                "title": e.get("title", ""),
                "url": e.get("url") or f"https://www.youtube.com/watch?v={video_id}",
                "duration": e.get("duration"),
            }
        )
    log.info("Found %d videos on %s", len(videos), channel_url)
    return videos


def download_video_audio(video: dict) -> Path | None:
    """Download audio + full metadata for one video. Returns the audio path.

    Skips work that is already on disk, so the scraper is safe to re-run.
    """
    video_id = video["video_id"]
    meta_path = METADATA_DIR / f"{video_id}.json"
    existing = list(AUDIO_DIR.glob(f"{video_id}.*"))
    if meta_path.exists() and existing:
        log.info("Skipping %s (already downloaded)", video_id)
        return existing[0]

    ydl_opts = {
        "quiet": True,
        "format": "bestaudio/best",
        "outtmpl": str(AUDIO_DIR / "%(id)s.%(ext)s"),
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "128"}
        ],
        "ignoreerrors": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video["url"], download=True)
    except yt_dlp.utils.DownloadError as exc:
        log.warning("Failed to download %s: %s", video_id, exc)
        return None
    if info is None:
        return None

    metadata = {
        "video_id": video_id,
        "title": info.get("title", video.get("title", "")),
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "description": info.get("description", ""),
        "upload_date": info.get("upload_date", ""),
        "duration": info.get("duration"),
        "view_count": info.get("view_count"),
        "channel": info.get("channel", "The Sabrina Zohar Show"),
    }
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2))

    audio_files = list(AUDIO_DIR.glob(f"{video_id}.*"))
    if not audio_files:
        log.warning("No audio file produced for %s", video_id)
        return None
    log.info("Downloaded %s → %s", metadata["title"], audio_files[0].name)
    return audio_files[0]


def scrape_channel(max_videos: int | None = None) -> list[Path]:
    """Full extraction: enumerate the channel, then download audio + metadata."""
    videos = list_channel_videos(max_videos=max_videos)
    audio_paths = []
    for video in videos:
        path = download_video_audio(video)
        if path:
            audio_paths.append(path)
    log.info("Done: %d/%d audio files ready in %s", len(audio_paths), len(videos), AUDIO_DIR)
    return audio_paths


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape The Sabrina Zohar Show from YouTube")
    parser.add_argument("--max-videos", type=int, default=25, help="Limit number of videos")
    args = parser.parse_args()
    scrape_channel(max_videos=args.max_videos)
