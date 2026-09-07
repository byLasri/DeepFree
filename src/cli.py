import argparse
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import DeepSeekConfig
from src.deepseek.client import DeepSeekClient, create_client_from_env
from src.recorder.recorder import Recorder, create_har_recorder
from src.protocol.sse_parser import parse_sse_stream, normalize_events, reconstruct_response
from src.auth.investigation import AuthInvestigator, KNOWN_ENDPOINTS


def cmd_test_completion(args):
    config = DeepSeekConfig.from_env()
    if not config.is_configured():
        print("ERROR: DEEPSEEK_AUTHORIZATION and DEEPSEEK_CHAT_SESSION_ID must be set")
        return 1

    recorder = create_har_recorder("recordings") if args.record else None
    client = DeepSeekClient(config, recorder)

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
    print(f"Current Parent Message ID: {result.session_state.current_parent_message_id}")
    print(f"Total Turns: {result.session_state.message_counter}")

    if recorder:
        filepath = recorder.save()
        print(f"\nRecording saved to: {filepath}")

    return 0


def cmd_test_multi_turn(args):
    config = DeepSeekConfig.from_env()
    if not config.is_configured():
        print("ERROR: DEEPSEEK_AUTHORIZATION and DEEPSEEK_CHAT_SESSION_ID must be set")
        return 1

    recorder = create_har_recorder("recordings") if args.record else None
    client = DeepSeekClient(config, recorder)

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
    print(f"Current Parent Message ID: {results[-1].session_state.current_parent_message_id}")
    print(f"Total Turns: {results[-1].session_state.message_counter}")

    if recorder:
        filepath = recorder.save()
        print(f"\nRecording saved to: {filepath}")

    return 0


def cmd_investigate_auth(args):
    config = DeepSeekConfig.from_env()
    if not config.is_configured():
        print("ERROR: DEEPSEEK_AUTHORIZATION and DEEPSEEK_CHAT_SESSION_ID must be set")
        return 1

    recorder = create_har_recorder("recordings") if args.record else None
    investigator = AuthInvestigator(config, recorder)

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
    config = DeepSeekConfig.from_env()
    investigator = AuthInvestigator(config)

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

    p3 = subparsers.add_parser("investigate", help="Investigate auth endpoints")
    p3.add_argument("--endpoints", help="Comma-separated endpoint keys")
    p3.add_argument("--record", action="store_true", help="Record exchanges")
    p3.set_defaults(func=cmd_investigate_auth)

    p4 = subparsers.add_parser("compare-har", help="Compare requests from HAR file")
    p4.add_argument("har_file", help="Path to HAR file")
    p4.set_defaults(func=cmd_compare_har)

    p5 = subparsers.add_parser("parse-sse", help="Parse SSE stream from file")
    p5.add_argument("file", help="Path to SSE output file")
    p5.set_defaults(func=cmd_parse_sse)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    import json
    sys.exit(main())