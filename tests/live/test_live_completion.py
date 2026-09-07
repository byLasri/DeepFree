"""Live tests requiring valid DeepSeek credentials.

Run with: DEEPFREE_LIVE_TESTS=1 pytest tests/live/ -v
"""
import pytest
from src.session import create_session_from_env
from src.deepseek.client import DeepSeekClient


@pytest.mark.live
def test_live_completion_basic():
    """Test basic completion with valid credentials."""
    session = create_session_from_env()
    assert session.auth.is_valid(), "DEEPSEEK_AUTHORIZATION not set"
    assert session.chat.chat_session_id, "DEEPSEEK_CHAT_SESSION_ID not set"

    client = DeepSeekClient(session)
    result = client.send_completion(prompt="Say hello")

    assert result.response.http_status == 200
    assert result.response.response_message_id is not None
    assert len(result.response.content) > 0
    print(f"Content: {result.response.content}")


@pytest.mark.live
def test_live_multi_turn():
    """Test multi-turn conversation."""
    session = create_session_from_env()
    assert session.auth.is_valid()
    assert session.chat.chat_chat_session_id

    client = DeepSeekClient(session)
    prompts = [
        "Remember this number: 4817",
        "What number did I ask you to remember?",
        "Add 83 to that number.",
    ]

    results = client.send_multi_turn(prompts)

    assert len(results) == 3
    for i, result in enumerate(results):
        assert result.response.response_message_id is not None
        assert result.response.http_status == 200
        print(f"Turn {i+1}: {result.response.content[:100]}")


@pytest.mark.live
def test_live_model_types():
    """Test different model_type values."""
    session = create_session_from_env()
    client = DeepSeekClient(session)

    for model_type in ["expert", "default"]:
        result = client.send_completion(prompt="test", model_type=model_type)
        assert result.response.http_status == 200
        assert result.response.response_message_id is not None


@pytest.mark.live
def test_live_search():
    """Test search_enabled flag."""
    session = create_session_from_env()
    client = DeepSeekClient(session)

    # Search disabled
    result1 = client.send_completion(
        prompt="What is 2+2?",
        search_enabled=False,
    )
    assert result1.response.http_status == 200

    # Search enabled
    result2 = client.send_completion(
        prompt="What is the current price of Bitcoin?",
        search_enabled=True,
    )
    assert result2.response.http_status == 200


@pytest.mark.live
def test_live_session_creation():
    """Test creating a new chat session."""
    session = create_session_from_env()
    client = DeepSeekClient(session)

    new_session_id = client.create_chat_session()
    assert new_session_id is not None
    assert len(new_session_id) > 0
    assert session.chat.chat_session_id == new_session_id
    assert session.chat.current_parent_message_id is None
    assert session.chat.message_counter == 0


@pytest.mark.live
def test_live_error_conditions():
    """Test various error conditions."""
    session = create_session_from_env()
    client = DeepSeekClient(session)

    # Invalid session ID
    session.chat.chat_session_id = "invalid"
    with pytest.raises(RuntimeError) as exc:
        client.send_completion(prompt="test")
    assert "422" in str(exc.value) or "UUID" in str(exc.value)

    # Reset to valid session
    session.chat.chat_session_id = create_session_from_env().chat.chat_session_id