"""Splitting long agent replies into KakaoTalk-sized chunks.

Faithful port of the chunking half of ``src/kakao/response.ts``.

Two original behaviours are preserved deliberately:

* ``chunk_text_for_kakao("")`` returns ``[""]``, not ``[]``.
* ``_chunk_by_sentence`` ignores a sentence terminator at index 0 (``> 0``, not
  ``>= 0``), so a leading "." never produces an empty first chunk.
"""

from __future__ import annotations

import re
from typing import Literal

ChunkMode = Literal["sentence", "newline", "length"]

DEFAULT_CHUNK_LIMIT = 400

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")


def chunk_text_for_kakao(
    text: str,
    limit: int = DEFAULT_CHUNK_LIMIT,
    mode: ChunkMode = "sentence",
) -> list[str]:
    """Split ``text`` into chunks of at most ``limit`` characters."""
    if not text or len(text) <= limit:
        return [text]

    if mode == "newline":
        return _chunk_by_newline(text, limit)
    if mode == "length":
        return _chunk_by_length(text, limit)
    return _chunk_by_sentence(text, limit)


def _chunk_by_sentence(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    remaining = text

    while len(remaining) > 0:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        window = remaining[:limit]
        last_sentence_end = max(window.rfind("."), window.rfind("!"), window.rfind("?"))

        if last_sentence_end > 0:
            chunks.append(remaining[: last_sentence_end + 1])
            remaining = remaining[last_sentence_end + 1 :].strip()
        else:
            chunks.append(remaining[:limit])
            remaining = remaining[limit:].strip()

    return chunks


def _chunk_by_newline(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    current = ""

    for paragraph in _PARAGRAPH_SPLIT.split(text):
        trimmed = paragraph.strip()
        if not trimmed:
            continue

        if len(current) == 0:
            if len(trimmed) <= limit:
                current = trimmed
            else:
                chunks.extend(_chunk_by_sentence(trimmed, limit))
        elif len(current) + 2 + len(trimmed) <= limit:
            current += "\n\n" + trimmed
        else:
            chunks.append(current)
            if len(trimmed) <= limit:
                current = trimmed
            else:
                chunks.extend(_chunk_by_sentence(trimmed, limit))
                current = ""

    if current:
        chunks.append(current)

    return chunks


def _chunk_by_length(text: str, limit: int) -> list[str]:
    return [text[i : i + limit] for i in range(0, len(text), limit)]
