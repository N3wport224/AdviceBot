"""Claude-powered advice interface in Sabrina Zohar's coaching style.

Accepts a text question and/or an image (e.g. a screenshot of a dating-app
conversation), retrieves relevant podcast excerpts from the scraped corpus (RAG),
and answers via the Anthropic Messages API.

Note on models: the originally specified `claude-3-5-sonnet` was retired by
Anthropic (Oct 2025) and now 404s. We default to its documented replacement,
`claude-sonnet-5` (see config.ANTHROPIC_MODEL / the ANTHROPIC_MODEL env var).
Claude Sonnet 5 rejects the `temperature` parameter, so tone is steered entirely
through the system prompt.

Run:  python -m advisor.sabrina_advisor "Should I text him first?" [--image shot.png]
      python -m advisor.sabrina_advisor --chat
"""

from __future__ import annotations

import argparse
import base64
import logging
import mimetypes
import sys
from pathlib import Path

import anthropic

from advisor.prompts import SABRINA_SYSTEM_PROMPT
from config import ANTHROPIC_MODEL, MAX_RESPONSE_TOKENS, RAG_TOP_K

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sabrina_advisor")

SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}

_client: anthropic.Anthropic | None = None
_retriever = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


def get_retriever():
    """Load the RAG index once; degrade gracefully if the corpus isn't built yet."""
    global _retriever
    if _retriever is None:
        try:
            from pipeline.retriever import CorpusRetriever

            _retriever = CorpusRetriever.load()
        except FileNotFoundError:
            log.warning("No corpus/index found — answering without RAG context. "
                        "Run `python run_pipeline.py` to build it.")
            _retriever = False
    return _retriever or None


def encode_image(image_path: str | Path) -> dict:
    """Build a base64 image content block for the Messages API."""
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")
    media_type = mimetypes.guess_type(str(path))[0]
    if media_type not in SUPPORTED_IMAGE_TYPES:
        raise ValueError(f"Unsupported image type {media_type!r} — use PNG/JPEG/GIF/WebP")
    data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def build_rag_context(query: str, top_k: int = RAG_TOP_K) -> str:
    """Retrieve the most relevant corpus excerpts and format them for the prompt."""
    retriever = get_retriever()
    if retriever is None:
        return ""
    hits = retriever.search(query, top_k=top_k)
    if not hits:
        return ""
    lines = []
    for h in hits:
        lines.append(
            f'<excerpt source="{h["source_platform"]}" title="{h["video_title"]}" '
            f'timestamp="{h["timestamp"]}" url="{h["url"]}">\n{h["transcript_text"]}\n</excerpt>'
        )
    return (
        "Reference material from Sabrina's actual content, most relevant first. "
        "Use it to ground your framing and vocabulary; ignore anything irrelevant:\n\n"
        + "\n\n".join(lines)
    )


def generate_sabrina_advice(
    user_query: str,
    image_path: str | Path | None = None,
    history: list[dict] | None = None,
) -> str:
    """Generate advice in Sabrina's style from text and/or a screenshot.

    Args:
        user_query: The user's question. May be empty if an image is provided.
        image_path: Optional path to a screenshot (PNG/JPEG/GIF/WebP).
        history: Optional prior conversation as Messages-API message dicts;
            the new exchange is appended to it in place, enabling multi-turn chat.

    Returns:
        The assistant's reply text.
    """
    if not user_query and not image_path:
        raise ValueError("Provide a question, an image, or both.")

    # Retrieve grounding excerpts. When only an image is given, use a generic
    # retrieval query so we still surface on-topic material.
    retrieval_query = user_query or "reading text message conversations, mixed signals, effort, interest level"
    rag_context = build_rag_context(retrieval_query)

    # System prompt: the stable persona block carries a cache breakpoint so
    # repeated calls reuse it; the volatile RAG block comes after it.
    system_blocks: list[dict] = [
        {
            "type": "text",
            "text": SABRINA_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    if rag_context:
        system_blocks.append({"type": "text", "text": rag_context})

    # User content: image first (if any), then the text.
    content: list[dict] = []
    if image_path:
        content.append(encode_image(image_path))
        content.append(
            {
                "type": "text",
                "text": user_query
                or "Here's a screenshot of a conversation I'm in. What's really going on here, and what should I do?",
            }
        )
    else:
        content.append({"type": "text", "text": user_query})

    messages = (history or []) + [{"role": "user", "content": content}]

    client = get_client()
    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=MAX_RESPONSE_TOKENS,
            system=system_blocks,
            messages=messages,
        )
    except anthropic.NotFoundError:
        raise RuntimeError(
            f"Model {ANTHROPIC_MODEL!r} not found — it may be retired. "
            "Set ANTHROPIC_MODEL to a current model (e.g. claude-sonnet-5)."
        )
    except anthropic.RateLimitError:
        raise RuntimeError("Rate limited by the Anthropic API — wait a moment and retry.")

    if response.stop_reason == "refusal":
        return (
            "I can't help with that one — if you're dealing with a safety issue, "
            "please reach out to a professional or a crisis line (988 in the US)."
        )

    reply = "".join(block.text for block in response.content if block.type == "text")

    if history is not None:
        history.append({"role": "user", "content": content})
        history.append({"role": "assistant", "content": reply})
    return reply


def chat_loop():
    """Simple interactive multi-turn chat in the terminal."""
    print("Sabrina-style advice chat — type 'quit' to exit.")
    print("Attach a screenshot with:  /image path/to/screenshot.png your question\n")
    history: list[dict] = []
    while True:
        try:
            raw = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not raw or raw.lower() in {"quit", "exit"}:
            break

        image_path = None
        if raw.startswith("/image "):
            parts = raw[len("/image "):].split(maxsplit=1)
            image_path = parts[0]
            raw = parts[1] if len(parts) > 1 else ""
        try:
            reply = generate_sabrina_advice(raw, image_path=image_path, history=history)
        except (RuntimeError, FileNotFoundError, ValueError) as exc:
            print(f"[error] {exc}")
            continue
        print(f"\nsabrina-bot> {reply}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sabrina Zohar-style advice from Claude")
    parser.add_argument("query", nargs="?", default="", help="Your question")
    parser.add_argument("--image", type=str, default=None, help="Path to a conversation screenshot")
    parser.add_argument("--chat", action="store_true", help="Interactive multi-turn chat")
    args = parser.parse_args()

    if args.chat:
        chat_loop()
    elif args.query or args.image:
        print(generate_sabrina_advice(args.query, image_path=args.image))
    else:
        parser.print_help()
        sys.exit(1)
