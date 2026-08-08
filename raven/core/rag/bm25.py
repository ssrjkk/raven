from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class BM25Index:
    """Okapi BM25 scoring (k1=1.5, b=0.75) with no external dependencies.

    Build once over a document corpus, then score queries against it.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._docs: list[list[str]] = []
        self._doc_lens: list[int] = []
        self._avgdl: float = 0.0
        self._df: Counter[str] = Counter()
        self._fitted = False

    def fit(self, docs: list[str]) -> BM25Index:
        self._docs = [tokenize(d) for d in docs]
        self._doc_lens = [len(d) for d in self._docs]
        total = sum(self._doc_lens)
        self._avgdl = total / len(self._docs) if self._docs else 0.0
        self._df = Counter()
        for tokens in self._docs:
            for term in set(tokens):
                self._df[term] += 1
        self._fitted = True
        return self

    def _idf(self, term: str) -> float:
        n = len(self._docs)
        if n == 0:
            return 0.0
        df = self._df.get(term, 0)
        return math.log(1.0 + (n - df + 0.5) / (df + 0.5))

    def scores(self, query: str) -> list[float]:
        if not self._fitted or not self._docs:
            return [0.0] * len(self._docs)
        terms = tokenize(query)
        if not terms:
            return [0.0] * len(self._docs)
        term_counts = Counter(terms)
        k1 = self.k1
        b = self.b
        results: list[float] = []
        for doc_id, tokens in enumerate(self._docs):
            doc_len = self._doc_lens[doc_id]
            denom = 1.0 - b + b * (doc_len / self._avgdl) if self._avgdl > 0 else 1.0
            counts = Counter(tokens)
            score = 0.0
            for term, qf in term_counts.items():
                tf = counts.get(term, 0)
                if tf == 0:
                    continue
                idf = self._idf(term)
                score += qf * idf * (tf * (k1 + 1.0)) / (tf + k1 * denom)
            results.append(score)
        return results
