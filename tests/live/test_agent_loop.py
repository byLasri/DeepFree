"""Agent loop experiment - testing external tool calling via text."""

import json
from src.session import create_session_from_env
from src.deepseek.client import DeepSeekClient


def test_text_based_agent_loop():
    """Test if we can implement an external agent loop using text-based tool calls.

    Architecture:
    Agent (us) -> DeepSeek -> structured text tool call -> external executor -> tool result -> DeepSeek -> final answer
    """
    session = create_session_from_env()
    session.chat.chat_session_id = 'afad64f0-2ffa-424d-a316-1a1a26f17c35'
    client = DeepSeekClient(session)

    # This will fail due to expired PoW but demonstrates the pattern
    print("=== Text-based Agent Loop Experiment ===")
    print("Note: Requires fresh PoW from browser to work fully")
    print()

    # Define a simple tool
    tools = [
        {
            "name": "get_test_value",
            "description": "Returns a test value",
            "parameters": {"type": "object", "properties": {}},
        }
    ]

    # System prompt that instructs the model to use tools via text
    system_prompt = """You have access to the following tools:

{tools}

When you need to use a tool, respond with a JSON object in this format:
```json
{{
  "tool_call": {{
    "name": "tool_name",
    "arguments": {{}}
  }}
}}
```

After receiving the tool result, continue your response.""".format(tools=json.dumps(tools, indent=2))

    # Turn 1: Ask model to use tool
    print("--- Turn 1: Request tool use ---")
    try:
        result = client.send_completion(
            prompt=system_prompt + "\n\nUser: Please call get_test_value()",
        )
        print(f"Response: {result.response.content[:500]}")
    except Exception as e:
        print(f"Error (expected - PoW expired): {e}")

    # Turn 2: Simulate tool result
    print("\n--- Turn 2: Provide tool result ---")
    tool_result = {"value": 42}
    try:
        result = client.send_completion(
            prompt=f"Tool result: {json.dumps(tool_result)}",
            parent_message_id=None,  # Would use previous response_message_id
        )
        print(f"Response: {result.response.content[:500]}")
    except Exception as e:
        print(f"Error (expected - PoW expired): {e}")


if __name__ == "__main__":
    test_text_based_agent_loop()