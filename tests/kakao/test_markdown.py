from __future__ import annotations

import pytest

from hermes_kakao_talkchannel.kakao.markdown import strip_markdown


def test_empty_input_is_returned_unchanged() -> None:
    assert strip_markdown("") == ""


def test_fenced_code_block_keeps_body_drops_fence() -> None:
    text = "before\n```python\nprint('hi')\n```\nafter"
    result = strip_markdown(text)
    assert "```" not in result
    assert "print('hi')" in result


def test_inline_code_is_unwrapped() -> None:
    assert strip_markdown("use `pnpm test` now") == "use pnpm test now"


def test_image_becomes_korean_placeholder() -> None:
    assert strip_markdown("![고양이](https://x.example/a.png)") == "[이미지: 고양이]"


def test_link_becomes_label_with_url_in_parens() -> None:
    assert strip_markdown("[문서](https://x.example)") == "문서 (https://x.example)"


def test_image_is_processed_before_link() -> None:
    # If links ran first the "!" would be left dangling.
    assert strip_markdown("![alt](https://x.example/a.png)").startswith("[이미지:")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("# 제목", "제목"),
        ("###### 작은 제목", "작은 제목"),
        ("**굵게**", "굵게"),
        ("__굵게__", "굵게"),
        ("*기울임*", "기울임"),
        ("_기울임_", "기울임"),
        ("~~취소선~~", "취소선"),
        ("> 인용문", "인용문"),
    ],
)
def test_basic_inline_syntax_is_stripped(source: str, expected: str) -> None:
    assert strip_markdown(source) == expected


def test_horizontal_rule_is_removed() -> None:
    assert strip_markdown("위\n\n---\n\n아래") == "위\n\n아래"


def test_bullets_become_bullet_character() -> None:
    result = strip_markdown("- 하나\n- 둘")
    assert result == "• 하나\n• 둘"


def test_numbered_list_loses_its_numbering() -> None:
    # AS-IS behaviour ported from the original: numbering is dropped entirely.
    assert strip_markdown("1. 하나\n2. 둘") == "하나\n둘"


def test_three_or_more_newlines_collapse_to_two() -> None:
    assert strip_markdown("a\n\n\n\n\nb") == "a\n\nb"


def test_result_is_trimmed() -> None:
    assert strip_markdown("\n\n# 제목\n\n") == "제목"


def test_indented_heading_is_left_alone() -> None:
    # AS-IS: the heading regex is anchored with ^, so a leading space defeats it.
    # Same in the TypeScript original.
    assert strip_markdown("   # 제목") == "# 제목"
