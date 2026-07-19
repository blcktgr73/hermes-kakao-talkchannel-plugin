"""KakaoTalk Open Builder v2.0 response limits and validators.

Faithful port of ``src/kakao/limits.ts``. Every constant and every error message
matches the TypeScript original so behaviour is comparable across the two plugins.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final


class KakaoLimits:
    """Numeric limits imposed by the KakaoTalk Open Builder skill response format."""

    SIMPLE_TEXT_MAX: Final = 1000
    SIMPLE_TEXT_VISIBLE: Final = 400
    CARD_TITLE: Final = 50
    CARD_DESCRIPTION: Final = 230
    BUTTON_LABEL: Final = 14
    QUICK_REPLY_LABEL: Final = 14
    QUICK_REPLIES_MAX: Final = 10
    OUTPUTS_MAX: Final = 3
    CAROUSEL_MIN: Final = 2
    CAROUSEL_MAX: Final = 10
    LIST_ITEMS_MIN: Final = 2
    LIST_ITEMS_MAX: Final = 5


KAKAO_LIMITS = KakaoLimits


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    error: str | None = None


_OK = ValidationResult(valid=True)


def _fail(message: str) -> ValidationResult:
    return ValidationResult(valid=False, error=message)


def validate_simple_text(text: str) -> ValidationResult:
    if len(text) > KakaoLimits.SIMPLE_TEXT_MAX:
        return _fail(
            f"Text exceeds {KakaoLimits.SIMPLE_TEXT_MAX} characters (got {len(text)})"
        )
    return _OK


def validate_card_title(title: str) -> ValidationResult:
    if len(title) > KakaoLimits.CARD_TITLE:
        return _fail(
            f"Card title exceeds {KakaoLimits.CARD_TITLE} characters (got {len(title)})"
        )
    return _OK


def validate_card_description(description: str) -> ValidationResult:
    if len(description) > KakaoLimits.CARD_DESCRIPTION:
        return _fail(
            "Card description exceeds "
            f"{KakaoLimits.CARD_DESCRIPTION} characters (got {len(description)})"
        )
    return _OK


def validate_button(button: dict[str, Any]) -> ValidationResult:
    label = button.get("label", "")
    if len(label) > KakaoLimits.BUTTON_LABEL:
        return _fail(
            f"Button label exceeds {KakaoLimits.BUTTON_LABEL} characters (got {len(label)})"
        )
    return _OK


def validate_quick_reply(reply: dict[str, Any]) -> ValidationResult:
    label = reply.get("label", "")
    if len(label) > KakaoLimits.QUICK_REPLY_LABEL:
        return _fail(
            "Quick reply label exceeds "
            f"{KakaoLimits.QUICK_REPLY_LABEL} characters (got {len(label)})"
        )
    return _OK


def validate_quick_replies(replies: list[dict[str, Any]]) -> ValidationResult:
    if len(replies) > KakaoLimits.QUICK_REPLIES_MAX:
        return _fail(
            f"Quick replies exceed max of {KakaoLimits.QUICK_REPLIES_MAX} (got {len(replies)})"
        )
    for index, reply in enumerate(replies):
        result = validate_quick_reply(reply)
        if not result.valid:
            return _fail(f"Quick reply {index}: {result.error}")
    return _OK


def validate_output_count(count: int) -> ValidationResult:
    if count > KakaoLimits.OUTPUTS_MAX:
        return _fail(f"Outputs exceed max of {KakaoLimits.OUTPUTS_MAX} (got {count})")
    return _OK


def validate_carousel_item_count(count: int) -> ValidationResult:
    if count < KakaoLimits.CAROUSEL_MIN:
        return _fail(
            f"Carousel requires at least {KakaoLimits.CAROUSEL_MIN} items (got {count})"
        )
    if count > KakaoLimits.CAROUSEL_MAX:
        return _fail(
            f"Carousel exceeds max of {KakaoLimits.CAROUSEL_MAX} items (got {count})"
        )
    return _OK


def validate_list_item_count(count: int) -> ValidationResult:
    if count < KakaoLimits.LIST_ITEMS_MIN:
        return _fail(f"List requires at least {KakaoLimits.LIST_ITEMS_MIN} items (got {count})")
    if count > KakaoLimits.LIST_ITEMS_MAX:
        return _fail(f"List exceeds max of {KakaoLimits.LIST_ITEMS_MAX} items (got {count})")
    return _OK
