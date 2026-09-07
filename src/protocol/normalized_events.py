from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime
import json


@dataclass
class ProtocolRequest:
    chat_session_id: str
    parent_message_id: Optional[int]
    model_type: str
    prompt: str
    ref_file_ids: list = field(default_factory=list)
    thinking_enabled: bool = True
    search_enabled: bool = False
    action: str = "retry"
    preempt: bool = False

    def to_dict(self) -> dict:
        return {
            "chat_session_id": self.chat_session_id,
            "parent_message_id": self.parent_message_id,
            "model_type": self.model_type,
            "prompt": self.prompt,
            "ref_file_ids": self.ref_file_ids,
            "thinking_enabled": self.thinking_enabled,
            "search_enabled": self.search_enabled,
            "action": self.action,
            "preempt": self.preempt,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProtocolRequest":
        return cls(
            chat_session_id=data.get("chat_session_id", ""),
            parent_message_id=data.get("parent_message_id"),
            model_type=data.get("model_type", "expert"),
            prompt=data.get("prompt", ""),
            ref_file_ids=data.get("ref_file_ids", []),
            thinking_enabled=data.get("thinking_enabled", True),
            search_enabled=data.get("search_enabled", False),
            action=data.get("action", "retry"),
            preempt=data.get("preempt", False),
        )


@dataclass
class ProtocolResponse:
    request_message_id: Optional[int] = None
    response_message_id: Optional[int] = None
    model_type: Optional[str] = None
    content: str = ""
    status: Optional[str] = None
    elapsed_secs: Optional[float] = None
    title: Optional[str] = None
    session_updated_at: Optional[str] = None
    close_click_behavior: Optional[str] = None
    close_auto_resume: Optional[bool] = None
    raw_events: list[dict] = field(default_factory=list)
    path_updates: list[dict] = field(default_factory=list)
    http_status: int = 0
    timing_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "request_message_id": self.request_message_id,
            "response_message_id": self.response_message_id,
            "model_type": self.model_type,
            "content": self.content,
            "status": self.status,
            "elapsed_secs": self.elapsed_secs,
            "title": self.title,
            "session_updated_at": self.session_updated_at,
            "close_click_behavior": self.close_click_behavior,
            "close_auto_resume": self.close_auto_resume,
            "raw_events": self.raw_events,
            "path_updates": self.path_updates,
            "http_status": self.http_status,
            "timing_ms": self.timing_ms,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class ConversationTurn:
    turn_number: int
    request: ProtocolRequest
    response: ProtocolResponse
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "turn_number": self.turn_number,
            "request": self.request.to_dict(),
            "response": self.response.to_dict(),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class SessionState:
    chat_session_id: str
    current_parent_message_id: Optional[int] = None
    message_counter: int = 0
    turns: list[ConversationTurn] = field(default_factory=list)
    cookies: dict = field(default_factory=dict)
    authorization: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    def add_turn(self, request: ProtocolRequest, response: ProtocolResponse):
        self.message_counter += 1
        turn = ConversationTurn(
            turn_number=self.message_counter,
            request=request,
            response=response,
        )
        self.turns.append(turn)
        if response.response_message_id:
            self.current_parent_message_id = response.response_message_id

    def get_next_request(self, prompt: str, model_type: str = "expert") -> ProtocolRequest:
        return ProtocolRequest(
            chat_session_id=self.chat_session_id,
            parent_message_id=self.current_parent_message_id,
            model_type=model_type,
            prompt=prompt,
        )

    def to_dict(self) -> dict:
        return {
            "chat_session_id": self.chat_session_id,
            "current_parent_message_id": self.current_parent_message_id,
            "message_counter": self.message_counter,
            "turns": [t.to_dict() for t in self.turns],
            "created_at": self.created_at.isoformat(),
        }