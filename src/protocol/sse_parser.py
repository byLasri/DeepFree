import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum


class SSEEventType(Enum):
    READY = "ready"
    UPDATE_SESSION = "update_session"
    TITLE = "title"
    CLOSE = "close"
    DATA = "data"


class OperationType(Enum):
    APPEND = "APPEND"
    SET = "SET"
    BATCH = "BATCH"
    UNKNOWN = "UNKNOWN"


@dataclass
class SSEEvent:
    event_type: SSEEventType
    data: dict
    raw_data: str
    event_name: Optional[str] = None
    id: Optional[str] = None
    retry: Optional[int] = None


@dataclass
class PathUpdate:
    path: str
    operation: OperationType
    value: Any
    raw_event: SSEEvent


@dataclass
class NormalizedEvent:
    event_type: SSEEventType
    request_message_id: Optional[int] = None
    response_message_id: Optional[int] = None
    model_type: Optional[str] = None
    session_updated_at: Optional[str] = None
    path_updates: list[PathUpdate] = field(default_factory=list)
    title: Optional[str] = None
    close_click_behavior: Optional[str] = None
    close_auto_resume: Optional[bool] = None
    raw_events: list[SSEEvent] = field(default_factory=list)
    status: Optional[str] = None
    elapsed_secs: Optional[float] = None
    content_fragments: list[str] = field(default_factory=list)
    raw_data: str = ""


def parse_sse_stream(raw_stream: str) -> list[SSEEvent]:
    events = []
    lines = raw_stream.split("\n")
    current_event = {}
    current_data = []

    for line in lines:
        line = line.rstrip("\r")
        if not line:
            if current_data or "event" in current_event:
                event = _build_event(current_event, "\n".join(current_data))
                if event:
                    events.append(event)
                current_event = {}
                current_data = []
            continue

        if line.startswith(":"):
            continue

        if line.startswith("event:"):
            current_event["event"] = line[6:].strip()
        elif line.startswith("id:"):
            current_event["id"] = line[3:].strip()
        elif line.startswith("retry:"):
            try:
                current_event["retry"] = int(line[6:].strip())
            except ValueError:
                pass
        elif line.startswith("data:"):
            current_data.append(line[5:].lstrip())
        else:
            if ":" in line:
                key, value = line.split(":", 1)
                current_event[key.strip()] = value.strip()

    if current_data or "event" in current_event:
        event = _build_event(current_event, "\n".join(current_data))
        if event:
            events.append(event)

    return events


def _build_event(event_dict: dict, data_str: str) -> Optional[SSEEvent]:
    if not data_str and "event" not in event_dict:
        return None

    event_name = event_dict.get("event")
    try:
        data = json.loads(data_str) if data_str else {}
    except json.JSONDecodeError:
        data = {"raw": data_str}

    if event_name:
        try:
            event_type = SSEEventType(event_name)
        except ValueError:
            event_type = SSEEventType.DATA
    else:
        event_type = SSEEventType.DATA

    return SSEEvent(
        event_type=event_type,
        data=data,
        raw_data=data_str,
        event_name=event_name,
        id=event_dict.get("id"),
        retry=event_dict.get("retry"),
    )


def normalize_events(events: list[SSEEvent]) -> list[NormalizedEvent]:
    normalized = []
    for event in events:
        norm = _normalize_single_event(event)
        normalized.append(norm)
    return normalized


def _normalize_single_event(event: SSEEvent) -> NormalizedEvent:
    norm = NormalizedEvent(event_type=event.event_type, raw_events=[event], raw_data=event.raw_data)

    if event.event_type == SSEEventType.READY:
        norm.request_message_id = event.data.get("request_message_id")
        norm.response_message_id = event.data.get("response_message_id")
        norm.model_type = event.data.get("model_type")

    elif event.event_type == SSEEventType.UPDATE_SESSION:
        norm.session_updated_at = event.data.get("updated_at")

    elif event.event_type == SSEEventType.TITLE:
        norm.title = event.data.get("content")

    elif event.event_type == SSEEventType.CLOSE:
        norm.close_click_behavior = event.data.get("click_behavior")
        norm.close_auto_resume = event.data.get("auto_resume")

    if event.event_type == SSEEventType.DATA:
        if isinstance(event.data, dict):
            if "v" in event.data:
                v = event.data["v"]
                if isinstance(v, dict) and "response" in v:
                    resp = v["response"]
                    norm.response_message_id = resp.get("message_id")
                    norm.request_message_id = resp.get("parent_id")
                path = event.data.get("p")
                op_str = event.data.get("o")
                value = event.data.get("v")
                if path:
                    try:
                        op = OperationType(op_str)
                    except ValueError:
                        op = OperationType.UNKNOWN
                    norm.path_updates.append(
                        PathUpdate(path=path, operation=op, value=value, raw_event=event)
                    )
                    _extract_content_from_path(norm, path, value)

            if "response" in event.data:
                resp = event.data["response"]
                norm.response_message_id = resp.get("message_id")
                norm.request_message_id = resp.get("parent_id")
                if "status" in resp:
                    norm.status = resp["status"]

    return norm


def _extract_content_from_path(norm: NormalizedEvent, path: str, value: Any):
    if path == "response/fragments/-1/content" and isinstance(value, str):
        norm.content_fragments.append(value)
    elif path == "response/fragments/-1/elapsed_secs" and isinstance(value, (int, float)):
        norm.elapsed_secs = float(value)
    elif path == "response/status" and isinstance(value, str):
        norm.status = value


def reconstruct_response(normalized_events: list[NormalizedEvent]) -> str:
    fragments = []
    for event in normalized_events:
        fragments.extend(event.content_fragments)
    return "".join(fragments)


def extract_message_ids(normalized_events: list[NormalizedEvent]) -> tuple[Optional[int], Optional[int]]:
    request_id = None
    response_id = None
    for event in normalized_events:
        if event.request_message_id is not None:
            request_id = event.request_message_id
        if event.response_message_id is not None:
            response_id = event.response_message_id
    return request_id, response_id


def extract_session_info(normalized_events: list[NormalizedEvent]) -> dict:
    info = {}
    for event in normalized_events:
        if event.session_updated_at:
            info["updated_at"] = event.session_updated_at
        if event.title:
            info["title"] = event.title
        if event.close_click_behavior:
            info["close_click_behavior"] = event.close_click_behavior
        if event.close_auto_resume is not None:
            info["close_auto_resume"] = event.close_auto_resume
    return info