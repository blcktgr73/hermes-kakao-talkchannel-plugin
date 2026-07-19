"""Builders for KakaoTalk Open Builder v2.0 skill responses.

Faithful port of the builder half of ``src/kakao/response.ts``.

One deliberate difference from the TypeScript original: where JS produced keys
whose value was ``undefined`` (dropped by ``JSON.stringify``), Python omits the
key entirely. The resulting JSON is identical.

``build_quick_replies`` has no TypeScript counterpart — the original plugin
declared the types and validators but never shipped a builder.
"""

from __future__ import annotations

from typing import Any, Literal

CarouselType = Literal["basicCard", "commerceCard", "itemCard", "textCard"]

_CAROUSEL_KEYS: tuple[CarouselType, ...] = (
    "basicCard",
    "commerceCard",
    "itemCard",
    "textCard",
)


def _template(outputs: list[dict[str, Any]]) -> dict[str, Any]:
    return {"version": "2.0", "template": {"outputs": outputs}}


def build_simple_text_response(text: str) -> dict[str, Any]:
    return _template([{"simpleText": {"text": text}}])


def build_callback_ack_response() -> dict[str, Any]:
    """Acknowledge the skill callback without a template.

    Tells Kakao the real answer will arrive later on ``userRequest.callbackUrl``.
    """
    return {"version": "2.0", "useCallback": True}


def build_error_response(message: str) -> dict[str, Any]:
    return _template([{"simpleText": {"text": message}}])


def build_multi_text_response(texts: list[str]) -> dict[str, Any]:
    """Up to OUTPUTS_MAX (3) text bubbles; extras are dropped."""
    return _template([{"simpleText": {"text": text}} for text in texts[:3]])


def build_simple_image_response(image_url: str, alt_text: str | None = None) -> dict[str, Any]:
    image: dict[str, Any] = {"imageUrl": image_url}
    if alt_text is not None:
        image["altText"] = alt_text
    return _template([{"simpleImage": image}])


def build_text_card_response(options: dict[str, Any]) -> dict[str, Any]:
    return _template([{"textCard": options}])


def build_basic_card_response(options: dict[str, Any]) -> dict[str, Any]:
    return _template([{"basicCard": options}])


def build_commerce_card_response(options: dict[str, Any]) -> dict[str, Any]:
    return _template([{"commerceCard": options}])


def build_list_card_response(
    header: dict[str, Any],
    items: list[dict[str, Any]],
    buttons: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Up to LIST_ITEMS_MAX (5) items; extras are dropped."""
    list_card: dict[str, Any] = {"header": header, "items": items[:5]}
    if buttons is not None:
        list_card["buttons"] = buttons
    return _template([{"listCard": list_card}])


def build_item_card_response(options: dict[str, Any]) -> dict[str, Any]:
    return _template([{"itemCard": options}])


def build_carousel_response(
    carousel_type: CarouselType,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Up to CAROUSEL_MAX (10) cards, all of the same type.

    Each item arrives wrapped (``{"basicCard": {...}}``) and is unwrapped into
    the carousel's flat item list.
    """
    carousel_items: list[dict[str, Any]] = []

    for index, item in enumerate(items[:10]):
        item_type = next((key for key in _CAROUSEL_KEYS if key in item), None)

        if item_type is None:
            raise ValueError(f"Invalid carousel item at index {index}: expected card type")
        if item_type != carousel_type:
            raise ValueError(
                f"Carousel type mismatch at index {index}: "
                f"expected '{carousel_type}' but got '{item_type}'"
            )

        carousel_items.append(item[item_type])

    return _template([{"carousel": {"type": carousel_type, "items": carousel_items}}])


def build_quick_replies(
    response: dict[str, Any],
    quick_replies: list[dict[str, Any]],
) -> dict[str, Any]:
    """Attach quick replies to an existing response, capped at QUICK_REPLIES_MAX (10).

    New in the Python port. Mutates and returns ``response``; a response built by
    ``build_callback_ack_response`` has no template, so quick replies are ignored.
    """
    template = response.get("template")
    if template is None:
        return response
    template["quickReplies"] = quick_replies[:10]
    return response
