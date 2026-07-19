"""Representative KakaoTalk Open Builder skill payloads."""

from __future__ import annotations

import copy
from typing import Any

VALID_SKILL_PAYLOAD: dict[str, Any] = {
    "intent": {"id": "intent-1", "name": "fallback"},
    "userRequest": {
        "timezone": "Asia/Seoul",
        "utterance": "안녕하세요",
        "lang": "kr",
        "user": {
            "id": "botuserkey-abc123",
            "type": "botUserKey",
            "properties": {
                "plusfriendUserKey": "plusfriend-xyz",
                "isFriend": True,
            },
        },
        "block": {"id": "block-1", "name": "폴백 블록"},
        "callbackUrl": "https://callback.kakao.example/v1/callback/abc",
    },
    "bot": {"id": "bot-1", "name": "테스트봇"},
    "action": {
        "id": "action-1",
        "name": "fallbackAction",
        "params": {},
        "detailParams": {},
        "clientExtra": {},
    },
}

MINIMAL_SKILL_PAYLOAD: dict[str, Any] = {
    "intent": {"id": "intent-1", "name": "fallback"},
    "userRequest": {
        "timezone": "Asia/Seoul",
        "utterance": "hi",
        "lang": "kr",
        "user": {"id": "botuserkey-minimal", "type": "botUserKey", "properties": {}},
    },
    "bot": {"id": "bot-1", "name": "테스트봇"},
    "action": {
        "id": "action-1",
        "name": "fallbackAction",
        "params": {},
        "detailParams": {},
        "clientExtra": {},
    },
}

INBOUND_MESSAGE_WIRE: dict[str, Any] = {
    "id": "msg-0001",
    "conversationKey": "conv-abc",
    "kakaoPayload": VALID_SKILL_PAYLOAD,
    "normalized": {
        "userId": "botuserkey-abc123",
        "text": "안녕하세요",
        "channelId": "@testchannel",
    },
    "createdAt": "2026-07-19T09:00:00.000Z",
}


def valid_payload() -> dict[str, Any]:
    return copy.deepcopy(VALID_SKILL_PAYLOAD)


def minimal_payload() -> dict[str, Any]:
    return copy.deepcopy(MINIMAL_SKILL_PAYLOAD)


def inbound_wire(**overrides: Any) -> dict[str, Any]:
    data = copy.deepcopy(INBOUND_MESSAGE_WIRE)
    data.update(overrides)
    return data
