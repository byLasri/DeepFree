import pytest
from datetime import datetime
from src.protocol.normalized_events import ProtocolRequest, ProtocolResponse, ConversationTurn, SessionState


def test_protocol_request_serialization():
    req = ProtocolRequest(
        chat_session_id="session-123",
        parent_message_id=5,
        model_type="expert",
        prompt="Hello world",
        thinking_enabled=True,
        search_enabled=False,
    )
    data = req.to_dict()
    assert data["chat_session_id"] == "session-123"
    assert data["parent_message_id"] == 5
    assert data["model_type"] == "expert"
    assert data["prompt"] == "Hello world"
    assert data["thinking_enabled"] is True
    assert data["search_enabled"] is False

    req2 = ProtocolRequest.from_dict(data)
    assert req2.chat_session_id == req.chat_session_id
    assert req2.parent_message_id == req.parent_message_id
    assert req2.prompt == req.prompt


def test_protocol_response_serialization():
    resp = ProtocolResponse(
        request_message_id=1,
        response_message_id=2,
        model_type="expert",
        content="Hello world",
        status="FINISHED",
        elapsed_secs=1.5,
        http_status=200,
        timing_ms=1500.0,
    )
    data = resp.to_dict()
    assert data["request_message_id"] == 1
    assert data["response_message_id"] == 2
    assert data["content"] == "Hello world"
    assert data["status"] == "FINISHED"
    assert data["http_status"] == 200

    json_str = resp.to_json()
    assert "Hello world" in json_str


def test_conversation_turn():
    req = ProtocolRequest(
        chat_session_id="session-123",
        parent_message_id=None,
        model_type="expert",
        prompt="Test",
    )
    resp = ProtocolResponse(
        request_message_id=1,
        response_message_id=2,
        content="Response",
    )
    turn = ConversationTurn(turn_number=1, request=req, response=resp)
    data = turn.to_dict()
    assert data["turn_number"] == 1
    assert data["request"]["prompt"] == "Test"
    assert data["response"]["content"] == "Response"


def test_session_state():
    session = SessionState(chat_session_id="session-123")
    assert session.chat_session_id == "session-123"
    assert session.current_parent_message_id is None
    assert session.message_counter == 0

    req1 = ProtocolRequest(chat_session_id="session-123", parent_message_id=None, model_type="expert", prompt="Turn 1")
    resp1 = ProtocolResponse(request_message_id=1, response_message_id=2, content="Response 1")
    session.add_turn(req1, resp1)

    assert session.message_counter == 1
    assert session.current_parent_message_id == 2
    assert len(session.turns) == 1

    req2 = session.get_next_request("Turn 2")
    assert req2.parent_message_id == 2
    assert req2.chat_session_id == "session-123"
    assert req2.prompt == "Turn 2"

    resp2 = ProtocolResponse(request_message_id=2, response_message_id=3, content="Response 2")
    session.add_turn(req2, resp2)

    assert session.message_counter == 2
    assert session.current_parent_message_id == 3
    assert len(session.turns) == 2

    data = session.to_dict()
    assert data["chat_session_id"] == "session-123"
    assert data["current_parent_message_id"] == 3
    assert data["message_counter"] == 2
    assert len(data["turns"]) == 2


def test_session_state_with_authorization():
    session = SessionState(chat_session_id="session-123", authorization="Bearer token123")
    assert session.authorization == "Bearer token123"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])