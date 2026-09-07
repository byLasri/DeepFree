import json
import os
from dataclasses import dataclass, asdict
from typing import Any, Optional
from datetime import datetime
from pathlib import Path

from ..config import DeepSeekConfig


SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "x-ds-pow-response",
    "x-hif-leim",
    "x-ds-pow-challenge",
    "x-csrf-token",
    "x-xsrf-token",
}

SENSITIVE_BODY_KEYS = {
    "authorization",
    "token",
    "password",
    "secret",
    "key",
    "session",
    "cookie",
    "pow",
    "hif",
    "leim",
}


@dataclass
class RecordedRequest:
    url: str
    method: str
    headers: dict
    body: Optional[dict] = None
    timestamp: str = ""
    timing_ms: float = 0.0


@dataclass
class RecordedResponse:
    status: int
    headers: dict
    body: Optional[str] = None
    sse_events: list[dict] = None
    timestamp: str = ""
    timing_ms: float = 0.0

    def __post_init__(self):
        if self.sse_events is None:
            self.sse_events = []


@dataclass
class RecordedExchange:
    request: RecordedRequest
    response: RecordedResponse
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class Recorder:
    def __init__(self, output_dir: str = "recordings"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.exchanges: list[RecordedExchange] = []

    def record(
        self,
        url: str,
        method: str,
        request_headers: dict,
        request_body: Optional[dict],
        response_status: int,
        response_headers: dict,
        response_body: Optional[str],
        sse_events: Optional[list[dict]] = None,
        request_timing_ms: float = 0.0,
        response_timing_ms: float = 0.0,
        metadata: Optional[dict] = None,
    ):
        redacted_req_headers = self._redact_headers(request_headers)
        redacted_resp_headers = self._redact_headers(response_headers)
        redacted_req_body = self._redact_body(request_body) if request_body else None
        redacted_resp_body = self._redact_body(response_body) if response_body else None
        redacted_sse = self._redact_sse_events(sse_events) if sse_events else None

        exchange = RecordedExchange(
            request=RecordedRequest(
                url=url,
                method=method,
                headers=redacted_req_headers,
                body=redacted_req_body,
                timestamp=datetime.now().isoformat(),
                timing_ms=request_timing_ms,
            ),
            response=RecordedResponse(
                status=response_status,
                headers=redacted_resp_headers,
                body=redacted_resp_body,
                sse_events=redacted_sse,
                timestamp=datetime.now().isoformat(),
                timing_ms=response_timing_ms,
            ),
            metadata=metadata or {},
        )
        self.exchanges.append(exchange)
        return exchange

    def _redact_headers(self, headers: dict) -> dict:
        redacted = {}
        for k, v in headers.items():
            if k.lower() in SENSITIVE_HEADERS:
                redacted[k] = "[REDACTED]"
            else:
                redacted[k] = v
        return redacted

    def _redact_body(self, body: Any) -> Any:
        if isinstance(body, str):
            try:
                parsed = json.loads(body)
                return self._redact_dict(parsed)
            except json.JSONDecodeError:
                return "[REDACTED: non-JSON body]"
        elif isinstance(body, dict):
            return self._redact_dict(body)
        elif isinstance(body, list):
            return [self._redact_body(item) for item in body]
        return body

    def _redact_dict(self, d: dict) -> dict:
        redacted = {}
        for k, v in d.items():
            if any(sensitive in k.lower() for sensitive in SENSITIVE_BODY_KEYS):
                redacted[k] = "[REDACTED]"
            elif isinstance(v, dict):
                redacted[k] = self._redact_dict(v)
            elif isinstance(v, list):
                redacted[k] = [self._redact_body(item) for item in v]
            else:
                redacted[k] = v
        return redacted

    def _redact_sse_events(self, events: list[dict]) -> list[dict]:
        redacted = []
        for event in events:
            if isinstance(event, dict):
                new_event = {}
                for k, v in event.items():
                    if k == "data" and isinstance(v, dict):
                        new_event[k] = self._redact_dict(v)
                    else:
                        new_event[k] = v
                redacted.append(new_event)
            else:
                redacted.append(event)
        return redacted

    def save(self, filename: Optional[str] = None) -> str:
        if not filename:
            filename = f"recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = self.output_dir / filename
        data = {
            "recorded_at": datetime.now().isoformat(),
            "exchanges": [self._exchange_to_dict(ex) for ex in self.exchanges],
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return str(filepath)

    def _exchange_to_dict(self, exchange: RecordedExchange) -> dict:
        return {
            "request": asdict(exchange.request),
            "response": asdict(exchange.response),
            "metadata": exchange.metadata,
        }

    def load(self, filepath: str) -> list[RecordedExchange]:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.exchanges = []
        for ex_data in data.get("exchanges", []):
            req = RecordedRequest(**ex_data["request"])
            resp = RecordedResponse(**ex_data["response"])
            self.exchanges.append(RecordedExchange(request=req, response=resp, metadata=ex_data.get("metadata", {})))
        return self.exchanges


def create_har_recorder(output_dir: str = "recordings") -> Recorder:
    return Recorder(output_dir)