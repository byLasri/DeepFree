import argparse
import sys
import os
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.session import create_session_from_env, DeepSeekSession, StaticDynamicHeaderProvider
from src.deepseek.client import DeepSeekClient, create_client_from_env
from src.recorder.recorder import Recorder, create_har_recorder
from src.protocol.sse_parser import parse_sse_stream, normalize_events, reconstruct_response
from src.auth.investigation import AuthInvestigator, KNOWN_ENDPOINTS


def cmd_test_completion(args):
    session = create_session_from_env()
    if not session.auth.is_valid() or not session.chat.chat_session_id:
        print("ERROR: DEEPSEEK_AUTHORIZATION and DEEPSEEK_CHAT_SESSION_ID must be set")
        return 1

    recorder = create_har_recorder("recordings") if args.record else None
    client = DeepSeekClient(session, recorder)

    print(f"Sending prompt: {args.prompt}")
    result = client.send_completion(
        prompt=args.prompt,
        parent_message_id=args.parent_id,
        model_type=args.model,
        thinking_enabled=not args.no_thinking,
        search_enabled=args.search,
    )

    print(f"\nHTTP Status: {result.response.http_status}")
    print(f"Timing: {result.response.timing_ms:.2f}ms")
    print(f"Request Message ID: {result.response.request_message_id}")
    print(f"Response Message ID: {result.response.response_message_id}")
    print(f"Model Type: {result.response.model_type}")
    print(f"Status: {result.response.status}")
    print(f"Title: {result.response.title}")
    print(f"Elapsed: {result.response.elapsed_secs}s")
    print(f"\n--- Response Content ---")
    print(result.response.content)
    print(f"\n--- Session State ---")
    print(f"Chat Session ID: {result.session.chat.chat_session_id}")
    print(f"Current Parent Message ID: {result.session.chat.current_parent_message_id}")
    print(f"Total Turns: {result.session.chat.message_counter}")
    print(f"Dynamic Headers Used: pow={bool(result.dynamic_headers_used.x_ds_pow_response)}, hif={bool(result.dynamic_headers_used.x_hif_leim)}")

    if recorder:
        filepath = recorder.save()
        print(f"\nRecording saved to: {filepath}")

    return 0


def cmd_test_multi_turn(args):
    session = create_session_from_env()
    if not session.auth.is_valid() or not session.chat.chat_session_id:
        print("ERROR: DEEPSEEK_AUTHORIZATION and DEEPSEEK_CHAT_SESSION_ID must be set")
        return 1

    recorder = create_har_recorder("recordings") if args.record else None
    client = DeepSeekClient(session, recorder)

    prompts = args.prompts if args.prompts else [
        "Remember this number: 12345",
        "What number did I ask you to remember?",
    ]

    print(f"Running {len(prompts)} turns...")
    results = client.send_multi_turn(prompts, model_type=args.model)

    for i, result in enumerate(results):
        print(f"\n=== Turn {i+1} ===")
        print(f"Prompt: {prompts[i]}")
        print(f"Response Message ID: {result.response.response_message_id}")
        print(f"Content: {result.response.content[:200]}...")

    print(f"\n=== Final Session State ===")
    print(f"Chat Session ID: {results[-1].session.chat.chat_session_id}")
    print(f"Current Parent Message ID: {results[-1].session.chat.current_parent_message_id}")
    print(f"Total Turns: {results[-1].session.chat.message_counter}")

    if recorder:
        filepath = recorder.save()
        print(f"\nRecording saved to: {filepath}")

    return 0


def cmd_create_session(args):
    session = create_session_from_env()
    if not session.auth.is_valid():
        print("ERROR: DEEPSEEK_AUTHORIZATION must be set")
        return 1

    recorder = create_har_recorder("recordings") if args.record else None
    client = DeepSeekClient(session, recorder)

    print("Creating new chat session...")
    try:
        new_session_id = client.create_chat_session()
        print(f"Created chat session: {new_session_id}")
        print(f"Session state updated: chat_session_id={session.chat.chat_session_id}")
        return 0
    except Exception as e:
        print(f"ERROR: {e}")
        return 1


def cmd_investigate_auth(args):
    session = create_session_from_env()
    if not session.auth.is_valid():
        print("ERROR: DEEPSEEK_AUTHORIZATION must be set")
        return 1

    recorder = create_har_recorder("recordings") if args.record else None
    investigator = AuthInvestigator(session.auth, recorder)

    endpoints = args.endpoints.split(",") if args.endpoints else list(KNOWN_ENDPOINTS.keys())

    for ep in endpoints:
        print(f"\n=== Investigating {ep} ===")
        result = investigator.investigate_endpoint(ep.strip())
        print(json.dumps(result, indent=2))

    if recorder:
        filepath = recorder.save()
        print(f"\nRecording saved to: {filepath}")

    return 0


def cmd_compare_har(args):
    session = create_session_from_env()
    investigator = AuthInvestigator(session.auth)

    result = investigator.compare_requests(args.har_file)
    print(json.dumps(result, indent=2))
    return 0


def cmd_parse_sse(args):
    with open(args.file, "r") as f:
        raw = f.read()

    events = parse_sse_stream(raw)
    normalized = normalize_events(events)
    content = reconstruct_response(normalized)

    print(f"Parsed {len(events)} raw SSE events")
    print(f"Normalized to {len(normalized)} events")
    print(f"Reconstructed content length: {len(content)}")
    print(f"\nContent:\n{content}")

    for i, event in enumerate(normalized):
        print(f"\n--- Event {i} ---")
        print(f"Type: {event.event_type.value}")
        if event.request_message_id:
            print(f"Request Message ID: {event.request_message_id}")
        if event.response_message_id:
            print(f"Response Message ID: {event.response_message_id}")
        if event.session_updated_at:
            print(f"Session Updated: {event.session_updated_at}")
        if event.title:
            print(f"Title: {event.title}")
        if event.status:
            print(f"Status: {event.status}")
        if event.path_updates:
            print(f"Path Updates: {len(event.path_updates)}")
            for pu in event.path_updates[:5]:
                print(f"  {pu.path} {pu.operation.value} = {str(pu.value)[:100]}")

    return 0


