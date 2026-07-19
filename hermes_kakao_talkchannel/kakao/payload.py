"""Parsing inbound KakaoTalk Open Builder skill payloads.

Faithful port of ``src/kakao/payload.ts``. Validation order and error strings
match the original exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MAX_UTTERANCE_LENGTH = 5000


@dataclass(frozen=True)
class ParsedKakaoUser:
    bot_user_key: str
    plusfriend_user_key: str | None
    is_friend: bool


def _require_field(obj: dict[str, Any], field: str, context: str) -> None:
    """Truthiness check, matching the original ``requireField``."""
    if not obj.get(field):
        raise ValueError(f"{context} missing required field: {field}")


def parse_skill_payload(body: Any) -> dict[str, Any]:
    """Validate an inbound skill payload and return it unchanged.

    Like the original, this returns the *same* object rather than a copy.
    """
    if body is None or not isinstance(body, dict):
        raise ValueError("SkillPayload must be an object")

    _require_field(body, "intent", "SkillPayload")
    _require_field(body, "userRequest", "SkillPayload")
    _require_field(body, "bot", "SkillPayload")
    _require_field(body, "action", "SkillPayload")

    user_request = body["userRequest"]
    _require_field(user_request, "utterance", "userRequest")

    utterance = user_request["utterance"]
    if not isinstance(utterance, str) or utterance.strip() == "":
        raise ValueError("userRequest.utterance must be a non-empty string")
    if len(utterance) > MAX_UTTERANCE_LENGTH:
        raise ValueError(
            f"userRequest.utterance exceeds maximum length of {MAX_UTTERANCE_LENGTH} characters"
        )

    _require_field(user_request, "user", "userRequest")
    _require_field(user_request["user"], "id", "userRequest.user")

    return body


def extract_user_id(payload: dict[str, Any]) -> str:
    user_id = payload["userRequest"]["user"].get("id")
    if not user_id:
        raise ValueError("Cannot extract userId: user.id is missing")
    return str(user_id)


def extract_utterance(payload: dict[str, Any]) -> str:
    """Return the utterance untrimmed, matching the original."""
    utterance = payload["userRequest"].get("utterance")
    if not utterance or utterance.strip() == "":
        raise ValueError("Cannot extract utterance: utterance is missing or empty")
    return str(utterance)


def parse_kakao_user(payload: dict[str, Any]) -> ParsedKakaoUser:
    user = payload["userRequest"]["user"]
    if not user.get("id"):
        raise ValueError("Cannot parse user: user.id is missing")

    properties = user.get("properties") or {}
    return ParsedKakaoUser(
        bot_user_key=str(user["id"]),
        plusfriend_user_key=properties.get("plusfriendUserKey"),
        is_friend=bool(properties.get("isFriend", False)),
    )


def get_callback_url(payload: dict[str, Any]) -> str | None:
    """Return the callback URL untrimmed, or None when absent/blank."""
    callback_url = payload["userRequest"].get("callbackUrl")
    if callback_url and callback_url.strip() != "":
        return str(callback_url)
    return None


def has_callback_url(payload: dict[str, Any]) -> bool:
    return get_callback_url(payload) is not None
