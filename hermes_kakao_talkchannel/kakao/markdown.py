"""Markdown stripping — KakaoTalk renders no markdown at all.

Faithful port of ``stripMarkdown`` from ``src/kakao/response.ts``. The regex
pipeline order matters (fences before inline code, images before links), so the
steps are numbered to match the original.
"""

from __future__ import annotations

import re

_CODE_FENCE = re.compile(r"```[\s\S]*?```")
_FENCE_OPEN = re.compile(r"```\w*\n?")
_FENCE_CLOSE = re.compile(r"```$")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_BOLD_STAR = re.compile(r"\*\*([^*]+)\*\*")
_BOLD_UNDERSCORE = re.compile(r"__([^_]+)__")
# Both lookbehind branches are width 1, which Python's `re` accepts.
_ITALIC_STAR = re.compile(r"(?<!\n)(?<!\*)\*([^*\n]+)\*(?!\*)")
_ITALIC_UNDERSCORE = re.compile(r"(?<!\n)(?<!_)_([^_\n]+)_(?!_)")
_STRIKETHROUGH = re.compile(r"~~([^~]+)~~")
_BLOCKQUOTE = re.compile(r"^>\s?", re.MULTILINE)
_HORIZONTAL_RULE = re.compile(r"^[-*_]{3,}\s*$", re.MULTILINE)
_BULLET = re.compile(r"^[\s]*[-*+]\s+", re.MULTILINE)
_NUMBERED = re.compile(r"^[\s]*\d+\.\s+", re.MULTILINE)
_BLANK_LINES = re.compile(r"\n{3,}")


def _strip_fence(match: re.Match[str]) -> str:
    body = match.group(0)
    body = _FENCE_OPEN.sub("", body)
    body = _FENCE_CLOSE.sub("", body)
    return body.strip()


def strip_markdown(text: str) -> str:
    """Remove markdown syntax that KakaoTalk would otherwise show literally."""
    if not text:
        return text

    result = _CODE_FENCE.sub(_strip_fence, text)          # 1. fenced code blocks
    result = _INLINE_CODE.sub(r"\1", result)              # 2. inline code
    result = _IMAGE.sub(r"[이미지: \1]", result)           # 3. images
    result = _LINK.sub(r"\1 (\2)", result)                # 4. links
    result = _HEADING.sub("", result)                     # 5. headings
    result = _BOLD_STAR.sub(r"\1", result)                # 6. **bold**
    result = _BOLD_UNDERSCORE.sub(r"\1", result)          # 7. __bold__
    result = _ITALIC_STAR.sub(r"\1", result)              # 8. *italic*
    result = _ITALIC_UNDERSCORE.sub(r"\1", result)        # 9. _italic_
    result = _STRIKETHROUGH.sub(r"\1", result)            # 10. ~~strike~~
    result = _BLOCKQUOTE.sub("", result)                  # 11. blockquotes
    result = _HORIZONTAL_RULE.sub("", result)             # 12. horizontal rules
    result = _BULLET.sub("• ", result)                    # 13. bullets -> •
    result = _NUMBERED.sub("", result)                    # 14. numbering dropped
    result = _BLANK_LINES.sub("\n\n", result)             # 15. collapse blank lines
    return result.strip()                                 # 16.
