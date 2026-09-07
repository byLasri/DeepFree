import time
import json
import requests
from typing import Optional, List
from dataclasses import dataclass

from ..session import DeepSeekSession, DynamicHeaders, StaticDynamicHeaderProvider, DynamicHeaderProvider
from ..protocol.sse_parser import parse_sse_stream, normalize_events, reconstruct_response, extract_message_ids
from ..protocol.normalized_events import ProtocolRequest, ProtocolResponse
from ..recorder.recorder import Recorder


@dataclass
class CompletionResult:
    response: ProtocolResponse
    session: DeepSeekSession
    raw_sse: str
    dynamic_headers_used: DynamicHeaders


class DeepSeekClient:
    def __init__(
        self,
        session: DeepSeekSession,
        recorder: Optional[Recorder] = None,
        dynamic_provider: Optional[DynamicHeaderProvider] = None,
    ):
        self.session = session
        self.recorder = recorder
        self.dynamic_provider = dynamic_provider or session.dynamic_header_provider or StaticDynamicHeaderProvider()
        self.http_session = requests.Session()

    def send_completion(
        self,
        prompt: str,
        parent_message_id: Optional[int] = None,
        model_type: str = "expert",
        thinking_enabled: bool = True,
        search_enabled: bool = False,
        action: str = "retry",
        preempt: bool = False,
        record: bool = True,
    ) -> CompletionResult:
        url = f"https://chat.deepseek.com/api/v0/chat/completion"

        request = ProtocolRequest(
            chat_session_id=self.session.chat.chat_session_id,
            parent_message_id=parent_message_id,
            model_type=model_type,
            prompt=prompt,
            thinking_enabled=thinking_enabled,
            search_enabled=search_enabled,
            action=action,
            preempt=preempt,
        )

        # Generate dynamic headers for this request
        dynamic = self.dynamic_provider.generate_headers(self.session, request.to_dict())

        headers = self.session.get_request_headers(dynamic)
        redacted_headers = self.session.get_redacted_headers(dynamic)
        body = request.to_dict()

        req_start = time.perf_counter()
        try:
            response = self.http_session.post(
                url,
                headers=headers,
                json=body,
                stream=True,
                timeout=120,
            )
        except requests.RequestException as e:
            raise RuntimeError(f"Request failed: {e}") from e

        req_timing = (time.perf_counter() - req_start) * 1000

        if response.status_code != 200:
            error_body = response.text[:500] if response.text else ""
            raise RuntimeError(f"HTTP {response.status_code}: {error_body}")

        resp_start = time.perf_counter()
        raw_sse = ""
        for chunk in response.iter_content(chunk_size=1024, decode_unicode=True):
            if chunk:
                raw_sse += chunk
        resp_timing = (time.perf_counter() - resp_start) * 1000

        sse_events = parse_sse_stream(raw_sse)
        normalized = normalize_events(sse_events)
        content = reconstruct_response(normalized)
        req_msg_id, resp_msg_id = extract_message_ids(normalized)

        protocol_response = ProtocolResponse(
            request_message_id=req_msg_id,
            response_message_id=resp_msg_id,
            model_type=model_type,
            content=content,
            http_status=response.status_code,
            timing_ms=req_timing + resp_timing,
        )

        for event in normalized:
            protocol_response.raw_events.append({
                "event_type": event.event_type.value,
                "data": event.data,
                "raw_data": event.raw_data,
            })
            for pu in event.path_updates:
                protocol_response.path_updates.append({
                    "path": pu.path,
                    "operation": pu.operation.value,
                    "value": pu.value,
                })
            if event.session_updated_at:
                protocol_response.session_updated_at = event.session_updated_at
            if event.title:
                protocol_response.title = event.title
            if event.close_click_behavior:
                protocol_response.close_click_behavior = event.close_click_behavior
            if event.close_auto_resume is not None:
                protocol_response.close_auto_resume = event.close_auto_resume
            if event.status:
                protocol_response.status = event.status
            if event.elapsed_secs:
                protocol_response.elapsed_secs = event.elapsed_secs

        # Update chat session state
        self.session.chat.add_turn(request, protocol_response)

        if record and self.recorder:
            self.recorder.record(
                url=url,
                method="POST",
                request_headers=redacted_headers,
                request_body=body,
                response_status=response.status_code,
                response_headers=dict(response.headers),
                response_body=raw_sse,
                sse_events=[{
                    "event_type": e.event_type.value,
                    "data": e.data,
                    "raw_data": e.raw_data,
                } for e in normalized],
                request_timing_ms=req_timing,
                response_timing_ms=resp_timing,
                metadata={
                    "prompt": prompt,
                    "parent_message_id": parent_message_id,
                    "model_type": model_type,
                },
            )

        return CompletionResult(
            response=protocol_response,
            session=self.session,
            raw_sse=raw_sse,
            dynamic_headers_used=dynamic,
        )

    def send_multi_turn(self, prompts: List[str], model_type: str = "expert") -> List[CompletionResult]:
        results = []
        parent_id = None
        for i, prompt in enumerate(prompts):
            result = self.send_completion(
                prompt=prompt,
                parent_message_id=parent_id,
                model_type=model_type,
            )
            results.append(result)
            parent_id = result.response.response_message_id
        return results

    def create_chat_session(self) -> str:
        """Create a new chat session via the API."""
        url = "https://chat.deepseek.com/api/v0/chat_session/create"
        dynamic = self.dynamic_provider.generate_headers(self.session, {})
        headers = self.session.get_request_headers(dynamic)
        redacted_headers = self.session.get_redacted_headers(dynamic)

        req_start = time.perf_counter()
        try:
            response = self.http_session.post(
                url,
                headers=headers,
                json={},
                timeout=30,
            )
        except requests.RequestException as e:
            raise RuntimeError(f"Session creation failed: {e}") from e

        req_timing = (time.perf_counter() - req_start) * 1000

        if response.status_code != 200:
            error_body = response.text[:500] if response.text else ""
            raise RuntimeError(f"HTTP {response.status_code}: {error_body}")

        data = response.json()
        if data.get("code") == 0:
            chat_data = data.get("data", {}).get("biz_data", {}).get("chat_session", {})
            new_session_id = chat_data.get("id")
            if new_session_id:
                self.session.chat.chat_session_id = new_session_id
                self.session.chat.current_parent_message_id = None
                self.session.chat.message_counter = 0
                return new_session_id

        raise RuntimeError(f"Failed to create session: {data}")


def create_client_from_env(recorder: Optional[Recorder] = None) -> DeepSeekClient:
    from ..session import create_session_from_env
    session = create_session_from_env()
    if not session.auth.is_valid() or not session.chat.chat_session_id:
        raise ValueError("DeepSeek credentials not configured. Set DEEPSEEK_AUTHORIZATION and DEEPSEEK_CHAT_SESSION_ID")
    return DeepSeekClient(session, recorder)