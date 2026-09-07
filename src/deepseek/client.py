import time
import json
import requests
from typing import Optional, Generator
from dataclasses import dataclass

from ..config import DeepSeekConfig
from ..protocol.sse_parser import parse_sse_stream, normalize_events, reconstruct_response, extract_message_ids
from ..protocol.normalized_events import ProtocolRequest, ProtocolResponse, SessionState
from ..recorder.recorder import Recorder


@dataclass
class CompletionResult:
    response: ProtocolResponse
    session_state: SessionState
    raw_sse: str


class DeepSeekClient:
    def __init__(self, config: DeepSeekConfig, recorder: Optional[Recorder] = None):
        self.config = config
        self.recorder = recorder
        self.session = requests.Session()
        self.session_state = SessionState(chat_session_id=config.chat_session_id)
        self.session_state.authorization = config.authorization
        if config.cookie:
            self._parse_cookies(config.cookie)

    def _parse_cookies(self, cookie_str: str):
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                self.session_state.cookies[k.strip()] = v.strip()

    def _get_headers(self, include_dynamic: bool = True) -> dict:
        return self.config.get_headers(include_dynamic)

    def _get_redacted_headers(self, include_dynamic: bool = True) -> dict:
        return self.config.get_redacted_headers(include_dynamic)

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
        url = f"{self.config.base_url}/api/v0/chat/completion"

        request = ProtocolRequest(
            chat_session_id=self.config.chat_session_id,
            parent_message_id=parent_message_id,
            model_type=model_type,
            prompt=prompt,
            thinking_enabled=thinking_enabled,
            search_enabled=search_enabled,
            action=action,
            preempt=preempt,
        )

        headers = self._get_headers()
        redacted_headers = self._get_redacted_headers()
        body = request.to_dict()

        req_start = time.perf_counter()
        try:
            response = self.session.post(
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

        self.session_state.add_turn(request, protocol_response)

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
            session_state=self.session_state,
            raw_sse=raw_sse,
        )

    def send_multi_turn(self, prompts: list[str], model_type: str = "expert") -> list[CompletionResult]:
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


def create_client_from_env(recorder: Optional[Recorder] = None) -> DeepSeekClient:
    config = DeepSeekConfig.from_env()
    if not config.is_configured():
        raise ValueError("DeepSeek credentials not configured. Set DEEPSEEK_AUTHORIZATION and DEEPSEEK_CHAT_SESSION_ID")
    return DeepSeekClient(config, recorder)