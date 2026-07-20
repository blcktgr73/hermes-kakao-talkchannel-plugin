from __future__ import annotations

import json

from hermes_kakao_talkchannel.transport.sse import (
    DEFAULT_MAX_RECONNECT_DELAY_MS,
    DEFAULT_RECONNECT_DELAY_MS,
    DEFAULT_TIMEOUT_MS,
    calculate_reconnect_delay,
    parse_sse_chunk,
)


def _event(name: str, data: dict[str, object], event_id: str | None = None) -> str:
    block = f"event: {name}\ndata: {json.dumps(data)}\n"
    if event_id:
        block += f"id: {event_id}\n"
    return block + "\n"


def test_defaults_match_the_original() -> None:
    assert DEFAULT_RECONNECT_DELAY_MS == 1000
    assert DEFAULT_MAX_RECONNECT_DELAY_MS == 30000
    assert DEFAULT_TIMEOUT_MS == 300000


def test_parses_a_single_event() -> None:
    parsed = parse_sse_chunk(_event("ping", {}))
    assert len(parsed.events) == 1
    assert parsed.events[0].event == "ping"
    assert parsed.events[0].data == {}
    assert parsed.parse_errors == 0


def test_parses_multiple_events_and_reports_consumed_bytes() -> None:
    chunk = _event("ping", {}) + _event("message", {"id": "m1"}, "42")
    parsed = parse_sse_chunk(chunk)
    assert [event.event for event in parsed.events] == ["ping", "message"]
    assert parsed.events[1].id == "42"
    assert parsed.consumed == len(chunk)


def test_incomplete_trailing_event_is_left_in_the_buffer() -> None:
    chunk = _event("ping", {}) + "event: message\ndata: {"
    parsed = parse_sse_chunk(chunk)
    assert len(parsed.events) == 1
    assert chunk[parsed.consumed :] == "event: message\ndata: {"


def test_malformed_json_counts_as_a_parse_error_and_is_dropped() -> None:
    parsed = parse_sse_chunk("event: message\ndata: {not json}\n\n")
    assert parsed.events == []
    assert parsed.parse_errors == 1


def test_event_without_a_name_is_dropped_silently() -> None:
    parsed = parse_sse_chunk("data: {}\n\n")
    assert parsed.events == []
    assert parsed.parse_errors == 0


def test_event_without_data_is_dropped_silently() -> None:
    parsed = parse_sse_chunk("event: ping\n\n")
    assert parsed.events == []
    assert parsed.parse_errors == 0


def test_multiline_data_is_joined_per_the_spec() -> None:
    # The original kept only the last line, losing everything before it. A
    # payload split across lines is valid SSE and must reassemble.
    parsed = parse_sse_chunk('event: message\ndata: {"a": 1,\ndata: "b": 2}\n\n')
    assert parsed.events[0].data == {"a": 1, "b": 2}


def test_a_single_data_line_is_unaffected() -> None:
    # Joining is a no-op here, which is why this did not need to wait for
    # proof that the relay ever sends multi-line payloads.
    parsed = parse_sse_chunk('event: message\ndata: {"a": 1}\n\n')
    assert parsed.events[0].data == {"a": 1}


def test_empty_buffer_yields_nothing() -> None:
    parsed = parse_sse_chunk("")
    assert parsed.events == []
    assert parsed.consumed == 0


def test_backoff_grows_exponentially() -> None:
    first = calculate_reconnect_delay(1, 1000, 30000)
    second = calculate_reconnect_delay(2, 1000, 30000)
    assert 2000 <= first < 2400
    assert 4000 <= second < 4800


def test_backoff_never_exceeds_the_cap() -> None:
    # The original capped first and added jitter afterwards, so 30000 could
    # come back as 35999.
    for attempt in range(40):
        for _ in range(25):
            assert calculate_reconnect_delay(attempt, 1000, 30000) <= 30000


def test_backoff_still_jitters_below_the_cap() -> None:
    delays = {calculate_reconnect_delay(1, 1000, 30000) for _ in range(200)}
    assert len(delays) > 1
    assert min(delays) >= 2000
