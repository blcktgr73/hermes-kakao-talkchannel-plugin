from __future__ import annotations

import pytest

from hermes_kakao_talkchannel.kakao.response import (
    build_callback_ack_response,
    build_carousel_response,
    build_list_card_response,
    build_multi_text_response,
    build_quick_replies,
    build_simple_image_response,
    build_simple_text_response,
    build_text_card_response,
)


def test_simple_text_shape() -> None:
    assert build_simple_text_response("안녕") == {
        "version": "2.0",
        "template": {"outputs": [{"simpleText": {"text": "안녕"}}]},
    }


def test_callback_ack_has_no_template() -> None:
    response = build_callback_ack_response()
    assert response == {"version": "2.0", "useCallback": True}
    assert "template" not in response


def test_multi_text_is_capped_at_three_outputs() -> None:
    response = build_multi_text_response(["1", "2", "3", "4", "5"])
    outputs = response["template"]["outputs"]
    assert len(outputs) == 3
    assert [output["simpleText"]["text"] for output in outputs] == ["1", "2", "3"]


def test_simple_image_omits_alt_text_when_absent() -> None:
    response = build_simple_image_response("https://x.example/a.png")
    assert response["template"]["outputs"][0]["simpleImage"] == {
        "imageUrl": "https://x.example/a.png"
    }


def test_simple_image_includes_alt_text_when_given() -> None:
    response = build_simple_image_response("https://x.example/a.png", "고양이")
    assert response["template"]["outputs"][0]["simpleImage"]["altText"] == "고양이"


def test_text_card_passes_options_through() -> None:
    options = {"title": "제목", "description": "설명", "buttons": []}
    assert build_text_card_response(options)["template"]["outputs"][0]["textCard"] == options


def test_list_card_is_capped_at_five_items() -> None:
    header = {"title": "헤더"}
    items = [{"title": f"항목 {i}"} for i in range(8)]
    list_card = build_list_card_response(header, items)["template"]["outputs"][0]["listCard"]
    assert len(list_card["items"]) == 5
    assert "buttons" not in list_card


def test_list_card_includes_buttons_when_given() -> None:
    list_card = build_list_card_response(
        {"title": "헤더"}, [{"title": "항목"}], [{"label": "더보기", "action": "message"}]
    )["template"]["outputs"][0]["listCard"]
    assert list_card["buttons"] == [{"label": "더보기", "action": "message"}]


def test_carousel_unwraps_items_and_caps_at_ten() -> None:
    items = [{"basicCard": {"title": f"카드 {i}", "thumbnail": {}}} for i in range(12)]
    carousel = build_carousel_response("basicCard", items)["template"]["outputs"][0]["carousel"]
    assert carousel["type"] == "basicCard"
    assert len(carousel["items"]) == 10
    assert carousel["items"][0] == {"title": "카드 0", "thumbnail": {}}


def test_carousel_rejects_item_without_a_card_type() -> None:
    with pytest.raises(ValueError, match="Invalid carousel item at index 1"):
        build_carousel_response("basicCard", [{"basicCard": {}}, {"nope": {}}])


def test_carousel_rejects_mixed_card_types() -> None:
    with pytest.raises(ValueError, match="expected 'basicCard' but got 'textCard'"):
        build_carousel_response("basicCard", [{"basicCard": {}}, {"textCard": {}}])


def test_quick_replies_are_capped_at_ten() -> None:
    response = build_simple_text_response("안녕")
    replies = [{"label": f"q{i}", "action": "message"} for i in range(15)]
    build_quick_replies(response, replies)
    assert len(response["template"]["quickReplies"]) == 10


def test_quick_replies_are_ignored_on_a_templateless_response() -> None:
    response = build_callback_ack_response()
    build_quick_replies(response, [{"label": "q", "action": "message"}])
    assert "template" not in response
