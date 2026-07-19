from __future__ import annotations

from hermes_kakao_talkchannel.kakao.limits import (
    KakaoLimits,
    validate_button,
    validate_card_description,
    validate_card_title,
    validate_carousel_item_count,
    validate_list_item_count,
    validate_output_count,
    validate_quick_replies,
    validate_simple_text,
)


def test_constants_match_the_kakao_spec() -> None:
    assert KakaoLimits.SIMPLE_TEXT_MAX == 1000
    assert KakaoLimits.SIMPLE_TEXT_VISIBLE == 400
    assert KakaoLimits.CARD_TITLE == 50
    assert KakaoLimits.CARD_DESCRIPTION == 230
    assert KakaoLimits.BUTTON_LABEL == 14
    assert KakaoLimits.QUICK_REPLY_LABEL == 14
    assert KakaoLimits.QUICK_REPLIES_MAX == 10
    assert KakaoLimits.OUTPUTS_MAX == 3
    assert KakaoLimits.CAROUSEL_MIN == 2
    assert KakaoLimits.CAROUSEL_MAX == 10
    assert KakaoLimits.LIST_ITEMS_MIN == 2
    assert KakaoLimits.LIST_ITEMS_MAX == 5


def test_simple_text_at_limit_passes() -> None:
    assert validate_simple_text("a" * 1000).valid is True


def test_simple_text_over_limit_reports_actual_length() -> None:
    result = validate_simple_text("a" * 1001)
    assert result.valid is False
    assert result.error == "Text exceeds 1000 characters (got 1001)"


def test_card_title_and_description() -> None:
    assert validate_card_title("a" * 50).valid is True
    assert validate_card_title("a" * 51).error == "Card title exceeds 50 characters (got 51)"
    assert validate_card_description("a" * 230).valid is True
    assert (
        validate_card_description("a" * 231).error
        == "Card description exceeds 230 characters (got 231)"
    )


def test_button_label() -> None:
    assert validate_button({"label": "a" * 14}).valid is True
    assert (
        validate_button({"label": "a" * 15}).error
        == "Button label exceeds 14 characters (got 15)"
    )


def test_quick_replies_count_limit() -> None:
    replies = [{"label": "ok"} for _ in range(11)]
    assert validate_quick_replies(replies).error == "Quick replies exceed max of 10 (got 11)"


def test_quick_replies_reports_first_bad_index() -> None:
    replies = [{"label": "ok"}, {"label": "a" * 20}]
    result = validate_quick_replies(replies)
    assert result.valid is False
    assert result.error is not None
    assert result.error.startswith("Quick reply 1: ")


def test_output_count() -> None:
    assert validate_output_count(3).valid is True
    assert validate_output_count(4).error == "Outputs exceed max of 3 (got 4)"


def test_carousel_item_count_checks_min_before_max() -> None:
    assert validate_carousel_item_count(1).error == "Carousel requires at least 2 items (got 1)"
    assert validate_carousel_item_count(2).valid is True
    assert validate_carousel_item_count(10).valid is True
    assert validate_carousel_item_count(11).error == "Carousel exceeds max of 10 items (got 11)"


def test_list_item_count() -> None:
    assert validate_list_item_count(1).error == "List requires at least 2 items (got 1)"
    assert validate_list_item_count(5).valid is True
    assert validate_list_item_count(6).error == "List exceeds max of 5 items (got 6)"
