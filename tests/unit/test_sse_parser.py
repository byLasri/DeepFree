import pytest
from src.protocol.sse_parser import (
    parse_sse_stream,
    normalize_events,
    reconstruct_response,
    extract_message_ids,
    SSEEventType,
    OperationType,
)


SAMPLE_SSE = """event: ready
data: {"request_message_id":1,"response_message_id":2,"model_type":"expert"}

event: update_session
data: {"updated_at":"2024-01-15T10:30:00Z"}

data: {"v":{"response":{"message_id":2,"parent_id":1,"status":"IN_PROGRESS"}}}

data: {"p":"response/fragments/-1/content","o":"APPEND","v":"Hello"}

data: {"p":"response/fragments/-1/content","o":"APPEND","v":" world"}

data: {"p":"response/fragments/-1/elapsed_secs","o":"SET","v":1.5}

data: {"p":"response/status","o":"SET","v":"FINISHED"}

event: update_session
data: {"updated_at":"2024-01-15T10:30:05Z"}

event: title
data: {"content":"Say hello"}

event: close
data: {"click_behavior":"none","auto_resume":false}
"""


def test_parse_sse_stream():
    events = parse_sse_stream(SAMPLE_SSE)
    assert len(events) == 10
    assert events[0].event_type == SSEEventType.READY
    assert events[1].event_type == SSEEventType.UPDATE_SESSION
    assert events[2].event_type == SSEEventType.DATA
    assert events[9].event_type == SSEEventType.CLOSE


def test_normalize_events():
    events = parse_sse_stream(SAMPLE_SSE)
    normalized = normalize_events(events)
    assert len(normalized) == 10
    assert normalized[0].request_message_id == 1
    assert normalized[0].response_message_id == 2
    assert normalized[0].model_type == "expert"
    assert normalized[1].session_updated_at == "2024-01-15T10:30:00Z"
    assert normalized[8].title == "Say hello"
    assert normalized[9].close_click_behavior == "none"
    assert normalized[9].close_auto_resume is False


def test_reconstruct_response():
    events = parse_sse_stream(SAMPLE_SSE)
    normalized = normalize_events(events)
    content = reconstruct_response(normalized)
    assert content == "Hello world"


def test_extract_message_ids():
    events = parse_sse_stream(SAMPLE_SSE)
    normalized = normalize_events(events)
    req_id, resp_id = extract_message_ids(normalized)
    assert req_id == 1
    assert resp_id == 2


def test_path_updates():
    events = parse_sse_stream(SAMPLE_SSE)
    normalized = normalize_events(events)

    data_events = [e for e in normalized if e.event_type == SSEEventType.DATA]
    path_updates = []
    for e in data_events:
        path_updates.extend(e.path_updates)

    assert len(path_updates) >= 4
    content_updates = [pu for pu in path_updates if "content" in pu.path]
    assert len(content_updates) == 2
    assert content_updates[0].value == "Hello"
    assert content_updates[1].value == " world"
    assert content_updates[0].operation == OperationType.APPEND

    elapsed_updates = [pu for pu in path_updates if "elapsed_secs" in pu.path]
    assert len(elapsed_updates) == 1
    assert elapsed_updates[0].value == 1.5
    assert elapsed_updates[0].operation == OperationType.SET

    status_updates = [pu for pu in path_updates if "status" in pu.path]
    assert len(status_updates) == 1
    assert status_updates[0].value == "FINISHED"
    assert status_updates[0].operation == OperationType.SET


def test_empty_stream():
    events = parse_sse_stream("")
    assert len(events) == 0


def test_comment_lines():
    sse = """: comment line
event: ready
data: {"test": "value"}
"""
    events = parse_sse_stream(sse)
    assert len(events) == 1
    assert events[0].event_type == SSEEventType.READY


def test_data_only_no_event():
    sse = """data: {"p":"test","o":"SET","v":"value"}
"""
    events = parse_sse_stream(sse)
    assert len(events) == 1
    assert events[0].event_type == SSEEventType.DATA


if __name__ == "__main__":
    pytest.main([__file__, "-v"])