def cmd_replay_matrix(args):
    """Test which headers are required by making requests with different header combinations."""
    session = create_session_from_env()
    if not session.auth.is_valid() or not session.chat.chat_session_id:
        print("ERROR: DEEPSEEK_AUTHORIZATION and DEEPSEEK_CHAT_SESSION_ID must be set")
        return 1

    print("=== Replay Matrix Test ===")
    print("This tests which headers are actually required by the server.")
    print("Note: PoW from .env is likely expired (single-use).")
    print()

    import requests
    import time

    url = "https://chat.deepseek.com/api/v0/chat/completion"
    base_body = {
        "chat_session_id": session.chat.chat_session_id,
        "parent_message_id": None,
        "model_type": "expert",
        "prompt": "test",
        "ref_file_ids": [],
        "thinking_enabled": True,
        "search_enabled": False,
        "action": "retry",
        "preempt": False,
    }

    # Test different header combinations
    tests = [
        ("All headers (from .env)", True, True, True, True),
        ("No PoW", True, False, True, True),
        ("No hif-leim", True, True, False, True),
        ("No PoW, no hif-leim", True, False, False, True),
        ("Only auth + cookie", True, False, False, False),
        ("No auth", False, True, True, True),
        ("No cookie", True, True, True, False),
    ]

    for name, use_auth, use_pow, use_hif, use_cookie in tests:
        headers = {
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Host": "chat.deepseek.com",
            "Origin": "https://chat.deepseek.com",
            "Referer": f"https://chat.deepseek.com/a/chat/s/{session.chat.chat_session_id}",
            "User-Agent": session.auth.user_agent,
            "x-client-bundle-id": "com.deepseek.chat",
            "x-client-locale": "en_US",
            "x-client-platform": "web",
            "x-client-version": "2.4.0",
            "x-client-timezone-offset": "-25200",
        }
        if use_auth and session.auth.authorization:
            headers["Authorization"] = f"Bearer {session.auth.authorization}"
        if use_cookie:
            cookie_header = session.auth.get_cookie_header()
            if cookie_header:
                headers["Cookie"] = cookie_header
        if use_pow and session.dynamic_header_provider:
            # This won't work with static provider but tests the path
            pow_val = getattr(session.dynamic_header_provider, 'pow_response', '')
            if pow_val:
                headers["x-ds-pow-response"] = pow_val
        if use_hif and session.dynamic_header_provider:
            hif_val = getattr(session.dynamic_header_provider, 'hif_leim', '')
            if hif_val:
                headers["x-hif-leim"] = hif_val

        print(f"\n--- Test: {name} ---")
        print(f"  Headers: auth={use_auth}, pow={use_pow}, hif={use_hif}, cookie={use_cookie}")

        try:
            resp = requests.post(url, headers=headers, json=base_body, timeout=30, stream=True)
            print(f"  Status: {resp.status_code}")
            # Read a bit of response
            raw = ""
            for chunk in resp.iter_content(chunk_size=1024, decode_unicode=True):
                if chunk:
                    raw += chunk
                    if len(raw) > 200:
                        break
            if raw:
                print(f"  Response: {raw[:200]}...")
        except Exception as e:
            print(f"  Error: {e}")

    return 0


def main():
    parser = argparse.ArgumentParser(description="DeepSeek Web Protocol Investigation Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p1 = subparsers.add_parser("completion", help="Test single completion")
    p1.add_argument("prompt", help="Prompt to send")
    p1.add_argument("--parent-id", type=int, help="Parent message ID")
    p1.add_argument("--model", default="expert", help="Model type")
    p1.add_argument("--no-thinking", action="store_true", help="Disable thinking")
    p1.add_argument("--search", action="store_true", help="Enable search")
    p1.add_argument("--record", action="store_true", help="Record exchange")
    p1.set_defaults(func=cmd_test_completion)

    p2 = subparsers.add_parser("multi-turn", help="Test multi-turn conversation")
    p2.add_argument("prompts", nargs="*", help="Prompts for each turn")
    p2.add_argument("--model", default="expert", help="Model type")
    p2.add_argument("--record", action="store_true", help="Record exchanges")
    p2.set_defaults(func=cmd_test_multi_turn)

    p3 = subparsers.add_parser("create-session", help="Create new chat session")
    p3.add_argument("--record", action="store_true", help="Record exchange")
    p3.set_defaults(func=cmd_create_session)

    p4 = subparsers.add_parser("investigate", help="Investigate auth endpoints")
    p4.add_argument("--endpoints", help="Comma-separated endpoint keys")
    p4.add_argument("--record", action="store_true", help="Record exchanges")
    p4.set_defaults(func=cmd_investigate_auth)

    p5 = subparsers.add_parser("compare-har", help="Compare requests from HAR file")
    p5.add_argument("har_file", help="Path to HAR file")
    p5.set_defaults(func=cmd_compare_har)

    p6 = subparsers.add_parser("parse-sse", help="Parse SSE stream from file")
    p6.add_argument("file", help="Path to SSE output file")
    p6.set_defaults(func=cmd_parse_sse)

    p7 = subparsers.add_parser("replay-matrix", help="Test which headers are required")
    p7.set_defaults(func=cmd_replay_matrix)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())