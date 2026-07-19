from __future__ import annotations

from hermes_kakao_talkchannel.kakao.chunking import DEFAULT_CHUNK_LIMIT, chunk_text_for_kakao


def test_default_limit_is_400() -> None:
    assert DEFAULT_CHUNK_LIMIT == 400


def test_short_text_is_returned_as_single_chunk() -> None:
    assert chunk_text_for_kakao("짧은 문장", limit=100) == ["짧은 문장"]


def test_empty_text_returns_list_with_empty_string() -> None:
    # AS-IS: the original returns [""] rather than [].
    assert chunk_text_for_kakao("", limit=100) == [""]


def test_text_exactly_at_limit_is_not_split() -> None:
    text = "a" * 100
    assert chunk_text_for_kakao(text, limit=100) == [text]


def test_sentence_mode_splits_on_sentence_boundary() -> None:
    text = "첫 번째 문장입니다. " + "가" * 60 + ". 마지막."
    chunks = chunk_text_for_kakao(text, limit=40, mode="sentence")
    assert len(chunks) > 1
    assert chunks[0].endswith(".")
    assert all(len(chunk) <= 40 or "." not in chunk[:40] for chunk in chunks)


def test_sentence_mode_falls_back_to_hard_cut_without_terminator() -> None:
    text = "가" * 250
    chunks = chunk_text_for_kakao(text, limit=100, mode="sentence")
    assert [len(chunk) for chunk in chunks] == [100, 100, 50]


def test_length_mode_is_fixed_width_and_does_not_trim() -> None:
    text = "ab cd ef gh"
    assert chunk_text_for_kakao(text, limit=4, mode="length") == ["ab c", "d ef", " gh"]


def test_newline_mode_packs_paragraphs_greedily() -> None:
    text = "첫째 문단.\n\n둘째 문단.\n\n셋째 문단."
    chunks = chunk_text_for_kakao(text, limit=20, mode="newline")
    assert all(len(chunk) <= 20 for chunk in chunks)
    assert "\n\n".join(chunks).replace("\n\n", " ").count("문단") == 3


def test_newline_mode_delegates_oversized_paragraph_to_sentence_mode() -> None:
    long_paragraph = "가" * 120
    text = f"짧은 문단.\n\n{long_paragraph}"
    chunks = chunk_text_for_kakao(text, limit=50, mode="newline")
    assert all(len(chunk) <= 50 for chunk in chunks)
    assert chunks[0] == "짧은 문단."


def test_no_chunk_exceeds_the_limit_in_sentence_mode() -> None:
    text = ("문장 하나. " * 200).strip()
    for chunk in chunk_text_for_kakao(text, limit=120, mode="sentence"):
        assert len(chunk) <= 120
