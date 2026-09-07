import pytest
import json
import tempfile
import os
from src.recorder.recorder import Recorder, SENSITIVE_HEADERS, SENSITIVE_BODY_KEYS


def test_redact_headers():
    recorder = Recorder()
    headers = {
        "Authorization": "Bearer secret-token",
        "Cookie": "session=abc123",
        "x-ds-pow-response": "pow-value",
        "x-hif-leim": "leim-value",
        "Content-Type": "application/json",
        "User-Agent": "test-agent",
    }
    redacted = recorder._redact_headers(headers)
    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["Cookie"] == "[REDACTED]"
    assert redacted["x-ds-pow-response"] == "[REDACTED]"
    assert redacted["x-hif-leim"] == "[REDACTED]"
    assert redacted["Content-Type"] == "application/json"
    assert redacted["User-Agent"] == "test-agent"


def test_redact_body_dict():
    recorder = Recorder()
    body = {
        "authorization": "Bearer token",
        "password": "secret123",
        "normal_field": "value",
        "nested": {
            "secret_key": "hidden",
            "public": "visible",
        },
        "list_field": [
            {"token": "abc"},
            {"normal": "data"},
        ],
    }
    redacted = recorder._redact_body(body)
    assert redacted["authorization"] == "[REDACTED]"
    assert redacted["password"] == "[REDACTED]"
    assert redacted["normal_field"] == "value"
    assert redacted["nested"]["secret_key"] == "[REDACTED]"
    assert redacted["nested"]["public"] == "visible"
    assert redacted["list_field"][0]["token"] == "[REDACTED]"
    assert redacted["list_field"][1]["normal"] == "data"


def test_redact_body_string_json():
    recorder = Recorder()
    body = '{"authorization": "Bearer token", "normal": "value"}'
    redacted = recorder._redact_body(body)
    assert redacted["authorization"] == "[REDACTED]"
    assert redacted["normal"] == "value"


def test_redact_body_non_json():
    recorder = Recorder()
    body = "plain text body"
    redacted = recorder._redact_body(body)
    assert redacted == "[REDACTED: non-JSON body]"


def test_redact_sse_events():
    recorder = Recorder()
    events = [
        {"event_type": "data", "data": {"authorization": "Bearer token", "normal": "value"}},
        {"event_type": "ready", "data": {"request_message_id": 1}},
    ]
    redacted = recorder._redact_sse_events(events)
    assert redacted[0]["data"]["authorization"] == "[REDACTED]"
    assert redacted[0]["data"]["normal"] == "value"
    assert redacted[1]["data"]["request_message_id"] == 1


def test_record_and_save():
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = Recorder(output_dir=tmpdir)
        recorder.record(
            url="https://chat.deepseek.com/api/v0/chat/completion",
            method="POST",
            request_headers={"Authorization": "Bearer secret", "Content-Type": "application/json"},
            request_body={"prompt": "test", "secret": "hidden"},
            response_status=200,
            response_headers={"Content-Type": "text/event-stream"},
            response_body='data: {"v": "response"}',
            sse_events=[{"event_type": "data", "data": {"v": "response"}}],
        )
        filepath = recorder.save("test_recording.json")
        assert os.path.exists(filepath)

        with open(filepath, "r") as f:
            data = json.load(f)
        assert len(data["exchanges"]) == 1
        ex = data["exchanges"][0]
        assert ex["request"]["headers"]["Authorization"] == "[REDACTED]"
        assert ex["request"]["body"]["secret"] == "[REDACTED]"
        assert ex["request"]["body"]["prompt"] == "test"


def test_load_recording():
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = Recorder(output_dir=tmpdir)
        recorder.record(
            url="https://test.com",
            method="GET",
            request_headers={"Authorization": "Bearer token"},
            request_body=None,
            response_status=200,
            response_headers={},
            response_body="{}",
        )
        filepath = recorder.save("test_load.json")

        new_recorder = Recorder(output_dir=tmpdir)
        exchanges = new_recorder.load(filepath)
        assert len(exchanges) == 1
        assert exchanges[0].request.url == "https://test.com"
        assert exchanges[0].request.headers["Authorization"] == "[REDACTED]"


def test_sensitive_header_detection():
    assert "authorization" in SENSITIVE_HEADERS
    assert "cookie" in SENSITIVE_HEADERS
    assert "x-ds-pow-response" in SENSITIVE_HEADERS
    assert "x-hif-leim" in SENSITIVE_HEADERS


def test_sensitive_body_key_detection():
    assert "authorization" in SENSITIVE_BODY_KEYS
    assert "token" in SENSITIVE_BODY_KEYS
    assert "password" in SENSITIVE_BODY_KEYS
    assert "secret" in SENSITIVE_BODY_KEYS
    assert "pow" in SENSITIVE_BODY_KEYS
    assert "hif" in SENSITIVE_BODY_KEYS
    assert "leim" in SENSITIVE_BODY_KEYS


if __name__ == "__main__":
    pytest.main([__file__, "-v"])