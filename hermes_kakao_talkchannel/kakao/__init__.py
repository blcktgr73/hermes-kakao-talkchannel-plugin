"""Pure KakaoTalk domain logic.

INVARIANT: nothing in this package may import Hermes. It is host-agnostic by
design so it stays portable and unit-testable without a running gateway.
``tests/test_invariants.py`` enforces this with an AST check.
"""

from __future__ import annotations

from .callback import (
    CallbackResult,
    CallbackTracker,
    PendingCallback,
    create_callback_tracker,
    is_callback_expired,
    send_callback,
)
from .chunking import DEFAULT_CHUNK_LIMIT, ChunkMode, chunk_text_for_kakao
from .limits import KAKAO_LIMITS, KakaoLimits, ValidationResult
from .markdown import strip_markdown
from .payload import (
    MAX_UTTERANCE_LENGTH,
    ParsedKakaoUser,
    extract_user_id,
    extract_utterance,
    get_callback_url,
    has_callback_url,
    parse_kakao_user,
    parse_skill_payload,
)
from .response import (
    build_basic_card_response,
    build_callback_ack_response,
    build_carousel_response,
    build_commerce_card_response,
    build_error_response,
    build_item_card_response,
    build_list_card_response,
    build_multi_text_response,
    build_quick_replies,
    build_simple_image_response,
    build_simple_text_response,
    build_text_card_response,
)

__all__ = [
    "DEFAULT_CHUNK_LIMIT",
    "KAKAO_LIMITS",
    "MAX_UTTERANCE_LENGTH",
    "CallbackResult",
    "CallbackTracker",
    "ChunkMode",
    "KakaoLimits",
    "ParsedKakaoUser",
    "PendingCallback",
    "ValidationResult",
    "build_basic_card_response",
    "build_callback_ack_response",
    "build_carousel_response",
    "build_commerce_card_response",
    "build_error_response",
    "build_item_card_response",
    "build_list_card_response",
    "build_multi_text_response",
    "build_quick_replies",
    "build_simple_image_response",
    "build_simple_text_response",
    "build_text_card_response",
    "chunk_text_for_kakao",
    "create_callback_tracker",
    "extract_user_id",
    "extract_utterance",
    "get_callback_url",
    "has_callback_url",
    "is_callback_expired",
    "parse_kakao_user",
    "parse_skill_payload",
    "send_callback",
    "strip_markdown",
]
