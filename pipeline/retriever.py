"""RAG retriever over the unified corpus.

Uses sentence-transformers embeddings when installed; otherwise falls back to a
TF-IDF index (scikit-learn) so the pipeline works with zero heavy dependencies.
The index is persisted to data/processed/rag_index.pkl.

Run:  python -m pipeline.retriever --rebuild
      python -m pipeline.retriever --query "he stopped texting me"
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle

import numpy as np

from config import CORPUS_PATH, INDEX_PATH, RAG_TOP_K

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("retriever")

EMBED_MODEL_NAME = "all-MiniLM-L6-v2"


def _load_corpus() -> list[dict]:
    if not CORPUS_PATH.exists():
        raise FileNotFoundError(
            f"Corpus not found at {CORPUS_PATH}. Run the pipeline first (python run_pipeline.py)."
        )
    return [json.loads(line) for line in CORPUS_PATH.read_text().splitlines() if line.strip()]


class CorpusRetriever:
    """Semantic (or lexical-fallback) top-k retrieval over the corpus."""

    def __init__(self):
        self.records: list[dict] = []
        self.backend: str = "tfidf"
        self._embeddings = None      # sentence-transformers matrix
        self._st_model = None
        self._vectorizer = None      # TF-IDF fallback
        self._tfidf_matrix = None

    # -- index building ------------------------------------------------------

    def build(self) -> "CorpusRetriever":
        self.records = _load_corpus()
        texts = [r["transcript_text"] for r in self.records]
        try:
            from sentence_transformers import SentenceTransformer

            self._st_model = SentenceTransformer(EMBED_MODEL_NAME)
            self._embeddings = self._st_model.encode(
                texts, normalize_embeddings=True, show_progress_bar=True
            )
            self.backend = "sentence-transformers"
        except ImportError:
            from sklearn.feature_extraction.text import TfidfVectorizer

            self._vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=50000)
            self._tfidf_matrix = self._vectorizer.fit_transform(texts)
            self.backend = "tfidf"
        log.info("Built %s index over %d records", self.backend, len(self.records))
        return self

    def save(self):
        payload = {
            "backend": self.backend,
            "records": self.records,
            "embeddings": self._embeddings,
            "vectorizer": self._vectorizer,
            "tfidf_matrix": self._tfidf_matrix,
        }
        with open(INDEX_PATH, "wb") as f:
            pickle.dump(payload, f)
        log.info("Index saved → %s", INDEX_PATH)

    @classmethod
    def load(cls) -> "CorpusRetriever":
        if not INDEX_PATH.exists():
            log.info("No saved index — building fresh")
            retriever = cls().build()
            retriever.save()
            return retriever
        with open(INDEX_PATH, "rb") as f:
            payload = pickle.load(f)
        retriever = cls()
        retriever.backend = payload["backend"]
        retriever.records = payload["records"]
        retriever._embeddings = payload["embeddings"]
        retriever._vectorizer = payload["vectorizer"]
        retriever._tfidf_matrix = payload["tfidf_matrix"]
        if retriever.backend == "sentence-transformers":
            from sentence_transformers import SentenceTransformer

            retriever._st_model = SentenceTransformer(EMBED_MODEL_NAME)
        return retriever

    # -- search --------------------------------------------------------------

    def search(self, query: str, top_k: int = RAG_TOP_K) -> list[dict]:
        """Return the top_k most relevant records, each with a `score` field."""
        if not self.records:
            return []
        if self.backend == "sentence-transformers":
            q = self._st_model.encode([query], normalize_embeddings=True)
            scores = (self._embeddings @ q.T).ravel()
        else:
            from sklearn.metrics.pairwise import cosine_similarity

            q_vec = self._vectorizer.transform([query])
            scores = cosine_similarity(q_vec, self._tfidf_matrix).ravel()

        top_idx = np.argsort(scores)[::-1][:top_k]
        return [{**self.records[i], "score": float(scores[i])} for i in top_idx if scores[i] > 0]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build or query the RAG index")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--query", type=str, default=None)
    args = parser.parse_args()

    if args.rebuild:
        CorpusRetriever().build().save()
    if args.query:
        retriever = CorpusRetriever.load()
        for hit in retriever.search(args.query):
            print(f"[{hit['score']:.3f}] {hit['video_title']} @ {hit['timestamp']}")
            print(f"    {hit['transcript_text'][:180]}…\n")
